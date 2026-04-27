"""Google Lighthouse scan service for government websites.

Runs the Lighthouse CLI via subprocess and extracts key audit scores
(performance, accessibility, best-practices, SEO, PWA) for each URL.

Requires the ``lighthouse`` CLI to be installed globally:
    npm install -g lighthouse

Chrome / Chromium must also be available on the system PATH.  In GitHub
Actions the ``ubuntu-latest`` runner ships with Chromium pre-installed.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence


@dataclass(slots=True)
class LighthouseScanResult:
    """Result of a Google Lighthouse scan for a single URL."""

    url: str
    performance_score: float | None = None    # 0.0–1.0
    accessibility_score: float | None = None  # 0.0–1.0
    best_practices_score: float | None = None  # 0.0–1.0
    seo_score: float | None = None             # 0.0–1.0
    pwa_score: float | None = None             # 0.0–1.0
    error_message: str | None = None
    scanned_at: str | None = None


def _parse_lighthouse_output(raw_json: str) -> Dict[str, float | None]:
    """Parse the Lighthouse JSON output and return category scores.

    Args:
        raw_json: Raw JSON string from Lighthouse ``--output json``.

    Returns:
        Dictionary with keys ``performance``, ``accessibility``,
        ``best-practices``, ``seo``, ``pwa`` mapped to float scores
        (0.0–1.0) or ``None`` when the category was not run.

    Raises:
        ValueError: When the JSON cannot be parsed or has no categories.
    """
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON output from Lighthouse: {exc}") from exc

    categories = data.get("categories")
    if not categories:
        raise ValueError("Lighthouse output contains no 'categories' key")

    def _score(key: str) -> float | None:
        cat = categories.get(key, {})
        return cat.get("score")

    return {
        "performance": _score("performance"),
        "accessibility": _score("accessibility"),
        "best-practices": _score("best-practices"),
        "seo": _score("seo"),
        "pwa": _score("pwa"),
    }


class LighthouseScanner:
    """
    Service that runs Google Lighthouse audits on government websites.

    Each URL is audited using the Lighthouse CLI in a subprocess.  The
    resulting JSON report is parsed and the five headline category scores
    are extracted:

    * **Performance** – page speed and user-experience metrics.
    * **Accessibility** – WCAG-aligned accessibility checks.
    * **Best Practices** – security and modern web best practices.
    * **SEO** – search-engine optimisation fundamentals.
    * **PWA** – Progressive Web App checks.

    All scores are returned on a 0.0–1.0 scale (multiply by 100 for
    the familiar 0–100 Lighthouse display value).
    """

    # Chrome flags required for headless operation in CI and sandboxed envs.
    _DEFAULT_CHROME_FLAGS = (
        "--headless "
        "--no-sandbox "
        "--disable-dev-shm-usage "
        "--disable-gpu"
    )

    def __init__(
        self,
        timeout_seconds: int = 120,
        lighthouse_path: str = "lighthouse",
        chrome_flags: str | None = None,
        extra_args: List[str] | None = None,
        only_categories: Sequence[str] | None = None,
        throttling_method: str | None = None,
    ):
        """
        Args:
            timeout_seconds: Maximum wall-clock seconds to wait for a single
                Lighthouse run.  Lighthouse can be slow (30–90 s per URL).
            lighthouse_path: Path to the ``lighthouse`` binary.  Defaults to
                searching the system ``PATH``.
            chrome_flags: Chrome flags string passed to
                ``--chrome-flags``.  ``None`` uses the default headless flags.
            extra_args: Additional CLI arguments appended to every Lighthouse
                invocation (e.g. ``["--only-categories=accessibility"]``).
            only_categories: When provided, pass
                ``--only-categories=<comma-joined>`` to Lighthouse to skip
                unwanted audit categories and speed up each run.  Common
                value for government sites:
                ``["performance", "accessibility", "best-practices", "seo"]``.
            throttling_method: When provided, pass
                ``--throttling-method=<value>`` to Lighthouse.  Use
                ``"provided"`` to skip simulated slow-network throttling
                (appropriate for server-to-server audits).
        """
        self.timeout_seconds = timeout_seconds
        self.lighthouse_path = lighthouse_path
        self.chrome_flags = chrome_flags if chrome_flags is not None else self._DEFAULT_CHROME_FLAGS

        # Build extra_args from explicit flags + caller-supplied list.
        built_extra: List[str] = list(extra_args or [])
        if only_categories:
            built_extra.append(f"--only-categories={','.join(only_categories)}")
        if throttling_method:
            built_extra.append(f"--throttling-method={throttling_method}")
        self.extra_args = built_extra

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_command(self, url: str) -> List[str]:
        """Return the subprocess command list for scanning *url*."""
        cmd = [
            self.lighthouse_path,
            url,
            "--output=json",
            "--output-path=stdout",
            "--quiet",
            f"--chrome-flags={self.chrome_flags}",
        ]
        cmd.extend(self.extra_args)
        return cmd

    def _run_lighthouse(self, url: str) -> str:
        """Run Lighthouse synchronously and return stdout.

        Raises:
            subprocess.TimeoutExpired: When the process exceeds *timeout_seconds*.
            subprocess.CalledProcessError: When Lighthouse exits non-zero.
            FileNotFoundError: When the ``lighthouse`` binary is not found.
        """
        cmd = self._build_command(url)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        if result.returncode != 0 and not result.stdout.strip():
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )
        return result.stdout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scan_url(self, url: str) -> LighthouseScanResult:
        """
        Run a Lighthouse audit on a single URL.

        The Lighthouse CLI is CPU-bound, so the subprocess is dispatched
        to a thread-pool executor so it does not block the event loop.

        Returns:
            LighthouseScanResult with category scores or an error message.
        """
        scanned_at = datetime.now(timezone.utc).isoformat()

        try:
            loop = asyncio.get_event_loop()
            stdout = await loop.run_in_executor(None, self._run_lighthouse, url)
        except FileNotFoundError:
            return LighthouseScanResult(
                url=url,
                error_message=(
                    "Lighthouse CLI not found. "
                    "Install it with: npm install -g lighthouse"
                ),
                scanned_at=scanned_at,
            )
        except subprocess.TimeoutExpired:
            return LighthouseScanResult(
                url=url,
                error_message=f"Lighthouse timed out after {self.timeout_seconds}s",
                scanned_at=scanned_at,
            )
        except subprocess.CalledProcessError as exc:
            return LighthouseScanResult(
                url=url,
                error_message=f"Lighthouse exited with code {exc.returncode}: {exc.stderr[:200]}",
                scanned_at=scanned_at,
            )
        except Exception as exc:  # noqa: BLE001
            return LighthouseScanResult(
                url=url,
                error_message=f"Unexpected error: {exc}",
                scanned_at=scanned_at,
            )

        try:
            scores = _parse_lighthouse_output(stdout)
        except ValueError as exc:
            return LighthouseScanResult(
                url=url,
                error_message=str(exc),
                scanned_at=scanned_at,
            )

        return LighthouseScanResult(
            url=url,
            performance_score=scores["performance"],
            accessibility_score=scores["accessibility"],
            best_practices_score=scores["best-practices"],
            seo_score=scores["seo"],
            pwa_score=scores["pwa"],
            scanned_at=scanned_at,
        )

    async def scan_urls_batch(
        self,
        urls: List[str],
        rate_limit_per_second: float = 0.2,
        max_runtime_seconds: Optional[float] = None,
        start_time: Optional[float] = None,
        on_result: Optional[Callable[["LighthouseScanResult"], None]] = None,
        concurrency: int = 1,
    ) -> Dict[str, "LighthouseScanResult"]:
        """
        Run Lighthouse audits for multiple URLs with rate limiting and
        optional concurrency.

        Lighthouse is slow (30–90 s per URL), so the default rate limit is
        0.2 req/s (one request every 5 seconds) to avoid overloading
        government servers.  Setting *concurrency* > 1 allows multiple
        Lighthouse processes to run simultaneously, which can significantly
        improve throughput when the bottleneck is network I/O rather than CPU.

        Args:
            urls: List of URLs to audit.
            rate_limit_per_second: Minimum gap between *starting* new
                Lighthouse processes.  With concurrency > 1 this controls
                how quickly new processes are submitted, not how quickly they
                complete.
            max_runtime_seconds: Stop scanning early when this many seconds
                have elapsed since *start_time*, leaving a 60-second safety
                buffer.  ``None`` means no limit.
            start_time: ``time.monotonic()`` value recorded at the start of
                the overall job.  ``None`` uses the first call to this method.
            on_result: Optional callback invoked immediately after each URL
                is scanned.  Useful for incremental persistence so that
                partial results survive a timeout.
            concurrency: Maximum number of Lighthouse processes to run in
                parallel.  Defaults to 1 (sequential).  Values > 1 increase
                throughput but consume more CPU and memory.

        Returns:
            Dictionary mapping URL to LighthouseScanResult.  When stopped
            early the dict contains only the URLs that were actually scanned.
        """
        results: Dict[str, LighthouseScanResult] = {}
        delay = 1.0 / rate_limit_per_second if rate_limit_per_second > 0 else 0
        # Cap delay at 120 seconds to prevent accidental freezes.
        delay = min(delay, 120.0)

        _start = start_time if start_time is not None else time.monotonic()
        _safety_buffer = 60.0
        semaphore = asyncio.Semaphore(max(1, concurrency))

        total = len(urls)

        async def _scan_one_url(idx: int, url: str) -> None:
            """Scan a single URL, respecting the concurrency semaphore."""
            async with semaphore:
                print(f"  [{idx}/{total}] Scanning: {url}")
                result = await self.scan_url(url)
                results[url] = result

                if on_result is not None:
                    on_result(result)

                if result.error_message:
                    print(f"      ✗ {result.error_message}")
                else:
                    perf = (
                        f"{result.performance_score * 100:.0f}"
                        if result.performance_score is not None
                        else "—"
                    )
                    a11y = (
                        f"{result.accessibility_score * 100:.0f}"
                        if result.accessibility_score is not None
                        else "—"
                    )
                    print(f"      ✓ perf={perf} a11y={a11y}")

        tasks: List[asyncio.Task] = []
        stopped_early = False
        for idx, url in enumerate(urls, 1):
            if max_runtime_seconds is not None:
                elapsed = time.monotonic() - _start
                remaining = max_runtime_seconds - elapsed
                if remaining < _safety_buffer:
                    print(
                        f"  ⏱️  Time budget near limit "
                        f"({elapsed / 60:.1f}m elapsed, "
                        f"{remaining / 60:.1f}m remaining) "
                        f"— stopping after submitting {len(tasks)}/{total} URLs"
                    )
                    stopped_early = True
                    break

            tasks.append(asyncio.create_task(_scan_one_url(idx, url)))

            if delay > 0:
                await asyncio.sleep(delay)

        if tasks:
            if stopped_early and max_runtime_seconds is not None:
                # Give in-flight tasks the remainder of the budget, then cancel
                # any that are still waiting for the semaphore (not yet scanning).
                elapsed = time.monotonic() - _start
                wait_budget = max(0.0, max_runtime_seconds - elapsed - _safety_buffer)
                done, pending = await asyncio.wait(tasks, timeout=wait_budget)
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    except Exception as exc:  # noqa: BLE001
                        print(f"      ✗ Unexpected error in cancelled task: {exc}")
                # Surface any unexpected exceptions from completed tasks.
                for task in done:
                    exc = task.exception()
                    if exc is not None:
                        print(f"      ✗ Unexpected task error: {exc}")
            else:
                task_results = await asyncio.gather(*tasks, return_exceptions=True)
                for task_result in task_results:
                    if isinstance(task_result, BaseException):
                        print(f"      ✗ Unexpected task error: {task_result}")

        return results
