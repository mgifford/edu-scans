"""Accessibility overlay scanner for government websites.

Fetches a page and checks whether any known accessibility overlay products
are present.  Accessibility overlays are third-party scripts marketed as
one-click accessibility fixes; they are controversial because they do not
reliably make inaccessible sites accessible and have been associated with
increased legal risk.

Detection is intentionally conservative — a positive result indicates a
*signal*, not a definitive conclusion.  Overlay vendors change their
implementation details frequently, so the signature list should be reviewed
and updated periodically.

References:
  - https://github.com/mgifford/Find-Overlays
  - https://overlayfactsheet.com/
  - https://almanac.httparchive.org/en/2024/accessibility#user-personalization-widgets-and-overlay-remediation
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx


# ---------------------------------------------------------------------------
# Known accessibility overlay signatures.
# Each entry maps a vendor name to a list of case-insensitive substrings that,
# when found anywhere in the page HTML, indicate the overlay is present.
# Based on https://github.com/mgifford/Find-Overlays (OVERLAY_SIGNATURES).
# ---------------------------------------------------------------------------

OVERLAY_SIGNATURES: Dict[str, List[str]] = {
    "AccessiBe": ["accessibe.com", "acsbapp", "acsb.js"],
    "Accessibility Adapter": ["accessibilityadapter.com", "accessibility-adapter"],
    "Accessiblelink": ["accessiblelink.com"],
    "Accessiplus": ["accessiplus"],
    "Accessiway": ["accessiway"],
    "Adally": ["adally.com", "adally.js"],
    "Adapte Mon Web": ["adaptemonweb"],
    "AdaptifY": ["adaptify"],
    "Allyable": ["allyable.com", "allyable.js"],
    "Alchemy": ["alchemyai", "alchemyaccessibility"],
    "Amaze": ["amazeaccess", "amaze/accessibility"],
    "AudioEye": ["audioeye.com", "audioeye.js"],
    "Bakh Fix": ["bakhfix"],
    "DIGIaccess": ["digiaccess"],
    "Eye-Able": ["eye-able.com", "eye-able-cdn"],
    "Equally.ai": ["equally.ai"],
    "EqualWeb": ["equalweb.com", "nagishli"],
    "FACIL'iti": ["facil-iti", "facil_iti"],
    "MaxAccess": ["maxaccess"],
    "Poloda AI": ["poloda"],
    "Purple Lens (Pluro)": ["purplelens", "pluro"],
    "ReciteME": ["reciteme.com", "recite.js"],
    "RentCafe": ["rentcafe.com/accessibility"],
    "Sentinel": ["sentinel-accessibility"],
    "TruAbilities": ["truabilities"],
    "True Accessibility": ["trueaccessibility"],
    "UsableNet (Assistive)": ["usablenet.com", "usablenet_assistive"],
    "UserWay": ["userway.org", "userway.js"],
    "WebAbility": ["webability"],
}


@dataclass(slots=True)
class OverlayScanResult:
    """Result of an overlay scan for a single URL."""

    url: str
    is_reachable: bool = True
    overlays: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    scanned_at: Optional[str] = None

    @property
    def overlay_count(self) -> int:
        """Number of distinct overlay products detected."""
        return len(self.overlays)

    @property
    def has_overlay(self) -> bool:
        """True when at least one overlay product was detected."""
        return len(self.overlays) > 0


def _detect_overlays(html: str) -> List[str]:
    """Return a list of overlay vendor names detected in *html*.

    Matching is case-insensitive and uses simple substring search, which is
    fast enough for single-page scans and matches the approach used by the
    reference Find-Overlays tool.

    Args:
        html: Raw HTML source of the page.

    Returns:
        Sorted list of vendor names whose signatures appear in the HTML.
    """
    html_lower = html.lower()
    detected: List[str] = []
    for vendor, signatures in OVERLAY_SIGNATURES.items():
        for sig in signatures:
            if sig in html_lower:
                detected.append(vendor)
                break  # only add each vendor once
    return sorted(detected)


class OverlayScanner:
    """Service for scanning government website pages for accessibility overlays.

    Fetches each URL with httpx and checks the page HTML against a list of
    known overlay vendor signatures.  Designed to mirror the pattern of
    :class:`~src.services.third_party_js_scanner.ThirdPartyJsScanner`.
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

    def scan_html(
        self,
        url: str,
        html: str,
        scanned_at: Optional[str] = None,
    ) -> OverlayScanResult:
        """Analyse pre-fetched HTML for accessibility overlay signatures.

        Use this when the page content has already been retrieved (e.g. by a
        multi-scanner that shares a single HTTP request across several analyses).

        Args:
            url: The original URL requested.
            html: Raw HTML of the page.
            scanned_at: ISO-8601 timestamp string.  Defaults to *now* in UTC.

        Returns:
            :class:`OverlayScanResult` with ``is_reachable=True``.
        """
        if scanned_at is None:
            scanned_at = datetime.now(timezone.utc).isoformat()

        try:
            overlays = _detect_overlays(html)
        except Exception as exc:  # noqa: BLE001
            return OverlayScanResult(
                url=url,
                is_reachable=True,
                error_message=f"Parse error: {exc}",
                scanned_at=scanned_at,
            )

        return OverlayScanResult(
            url=url,
            is_reachable=True,
            overlays=overlays,
            scanned_at=scanned_at,
        )

    async def scan_url(self, url: str) -> OverlayScanResult:
        """Scan a single URL for accessibility overlay signatures.

        Args:
            url: The URL to fetch and scan.

        Returns:
            :class:`OverlayScanResult` with detected overlay vendor names.
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

        except httpx.TooManyRedirects as exc:
            return OverlayScanResult(
                url=url,
                is_reachable=False,
                error_message=f"Too many redirects: {exc}",
                scanned_at=scanned_at,
            )
        except httpx.TimeoutException as exc:
            return OverlayScanResult(
                url=url,
                is_reachable=False,
                error_message=f"Timeout: {exc}",
                scanned_at=scanned_at,
            )
        except httpx.ConnectError as exc:
            return OverlayScanResult(
                url=url,
                is_reachable=False,
                error_message=f"Connection error: {exc}",
                scanned_at=scanned_at,
            )
        except httpx.HTTPError as exc:
            return OverlayScanResult(
                url=url,
                is_reachable=False,
                error_message=f"HTTP error: {exc}",
                scanned_at=scanned_at,
            )
        except Exception as exc:  # noqa: BLE001
            return OverlayScanResult(
                url=url,
                is_reachable=False,
                error_message=f"Unexpected error: {exc}",
                scanned_at=scanned_at,
            )

        return self.scan_html(url, html, scanned_at=scanned_at)

    async def scan_urls_batch(
        self,
        urls: List[str],
        rate_limit_per_second: float = 2.0,
        max_runtime_seconds: Optional[float] = None,
        start_time: Optional[float] = None,
        on_result: Optional[Callable[["OverlayScanResult"], None]] = None,
    ) -> Dict[str, "OverlayScanResult"]:
        """Scan multiple URLs for accessibility overlays with rate limiting.

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
                scanned (before the inter-request delay).  Useful for incremental
                persistence so that partial results survive a timeout.

        Returns:
            Dictionary mapping URL to :class:`OverlayScanResult`.  When stopped
            early the dict contains only the URLs that were scanned.
        """
        results: Dict[str, OverlayScanResult] = {}
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

            if result.error_message:
                print(f"      ✗ {result.error_message}")
            else:
                if result.overlays:
                    print(f"      ⚠  Overlays detected: {', '.join(result.overlays)}")
                else:
                    print("      ✓ No overlays detected")

            if delay > 0:
                await asyncio.sleep(delay)

        return results
