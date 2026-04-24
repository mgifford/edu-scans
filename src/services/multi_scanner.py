"""Multi-scanner: fetch a URL once and apply multiple analyses in parallel.

Each individual scanner (social media, accessibility, technology, third-party JS)
normally makes its own HTTP request for the same URL.  This module provides
:class:`MultiScanner`, which fetches a page **once** and then runs all four
HTML-based analyses concurrently against the single response, eliminating
redundant network traffic.

The Lighthouse scanner is *excluded* because it drives a full browser via
subprocess and cannot reuse a pre-fetched HTML response.  URL validation is
also excluded because it focuses on reachability / redirect chains rather than
page content analysis.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone


import httpx

from src.services.accessibility_scanner import (
    AccessibilityScanResult,
    AccessibilityScanner,
)
from src.services.social_media_scanner import (
    SocialMediaScanResult,
    SocialMediaScanner,
)
from src.services.tech_detector import TechDetectionResult, TechDetector
from src.services.third_party_js_scanner import (
    ThirdPartyJsScanResult,
    ThirdPartyJsScanner,
)


@dataclass
class MultiScanResult:
    """Combined result of all HTML-based scans for a single URL.

    All four sub-results share the same HTTP response, so only one network
    round-trip is made per URL regardless of how many analyses are requested.
    """

    url: str
    """The URL that was scanned."""

    is_reachable: bool
    """Whether the page could be fetched successfully."""

    final_url: str | None = None
    """The URL after any redirects (``None`` when the fetch failed)."""

    error_message: str | None = None
    """HTTP-level error message when ``is_reachable`` is ``False``."""

    accessibility: AccessibilityScanResult | None = None
    """Accessibility statement link detection result."""

    social_media: SocialMediaScanResult | None = None
    """Social media link detection result."""

    tech: TechDetectionResult | None = None
    """Technology fingerprinting result."""

    third_party_js: ThirdPartyJsScanResult | None = None
    """Third-party JavaScript detection result."""

    scanned_at: str | None = None
    """ISO-8601 UTC timestamp of when the scan was performed."""


class MultiScanner:
    """Fetch a URL once and apply multiple HTML-based analyses concurrently.

    By default all four scanners (accessibility, social media, technology
    detection, third-party JS) are run.  Pass a subset via the constructor
    arguments to skip specific analyses.

    Example::

        scanner = MultiScanner()
        result = await scanner.scan_url("https://example.gov/")
        print(result.social_media.social_tier)
        print(result.accessibility.has_statement)
        print(result.tech.technologies)
        print(result.third_party_js.third_party_count)
    """

    def __init__(
        self,
        timeout_seconds: int = 20,
        max_redirects: int = 10,
        user_agent: str = "EU-Government-Accessibility-Scanner/1.0",
        run_accessibility: bool = True,
        run_social_media: bool = True,
        run_tech: bool = True,
        run_third_party_js: bool = True,
    ):
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self.user_agent = user_agent
        self.run_accessibility = run_accessibility
        self.run_social_media = run_social_media
        self.run_tech = run_tech
        self.run_third_party_js = run_third_party_js

        self._accessibility = AccessibilityScanner(
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
            user_agent=user_agent,
        )
        self._social_media = SocialMediaScanner(
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
            user_agent=user_agent,
        )
        self._tech = TechDetector(
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
            user_agent=user_agent,
        )
        self._third_party_js = ThirdPartyJsScanner(
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
            user_agent=user_agent,
        )

    async def scan_url(self, url: str) -> MultiScanResult:
        """Fetch *url* once and run all enabled analyses against the response.

        When the page cannot be fetched (network error, timeout, etc.) the
        returned :class:`MultiScanResult` has ``is_reachable=False`` and all
        sub-results are ``None``.

        Args:
            url: The URL to scan.

        Returns:
            :class:`MultiScanResult` containing sub-results for every enabled
            scanner.
        """
        scanned_at = datetime.now(timezone.utc).isoformat()

        # --- Fetch the page once -----------------------------------------------
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=self.max_redirects,
                timeout=self.timeout_seconds,
            ) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": self.user_agent},
                )
                html = response.text
                headers = dict(response.headers)
                final_url = str(response.url)

        except httpx.TooManyRedirects as exc:
            return MultiScanResult(
                url=url,
                is_reachable=False,
                error_message=f"Too many redirects: {exc}",
                scanned_at=scanned_at,
            )
        except httpx.TimeoutException as exc:
            return MultiScanResult(
                url=url,
                is_reachable=False,
                error_message=f"Timeout: {exc}",
                scanned_at=scanned_at,
            )
        except httpx.ConnectError as exc:
            return MultiScanResult(
                url=url,
                is_reachable=False,
                error_message=f"Connection error: {exc}",
                scanned_at=scanned_at,
            )
        except httpx.HTTPError as exc:
            return MultiScanResult(
                url=url,
                is_reachable=False,
                error_message=f"HTTP error: {exc}",
                scanned_at=scanned_at,
            )
        except Exception as exc:  # noqa: BLE001
            return MultiScanResult(
                url=url,
                is_reachable=False,
                error_message=f"Unexpected error: {exc}",
                scanned_at=scanned_at,
            )

        # --- Run all enabled analyses concurrently against the fetched HTML ----
        tasks: list[asyncio.Future] = []
        task_names: list[str] = []

        if self.run_accessibility:
            tasks.append(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    self._accessibility.scan_html,
                    url,
                    html,
                    scanned_at,
                )
            )
            task_names.append("accessibility")

        if self.run_social_media:
            tasks.append(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    self._social_media.scan_html,
                    url,
                    html,
                    scanned_at,
                )
            )
            task_names.append("social_media")

        if self.run_tech:
            tasks.append(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    self._tech.detect_html,
                    url,
                    html,
                    headers,
                    final_url,
                    scanned_at,
                )
            )
            task_names.append("tech")

        if self.run_third_party_js:
            tasks.append(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    self._third_party_js.scan_html,
                    url,
                    html,
                    final_url,
                    scanned_at,
                )
            )
            task_names.append("third_party_js")

        sub_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Map results back to their named fields
        result_map: dict[str, object] = {
            "accessibility": None,
            "social_media": None,
            "tech": None,
            "third_party_js": None,
        }
        for name, sub in zip(task_names, sub_results):
            if isinstance(sub, Exception):
                # Wrap unexpected exceptions in a minimal error result
                if name == "accessibility":
                    result_map[name] = AccessibilityScanResult(
                        url=url,
                        is_reachable=True,
                        error_message=f"Unexpected error: {sub}",
                        scanned_at=scanned_at,
                    )
                elif name == "social_media":
                    result_map[name] = SocialMediaScanResult(
                        url=url,
                        is_reachable=True,
                        error_message=f"Unexpected error: {sub}",
                        scanned_at=scanned_at,
                    )
                elif name == "tech":
                    result_map[name] = TechDetectionResult(
                        url=url,
                        technologies={},
                        error_message=f"Unexpected error: {sub}",
                        scanned_at=scanned_at,
                    )
                elif name == "third_party_js":
                    result_map[name] = ThirdPartyJsScanResult(
                        url=url,
                        is_reachable=True,
                        error_message=f"Unexpected error: {sub}",
                        scanned_at=scanned_at,
                    )
            else:
                result_map[name] = sub

        return MultiScanResult(
            url=url,
            is_reachable=True,
            final_url=final_url,
            accessibility=result_map["accessibility"],
            social_media=result_map["social_media"],
            tech=result_map["tech"],
            third_party_js=result_map["third_party_js"],
            scanned_at=scanned_at,
        )

    async def scan_urls_batch(
        self,
        urls: list[str],
        rate_limit_per_second: float = 2.0,
        max_runtime_seconds: float | None = None,
        start_time: float | None = None,
        on_result: Callable[["MultiScanResult"], None] | None = None,
    ) -> dict[str, "MultiScanResult"]:
        """Scan multiple URLs with rate limiting.

        Each URL is fetched **once** regardless of how many analyses are
        enabled.  Results are returned as soon as they are available; the
        optional *on_result* callback can be used for incremental persistence.

        Args:
            urls: List of URLs to scan.
            rate_limit_per_second: Maximum requests per second.
            max_runtime_seconds: Stop scanning early when this many seconds have
                elapsed since *start_time*, leaving a 60-second safety buffer.
                ``None`` means no limit.
            start_time: ``time.monotonic()`` value recorded at the start of the
                overall job.  When ``None`` the clock starts at the first call
                to this method.
            on_result: Optional callback invoked immediately after each URL is
                scanned.  Useful for incremental persistence so that partial
                results survive a timeout.

        Returns:
            Dictionary mapping URL to :class:`MultiScanResult`.  When stopped
            early the dict contains only the URLs that were actually scanned.
        """
        results: dict[str, MultiScanResult] = {}
        delay = 1.0 / rate_limit_per_second if rate_limit_per_second > 0 else 0
        delay = min(delay, 60.0)

        _start = start_time if start_time is not None else time.monotonic()
        _safety_buffer = 60.0

        total = len(urls)
        for idx, url in enumerate(urls, 1):
            if max_runtime_seconds is not None:
                elapsed = time.monotonic() - _start
                remaining = max_runtime_seconds - elapsed
                if remaining < _safety_buffer:
                    print(
                        f"  ⏱️  Time budget near limit "
                        f"({elapsed / 60:.1f}m elapsed, "
                        f"{remaining / 60:.1f}m remaining) "
                        f"— stopping after {idx - 1}/{total} URLs"
                    )
                    break

            print(f"  [{idx}/{total}] Scanning: {url}")
            result = await self.scan_url(url)
            results[url] = result

            if on_result is not None:
                on_result(result)

            _print_result_summary(result)

            if delay > 0:
                await asyncio.sleep(delay)

        return results


def _print_result_summary(result: MultiScanResult) -> None:
    """Print a one-line summary for a completed multi-scan."""
    if not result.is_reachable:
        print(f"      ✗ Unreachable: {result.error_message}")
        return

    parts: list[str] = []

    if result.accessibility is not None:
        if result.accessibility.has_statement:
            parts.append("♿ statement found")
        else:
            parts.append("♿ no statement")

    if result.social_media is not None:
        parts.append(f"📱 {result.social_media.social_tier}")

    if result.tech is not None:
        tech_count = len(result.tech.technologies)
        parts.append(f"🔧 {tech_count} tech")

    if result.third_party_js is not None:
        js_count = result.third_party_js.third_party_count
        parts.append(f"📜 {js_count} 3pjs")

    print(f"      ✓ {' | '.join(parts)}")
