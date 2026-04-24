"""Technology detection service using Wappalyzer for government websites."""

from __future__ import annotations

import asyncio
import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx


WebPage = None
"""Lazily imported Wappalyzer WebPage class.

Keeping this import out of module scope prevents the whole CLI from crashing
at import time when the optional Wappalyzer dependency stack is misconfigured.
"""


@dataclass(slots=True)
class TechDetectionResult:
    """Result of a technology detection check for a single URL."""
    url: str
    technologies: Dict[str, Dict]  # {tech_name: {versions: [...], categories: [...]}}
    error_message: str | None = None
    scanned_at: str | None = None


class TechDetector:
    """
    Service for detecting technologies used by government websites.

    Uses python-Wappalyzer to fingerprint technologies from HTTP response
    headers and HTML content.  Page content is fetched with the project's
    standard httpx client and the resulting HTML/headers are passed directly
    to Wappalyzer, avoiding a separate aiohttp dependency.
    """

    def __init__(
        self,
        timeout_seconds: int = 20,
        max_redirects: int = 10,
        user_agent: str = "EU-Government-Accessibility-Scanner/1.0",
    ):
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self.user_agent = user_agent
        self._wappalyzer = None  # lazily initialised

    def _get_wappalyzer(self):
        """Return a cached Wappalyzer instance (lazy init to avoid import cost)."""
        if self._wappalyzer is None:
            from Wappalyzer import Wappalyzer

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self._wappalyzer = Wappalyzer.latest()
        return self._wappalyzer

    def _build_webpage(self, url: str, html: str, headers: dict):
        """Return a Wappalyzer WebPage instance for the fetched content."""
        webpage_cls = WebPage
        if webpage_cls is None:
            from Wappalyzer import WebPage as webpage_cls
        return webpage_cls(url, html, headers)

    def detect_html(
        self,
        url: str,
        html: str,
        headers: dict,
        final_url: str | None = None,
        scanned_at: str | None = None,
    ) -> "TechDetectionResult":
        """
        Detect technologies from pre-fetched HTML and response headers.

        Use this when the page content has already been retrieved (e.g. by a
        multi-scanner that shares a single HTTP request across several analyses).

        Args:
            url: The original URL requested.
            html: Raw HTML of the page.
            headers: HTTP response headers as a plain dict.
            final_url: The URL after redirects (uses *url* when not provided).
            scanned_at: ISO-8601 timestamp string.  Defaults to *now* in UTC.

        Returns:
            :class:`TechDetectionResult` with detected technologies.
        """
        if scanned_at is None:
            scanned_at = datetime.now(timezone.utc).isoformat()

        try:
            webpage = self._build_webpage(final_url or url, html, headers)
            wappalyzer = self._get_wappalyzer()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                technologies = wappalyzer.analyze_with_versions_and_categories(webpage)
        except Exception as exc:  # noqa: BLE001
            return TechDetectionResult(
                url=url,
                technologies={},
                error_message=f"Analysis error: {exc}",
                scanned_at=scanned_at,
            )

        return TechDetectionResult(
            url=url,
            technologies=technologies,
            scanned_at=scanned_at,
        )

    async def detect_url(self, url: str) -> TechDetectionResult:
        """
        Detect technologies used by a single URL.

        Fetches the page with httpx and passes the HTML and response headers
        to Wappalyzer for fingerprinting.

        Returns:
            TechDetectionResult with detected technologies or an error message.
        """
        scanned_at = datetime.now(timezone.utc).isoformat()

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
                # httpx headers are case-insensitive; convert to plain dict for Wappalyzer
                headers = dict(response.headers)
                final_url = str(response.url)

        except httpx.TooManyRedirects as exc:
            return TechDetectionResult(
                url=url,
                technologies={},
                error_message=f"Too many redirects: {exc}",
                scanned_at=scanned_at,
            )
        except httpx.TimeoutException as exc:
            return TechDetectionResult(
                url=url,
                technologies={},
                error_message=f"Timeout: {exc}",
                scanned_at=scanned_at,
            )
        except httpx.ConnectError as exc:
            return TechDetectionResult(
                url=url,
                technologies={},
                error_message=f"Connection error: {exc}",
                scanned_at=scanned_at,
            )
        except httpx.HTTPError as exc:
            return TechDetectionResult(
                url=url,
                technologies={},
                error_message=f"HTTP error: {exc}",
                scanned_at=scanned_at,
            )
        except Exception as exc:  # noqa: BLE001
            return TechDetectionResult(
                url=url,
                technologies={},
                error_message=f"Unexpected error: {exc}",
                scanned_at=scanned_at,
            )

        return self.detect_html(url, html, headers, final_url=final_url, scanned_at=scanned_at)

    async def detect_urls_batch(
        self,
        urls: List[str],
        rate_limit_per_second: float = 2.0,
        max_runtime_seconds: Optional[float] = None,
        start_time: Optional[float] = None,
        on_result: Optional[Callable[["TechDetectionResult"], None]] = None,
    ) -> Dict[str, TechDetectionResult]:
        """
        Detect technologies for multiple URLs with rate limiting.

        Args:
            urls: List of URLs to analyse.
            rate_limit_per_second: Maximum requests per second.
            max_runtime_seconds: Stop scanning early when this many seconds have
                elapsed since *start_time*, leaving a 60-second safety buffer.
                ``None`` means no limit.
            start_time: ``time.monotonic()`` value recorded at the start of the
                overall job.  When ``None`` the clock starts at the first call
                to this method.
            on_result: Optional callback invoked immediately after each URL is
                scanned (before the inter-request delay).  Useful for incremental
                persistence so that partial results survive a timeout.

        Returns:
            Dictionary mapping URL to TechDetectionResult.  When stopped
            early the dict contains only the URLs that were actually scanned.
        """
        results: Dict[str, TechDetectionResult] = {}
        delay = 1.0 / rate_limit_per_second if rate_limit_per_second > 0 else 0
        # Cap the delay at 60 seconds to prevent accidental freezes from very
        # small (but positive) rate_limit_per_second values.
        delay = min(delay, 60.0)

        _start = start_time if start_time is not None else time.monotonic()
        # Stop scanning this many seconds before the hard deadline so the
        # caller has time to flush results and upload artifacts.
        _safety_buffer = 60.0

        total = len(urls)
        for idx, url in enumerate(urls, 1):
            # Check remaining runtime budget before making the next request.
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
            result = await self.detect_url(url)
            results[url] = result

            if on_result is not None:
                on_result(result)

            if result.error_message:
                print(f"      ✗ {result.error_message}")
            else:
                tech_names = ", ".join(result.technologies.keys()) or "(none detected)"
                print(f"      ✓ {tech_names}")

            if delay > 0:
                await asyncio.sleep(delay)

        return results
