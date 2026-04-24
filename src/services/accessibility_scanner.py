"""Accessibility statement scanner for government websites.

Fetches a page, inspects the footer for links whose text or href matches
multilingual accessibility-statement terms as required by the EU Web
Accessibility Directive (Directive 2016/2102).

See: https://web-directive.eu/#toc20
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from src.glossary.accessibility_terms import ACCESSIBILITY_URL_PATTERNS, ALL_TERMS


@dataclass(slots=True)
class AccessibilityScanResult:
    """Result of an accessibility statement scan for a single URL."""

    url: str
    is_reachable: bool
    # Links found in the page footer that look like accessibility statements.
    statement_links: List[str] = field(default_factory=list)
    # The matched term(s) from the glossary that triggered each detection.
    matched_terms: List[str] = field(default_factory=list)
    # Whether an accessibility statement link was found in the footer.
    has_statement: bool = False
    # Whether the link was found specifically in a <footer> element.
    found_in_footer: bool = False
    error_message: str | None = None
    scanned_at: str | None = None


def _normalise(text: str) -> str:
    """Lower-case and collapse whitespace for term matching."""
    return " ".join(text.lower().split())


def _href_matches(href: str) -> bool:
    """Return True when the URL path fragment suggests an accessibility page."""
    path = urlparse(href).path.lower()
    return any(pattern in path for pattern in ACCESSIBILITY_URL_PATTERNS)


def _text_matches(text: str) -> tuple[bool, str]:
    """
    Return (True, matched_term) when the visible link text contains a known
    accessibility-statement term from the multilingual glossary.
    """
    normalised = _normalise(text)
    for term in ALL_TERMS:
        if term in normalised:
            return True, term
    return False, ""


def _extract_accessibility_links(
    html: str, base_url: str
) -> tuple[list[str], list[str], bool]:
    """
    Parse HTML and extract links that look like accessibility statements.

    Scans footer elements first; falls back to scanning the entire page so
    that sites that do not use a semantic <footer> element are still covered.

    Returns:
        (statement_links, matched_terms, found_in_footer)
    """
    soup = BeautifulSoup(html, "html.parser")

    links: list[str] = []
    terms: list[str] = []
    found_in_footer = False

    # Search footer elements first (preferred location per the Directive).
    footer_elements = soup.find_all("footer")
    # Also check elements with role="contentinfo" (ARIA equivalent of <footer>).
    footer_elements += soup.find_all(attrs={"role": "contentinfo"})
    # And elements with a footer-related class or id.
    footer_elements += soup.find_all(
        True,
        attrs={
            "class": lambda c: c
            and any(
                "footer" in cls.lower() for cls in (c if isinstance(c, list) else [c])
            )
        },
    )
    footer_elements += soup.find_all(
        True,
        attrs={"id": lambda i: i and "footer" in i.lower()},
    )

    # Deduplicate footer elements while preserving order.
    seen_ids: set[int] = set()
    unique_footer_elements = []
    for el in footer_elements:
        if id(el) not in seen_ids:
            seen_ids.add(id(el))
            unique_footer_elements.append(el)

    def _process_anchor(tag, in_footer: bool) -> None:
        href = tag.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            return

        visible_text = tag.get_text(separator=" ")
        text_hit, matched_term = _text_matches(visible_text)
        href_hit = _href_matches(href)

        if not text_hit and not href_hit:
            return

        # Resolve relative URLs.
        abs_href = urljoin(base_url, href)

        if abs_href not in links:
            links.append(abs_href)
            terms.append(matched_term or href)
            if in_footer:
                nonlocal found_in_footer
                found_in_footer = True

    for footer_el in unique_footer_elements:
        for tag in footer_el.find_all("a", href=True):
            _process_anchor(tag, in_footer=True)

    # If nothing found in footer, scan the full page as a fallback.
    if not links:
        for tag in soup.find_all("a", href=True):
            _process_anchor(tag, in_footer=False)

    return links, terms, found_in_footer


class AccessibilityScanner:
    """
    Service for scanning government website pages for accessibility statement links.

    Fetches each URL with httpx, parses the HTML with BeautifulSoup, and
    identifies links to accessibility statements using multilingual term
    matching against the EU Web Accessibility Directive glossary.  The footer
    is checked first; the full page is used as a fallback.
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
        scanned_at: str | None = None,
    ) -> "AccessibilityScanResult":
        """
        Analyse pre-fetched HTML for accessibility statement links.

        Use this when the page content has already been retrieved (e.g. by a
        multi-scanner that shares a single HTTP request across several analyses).

        Args:
            url: The URL the HTML was fetched from (used for base-URL resolution
                and as the ``url`` field in the returned result).
            html: Raw HTML of the page.
            scanned_at: ISO-8601 timestamp string.  Defaults to *now* in UTC.

        Returns:
            :class:`AccessibilityScanResult` with ``is_reachable=True``.
        """
        if scanned_at is None:
            scanned_at = datetime.now(timezone.utc).isoformat()

        try:
            statement_links, matched_terms, found_in_footer = (
                _extract_accessibility_links(html, url)
            )
        except Exception as exc:  # noqa: BLE001
            return AccessibilityScanResult(
                url=url,
                is_reachable=True,
                error_message=f"Parse error: {exc}",
                scanned_at=scanned_at,
            )

        return AccessibilityScanResult(
            url=url,
            is_reachable=True,
            statement_links=statement_links,
            matched_terms=matched_terms,
            has_statement=bool(statement_links),
            found_in_footer=found_in_footer,
            scanned_at=scanned_at,
        )

    async def scan_url(self, url: str) -> "AccessibilityScanResult":
        """
        Scan a single URL for accessibility statement links.

        Returns:
            AccessibilityScanResult with detected links and metadata.
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
            return AccessibilityScanResult(
                url=url,
                is_reachable=False,
                error_message=f"Too many redirects: {exc}",
                scanned_at=scanned_at,
            )
        except httpx.TimeoutException as exc:
            return AccessibilityScanResult(
                url=url,
                is_reachable=False,
                error_message=f"Timeout: {exc}",
                scanned_at=scanned_at,
            )
        except httpx.ConnectError as exc:
            return AccessibilityScanResult(
                url=url,
                is_reachable=False,
                error_message=f"Connection error: {exc}",
                scanned_at=scanned_at,
            )
        except httpx.HTTPError as exc:
            return AccessibilityScanResult(
                url=url,
                is_reachable=False,
                error_message=f"HTTP error: {exc}",
                scanned_at=scanned_at,
            )
        except Exception as exc:  # noqa: BLE001
            return AccessibilityScanResult(
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
        on_result: Optional[Callable[["AccessibilityScanResult"], None]] = None,
    ) -> Dict[str, "AccessibilityScanResult"]:
        """
        Scan multiple URLs for accessibility statement links with rate limiting.

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
            Dictionary mapping URL to AccessibilityScanResult.  When stopped
            early the dict contains only the URLs that were actually scanned.
        """
        results: Dict[str, AccessibilityScanResult] = {}
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

            if result.error_message and not result.is_reachable:
                print(f"      ✗ {result.error_message}")
            elif result.has_statement:
                footer_flag = " (footer)" if result.found_in_footer else ""
                print(
                    f"      ✓ Accessibility statement found{footer_flag}: "
                    f"{result.statement_links[0]}"
                )
            else:
                print("      – No accessibility statement detected")

            if delay > 0:
                await asyncio.sleep(delay)

        return results
