"""Social media link scanner for government websites.

Fetches a page and detects links to Twitter/X, Bluesky, Mastodon,
Facebook, and LinkedIn.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Known Mastodon / Fediverse instance hostnames.
# This list covers many large instances; detection also covers rel="me" links
# and the /@user pattern on any domain.
# ---------------------------------------------------------------------------
KNOWN_MASTODON_HOSTS: frozenset[str] = frozenset(
    {
        "mastodon.social",
        "mastodon.online",
        "fosstodon.org",
        "social.coop",
        "hachyderm.io",
        "mstdn.social",
        "infosec.exchange",
        "chaos.social",
        "mastodon.world",
        "aus.social",
        "social.saarland",
        "social.vivaldi.net",
        "mastodon.green",
        "eupolicy.social",
        "social.bund.de",
        "social.numerique.gouv.fr",
        "social.techno.app",
        "mastodon.nz",
        "mastodon.ie",
        "mastodon.scot",
        "mastodon.me.uk",
        "mastodon.com.br",
        "mastodon.lol",
        "mastodon.uno",
        "mastodon.cloud",
        "social.linux.pizza",
        "toot.cafe",
        "masto.ai",
        "tabletop.social",
        "sigmoid.social",
        "urbanists.social",
        "disabled.social",
        "newsie.social",
        "kolektiva.social",
        "tech.lgbt",
        "scholar.social",
        "scicomm.xyz",
        "hcommons.social",
        "pkm.social",
        "home.social",
        "indieweb.social",
    }
)

# Hostnames that belong to Twitter/X
TWITTER_HOSTS: frozenset[str] = frozenset({"twitter.com", "www.twitter.com"})
X_HOSTS: frozenset[str] = frozenset({"x.com", "www.x.com"})

# Hostnames that belong to Bluesky
BLUESKY_HOSTS: frozenset[str] = frozenset(
    {"bsky.app", "www.bsky.app", "bsky.social", "www.bsky.social"}
)

# Hostnames that belong to Facebook (legacy platform)
FACEBOOK_HOSTS: frozenset[str] = frozenset(
    {"facebook.com", "www.facebook.com", "fb.com", "www.fb.com"}
)

# Hostnames that belong to LinkedIn (legacy platform)
LINKEDIN_HOSTS: frozenset[str] = frozenset({"linkedin.com", "www.linkedin.com"})

# Version number that identifies which set of social-media platforms this
# scanner detects.  Increment this constant whenever a new platform is added
# so that previously-scanned URLs are re-scanned to collect the new data.
#   1 – Twitter, X, Bluesky, Mastodon
#   2 – Twitter, X, Bluesky, Mastodon, Facebook, LinkedIn  (current)
SOCIAL_PLATFORMS_VERSION: int = 2

# Regex for detecting @user@domain patterns in page text (Mastodon handles)
_MASTODON_HANDLE_RE = re.compile(r"@[\w.-]+@([\w.-]+\.\w{2,})")


@dataclass(slots=True)
class SocialMediaScanResult:
    """Result of a social media link scan for a single URL."""

    url: str
    is_reachable: bool
    twitter_links: List[str] = field(default_factory=list)
    x_links: List[str] = field(default_factory=list)
    bluesky_links: List[str] = field(default_factory=list)
    mastodon_links: List[str] = field(default_factory=list)
    facebook_links: List[str] = field(default_factory=list)
    linkedin_links: List[str] = field(default_factory=list)
    # Tier classification:
    #   "unreachable"   – page could not be fetched
    #   "no_social"     – reachable, no social media links found
    #   "twitter_only"  – only legacy social media (Twitter, X, Facebook, LinkedIn)
    #   "modern_only"   – only Bluesky / Mastodon links
    #   "mixed"         – legacy plus at least one modern platform
    social_tier: str = "no_social"
    error_message: str | None = None
    scanned_at: str | None = None


def _classify_tier(result: SocialMediaScanResult) -> str:
    """Return the social media tier string for a scan result."""
    if not result.is_reachable:
        return "unreachable"

    has_legacy = bool(
        result.twitter_links or result.x_links
        or result.facebook_links or result.linkedin_links
    )
    has_modern = bool(result.bluesky_links or result.mastodon_links)

    if has_legacy and has_modern:
        return "mixed"
    if has_legacy:
        return "twitter_only"
    if has_modern:
        return "modern_only"
    return "no_social"


def _extract_social_links(html: str, base_url: str) -> dict:
    """
    Parse HTML and extract links to Twitter/X, Bluesky, Mastodon,
    Facebook, and LinkedIn.

    Returns a dict with keys: twitter, x, bluesky, mastodon, facebook,
    linkedin — each a list of href strings found in <a> elements.
    """
    soup = BeautifulSoup(html, "html.parser")

    twitter: list[str] = []
    x_links: list[str] = []
    bluesky: list[str] = []
    mastodon: list[str] = []
    facebook: list[str] = []
    linkedin: list[str] = []

    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        try:
            parsed = urlparse(href)
        except ValueError:
            continue

        netloc = parsed.netloc.lower()

        if netloc in TWITTER_HOSTS:
            twitter.append(href)
        elif netloc in X_HOSTS:
            x_links.append(href)
        elif netloc in BLUESKY_HOSTS:
            bluesky.append(href)
        elif netloc in KNOWN_MASTODON_HOSTS:
            mastodon.append(href)
        elif netloc in FACEBOOK_HOSTS:
            facebook.append(href)
        elif netloc in LINKEDIN_HOSTS:
            linkedin.append(href)
        elif netloc and _looks_like_mastodon_profile(href, parsed):
            mastodon.append(href)

    # Also detect @user@domain handles in plain text
    for match in _MASTODON_HANDLE_RE.finditer(soup.get_text()):
        instance = match.group(1).lower()
        if instance not in TWITTER_HOSTS and instance not in BLUESKY_HOSTS:
            mastodon.append(match.group(0))

    return {
        "twitter": _deduplicate(twitter),
        "x": _deduplicate(x_links),
        "bluesky": _deduplicate(bluesky),
        "mastodon": _deduplicate(mastodon),
        "facebook": _deduplicate(facebook),
        "linkedin": _deduplicate(linkedin),
    }


def _looks_like_mastodon_profile(href: str, parsed) -> bool:
    """
    Heuristic: a link looks like a Mastodon profile URL when its path starts
    with ``/@`` (e.g. ``https://example.social/@alice``).
    """
    return bool(parsed.scheme in {"http", "https"} and parsed.path.startswith("/@"))


def _deduplicate(items: list[str]) -> list[str]:
    """Return items with duplicates removed, preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


class SocialMediaScanner:
    """
    Service for scanning government website pages for social media links.

    Fetches each URL with httpx, parses the HTML with BeautifulSoup, and
    identifies links to Twitter/X, Bluesky, and Mastodon.  Also records
    whether the page was reachable at all, which helps track defunct domains.
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
    ) -> "SocialMediaScanResult":
        """
        Analyse pre-fetched HTML for social media links.

        Use this when the page content has already been retrieved (e.g. by a
        multi-scanner that shares a single HTTP request across several analyses).

        Args:
            url: The URL the HTML was fetched from.
            html: Raw HTML of the page.
            scanned_at: ISO-8601 timestamp string.  Defaults to *now* in UTC.

        Returns:
            :class:`SocialMediaScanResult` with ``is_reachable=True``.
        """
        if scanned_at is None:
            scanned_at = datetime.now(timezone.utc).isoformat()

        try:
            links = _extract_social_links(html, url)
        except Exception as exc:  # noqa: BLE001
            result = SocialMediaScanResult(
                url=url,
                is_reachable=True,
                error_message=f"Parse error: {exc}",
                scanned_at=scanned_at,
            )
            result.social_tier = _classify_tier(result)
            return result

        result = SocialMediaScanResult(
            url=url,
            is_reachable=True,
            twitter_links=links["twitter"],
            x_links=links["x"],
            bluesky_links=links["bluesky"],
            mastodon_links=links["mastodon"],
            facebook_links=links["facebook"],
            linkedin_links=links["linkedin"],
            scanned_at=scanned_at,
        )
        result.social_tier = _classify_tier(result)
        return result

    async def scan_url(self, url: str) -> SocialMediaScanResult:
        """
        Scan a single URL for social media links.

        Returns:
            SocialMediaScanResult with detected links and tier classification.
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
            result = SocialMediaScanResult(
                url=url,
                is_reachable=False,
                error_message=f"Too many redirects: {exc}",
                scanned_at=scanned_at,
            )
            result.social_tier = _classify_tier(result)
            return result
        except httpx.TimeoutException as exc:
            result = SocialMediaScanResult(
                url=url,
                is_reachable=False,
                error_message=f"Timeout: {exc}",
                scanned_at=scanned_at,
            )
            result.social_tier = _classify_tier(result)
            return result
        except httpx.ConnectError as exc:
            result = SocialMediaScanResult(
                url=url,
                is_reachable=False,
                error_message=f"Connection error: {exc}",
                scanned_at=scanned_at,
            )
            result.social_tier = _classify_tier(result)
            return result
        except httpx.HTTPError as exc:
            result = SocialMediaScanResult(
                url=url,
                is_reachable=False,
                error_message=f"HTTP error: {exc}",
                scanned_at=scanned_at,
            )
            result.social_tier = _classify_tier(result)
            return result
        except Exception as exc:  # noqa: BLE001
            result = SocialMediaScanResult(
                url=url,
                is_reachable=False,
                error_message=f"Unexpected error: {exc}",
                scanned_at=scanned_at,
            )
            result.social_tier = _classify_tier(result)
            return result

        return self.scan_html(url, html, scanned_at=scanned_at)

    async def scan_urls_batch(
        self,
        urls: List[str],
        rate_limit_per_second: float = 2.0,
        max_runtime_seconds: Optional[float] = None,
        start_time: Optional[float] = None,
        on_result: Optional[Callable[["SocialMediaScanResult"], None]] = None,
    ) -> Dict[str, SocialMediaScanResult]:
        """
        Scan multiple URLs for social media links with rate limiting.

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
            Dictionary mapping URL to SocialMediaScanResult.  When stopped
            early the dict contains only the URLs that were actually scanned.
        """
        results: Dict[str, SocialMediaScanResult] = {}
        # rate_limit_per_second <= 0 disables inter-request delay entirely;
        # this is intentional for unit tests and should not be used in production.
        delay = 1.0 / rate_limit_per_second if rate_limit_per_second > 0 else 0
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
            result = await self.scan_url(url)
            results[url] = result

            if on_result is not None:
                on_result(result)

            if result.error_message:
                print(f"      ✗ {result.error_message}")
            else:
                platforms = []
                if result.twitter_links:
                    platforms.append(f"Twitter×{len(result.twitter_links)}")
                if result.x_links:
                    platforms.append(f"X×{len(result.x_links)}")
                if result.facebook_links:
                    platforms.append(f"Facebook×{len(result.facebook_links)}")
                if result.linkedin_links:
                    platforms.append(f"LinkedIn×{len(result.linkedin_links)}")
                if result.bluesky_links:
                    platforms.append(f"Bluesky×{len(result.bluesky_links)}")
                if result.mastodon_links:
                    platforms.append(f"Mastodon×{len(result.mastodon_links)}")
                summary = ", ".join(platforms) or "(no social media links)"
                print(f"      ✓ [{result.social_tier}] {summary}")

            if delay > 0:
                await asyncio.sleep(delay)

        return results
