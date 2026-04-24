"""Third-party JavaScript scanner for government websites.

Fetches a page and detects external JavaScript resources, identifies known
third-party services (e.g. Google Analytics, Tag Manager, Facebook Pixel),
and extracts version numbers where possible.

Version numbers are security-relevant: outdated libraries may carry known CVEs,
and tracking which third-party services governments use helps accountability.
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
# Known third-party service fingerprints.
# Each entry maps a (hostname, optional path-prefix) pair to metadata that
# describes the service name, category and a regex to extract the version
# from the script URL.
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _ServiceSignature:
    """Internal descriptor for a known third-party JS service."""
    service_name: str
    categories: List[str]
    # Optional regex applied to the full script URL; first capture group = version
    version_pattern: Optional[re.Pattern] = None


# Signatures keyed by hostname.  A list is used so multiple services can
# share a hostname (e.g. googleapis.com hosts jQuery CDN and others).
_SIGNATURES: Dict[str, List[_ServiceSignature]] = {
    # Google
    "www.googletagmanager.com": [
        _ServiceSignature(
            service_name="Google Tag Manager",
            categories=["Tag Manager"],
            version_pattern=re.compile(r"gtm\.js\?id=([A-Z0-9-]+)", re.I),
        ),
        _ServiceSignature(
            service_name="Google Analytics (GA4)",
            categories=["Analytics"],
            version_pattern=re.compile(r"gtag/js\?id=(G-[A-Z0-9]+)", re.I),
        ),
    ],
    "www.google-analytics.com": [
        _ServiceSignature(
            service_name="Google Analytics (Universal)",
            categories=["Analytics"],
        ),
    ],
    "ssl.google-analytics.com": [
        _ServiceSignature(
            service_name="Google Analytics (Universal)",
            categories=["Analytics"],
        ),
    ],
    # Google CDN — jQuery and other libs
    "ajax.googleapis.com": [
        _ServiceSignature(
            service_name="Google Hosted Libraries",
            categories=["CDN", "JavaScript Library"],
            version_pattern=re.compile(r"/ajax/libs/[\w.-]+/([\d.]+)/", re.I),
        ),
    ],
    # Facebook / Meta
    "connect.facebook.net": [
        _ServiceSignature(
            service_name="Facebook Pixel",
            categories=["Analytics", "Advertising"],
        ),
    ],
    # jQuery CDN
    "code.jquery.com": [
        _ServiceSignature(
            service_name="jQuery",
            categories=["JavaScript Library"],
            version_pattern=re.compile(r"jquery[.-]((?:\d+\.)*\d+)", re.I),
        ),
    ],
    # Bootstrap CDN variants
    "stackpath.bootstrapcdn.com": [
        _ServiceSignature(
            service_name="Bootstrap",
            categories=["UI Framework"],
            version_pattern=re.compile(r"bootstrap/([\d.]+)/", re.I),
        ),
    ],
    "maxcdn.bootstrapcdn.com": [
        _ServiceSignature(
            service_name="Bootstrap",
            categories=["UI Framework"],
            version_pattern=re.compile(r"bootstrap/([\d.]+)/", re.I),
        ),
    ],
    "cdn.jsdelivr.net": [
        _ServiceSignature(
            service_name="jsDelivr CDN",
            categories=["CDN"],
            version_pattern=re.compile(r"@([\d.]+)/", re.I),
        ),
    ],
    "cdnjs.cloudflare.com": [
        _ServiceSignature(
            service_name="cdnjs (Cloudflare CDN)",
            categories=["CDN"],
            version_pattern=re.compile(r"/ajax/libs/[\w.-]+/([\d.]+)/", re.I),
        ),
    ],
    "unpkg.com": [
        _ServiceSignature(
            service_name="unpkg CDN",
            categories=["CDN"],
            version_pattern=re.compile(r"@([\d.]+)/", re.I),
        ),
    ],
    # Hotjar
    "static.hotjar.com": [
        _ServiceSignature(
            service_name="Hotjar",
            categories=["Analytics", "Heatmaps"],
            version_pattern=re.compile(r"hotjar-([\d]+)", re.I),
        ),
    ],
    # Cookiebot
    "consent.cookiebot.com": [
        _ServiceSignature(
            service_name="Cookiebot",
            categories=["Cookie Consent"],
        ),
    ],
    # OneTrust
    "cdn.cookielaw.org": [
        _ServiceSignature(
            service_name="OneTrust",
            categories=["Cookie Consent"],
        ),
    ],
    "optanon.blob.core.windows.net": [
        _ServiceSignature(
            service_name="OneTrust",
            categories=["Cookie Consent"],
        ),
    ],
    # Sentry
    "browser.sentry-cdn.com": [
        _ServiceSignature(
            service_name="Sentry",
            categories=["Error Tracking"],
            version_pattern=re.compile(r"/([\d.]+)/bundle", re.I),
        ),
    ],
    "js.sentry-cdn.com": [
        _ServiceSignature(
            service_name="Sentry",
            categories=["Error Tracking"],
            version_pattern=re.compile(r"/([\d.]+)/bundle", re.I),
        ),
    ],
    # Cloudflare
    "challenges.cloudflare.com": [
        _ServiceSignature(
            service_name="Cloudflare Turnstile / Challenge",
            categories=["Security"],
        ),
    ],
    "static.cloudflareinsights.com": [
        _ServiceSignature(
            service_name="Cloudflare Web Analytics",
            categories=["Analytics"],
        ),
    ],
    # Recaptcha / Google
    "www.google.com": [
        _ServiceSignature(
            service_name="Google reCAPTCHA",
            categories=["Security", "CAPTCHA"],
        ),
    ],
    "www.recaptcha.net": [
        _ServiceSignature(
            service_name="Google reCAPTCHA",
            categories=["Security", "CAPTCHA"],
        ),
    ],
    # Font Awesome
    "kit.fontawesome.com": [
        _ServiceSignature(
            service_name="Font Awesome",
            categories=["Icon Library"],
        ),
    ],
    "use.fontawesome.com": [
        _ServiceSignature(
            service_name="Font Awesome",
            categories=["Icon Library"],
            version_pattern=re.compile(r"/([\d.]+)/", re.I),
        ),
    ],
    # Stripe
    "js.stripe.com": [
        _ServiceSignature(
            service_name="Stripe",
            categories=["Payments"],
            version_pattern=re.compile(r"/v([\d]+)", re.I),
        ),
    ],
    # Intercom
    "widget.intercom.io": [
        _ServiceSignature(
            service_name="Intercom",
            categories=["Customer Support", "Chat"],
        ),
    ],
    "js.intercomcdn.com": [
        _ServiceSignature(
            service_name="Intercom",
            categories=["Customer Support", "Chat"],
        ),
    ],
    # HubSpot
    "js.hs-scripts.com": [
        _ServiceSignature(
            service_name="HubSpot",
            categories=["CRM", "Marketing"],
        ),
    ],
    "js.hsadspixel.net": [
        _ServiceSignature(
            service_name="HubSpot Ads Pixel",
            categories=["Analytics", "Advertising"],
        ),
    ],
    # Zendesk
    "static.zdassets.com": [
        _ServiceSignature(
            service_name="Zendesk",
            categories=["Customer Support", "Chat"],
        ),
    ],
    # Crisp
    "client.crisp.chat": [
        _ServiceSignature(
            service_name="Crisp",
            categories=["Customer Support", "Chat"],
        ),
    ],
    # Matomo / Piwik (cloud)
    "cdn.matomo.cloud": [
        _ServiceSignature(
            service_name="Matomo Cloud",
            categories=["Analytics"],
        ),
    ],
    # New Relic
    "js-agent.newrelic.com": [
        _ServiceSignature(
            service_name="New Relic",
            categories=["Performance Monitoring"],
            version_pattern=re.compile(r"nr-((?:\d+\.)*\d+)", re.I),
        ),
    ],
    # Dynatrace
    "js.dynatrace.com": [
        _ServiceSignature(
            service_name="Dynatrace",
            categories=["Performance Monitoring"],
        ),
    ],
    # Cookieinformation (used in Nordic countries)
    "policy.app.cookieinformation.com": [
        _ServiceSignature(
            service_name="CookieInformation",
            categories=["Cookie Consent"],
        ),
    ],
    # Adobe Analytics / Launch
    "assets.adobedtm.com": [
        _ServiceSignature(
            service_name="Adobe Dynamic Tag Management / Launch",
            categories=["Tag Manager", "Analytics"],
        ),
    ],
    # LinkedIn Insight
    "snap.licdn.com": [
        _ServiceSignature(
            service_name="LinkedIn Insight Tag",
            categories=["Analytics", "Advertising"],
        ),
    ],
    # Twitter / X pixel
    "static.ads-twitter.com": [
        _ServiceSignature(
            service_name="Twitter/X Pixel",
            categories=["Analytics", "Advertising"],
        ),
    ],
    # Microsoft Clarity
    "www.clarity.ms": [
        _ServiceSignature(
            service_name="Microsoft Clarity",
            categories=["Analytics", "Heatmaps"],
        ),
    ],
    # Usercentrics (consent)
    "app.usercentrics.eu": [
        _ServiceSignature(
            service_name="Usercentrics",
            categories=["Cookie Consent"],
        ),
    ],
    # Piwik PRO
    "cdn.piwik.pro": [
        _ServiceSignature(
            service_name="Piwik PRO",
            categories=["Analytics", "Tag Manager"],
        ),
    ],
}

# Generic version extractor: matches common patterns in script src URLs.
# Applied as a fallback when no service-specific pattern matched.
# Handles:
#   - Query params: ?v=1.2.3 or &version=1.2.3
#   - Path segments: /v1.2.3/ or -3.6.0.min.js or lib-2.0.0.js
# Uses ((?:\d+\.)*\d+) to avoid capturing trailing dots.
# The (?!\d) lookahead ensures we do not extend a matched version into a
# following unrelated digit group.
_GENERIC_VERSION_RE = re.compile(
    r"(?:[?&]v(?:ersion)?=|[./_-]v?)((?:\d+\.)*\d+)(?!\d)",
    re.I,
)


def _extract_version(script_src: str, signature: Optional[_ServiceSignature]) -> Optional[str]:
    """
    Try to extract a version string from *script_src*.

    First tries the service-specific pattern (if available), then falls back
    to the generic semver-like pattern.  Returns ``None`` if no version found.
    """
    if signature and signature.version_pattern:
        m = signature.version_pattern.search(script_src)
        if m:
            return m.group(1)

    m = _GENERIC_VERSION_RE.search(script_src)
    if m:
        return m.group(1)

    return None


@dataclass(slots=True)
class ThirdPartyScript:
    """Details of a single third-party script found on a page."""

    src: str
    host: str
    service_name: Optional[str] = None
    version: Optional[str] = None
    categories: List[str] = field(default_factory=list)


@dataclass(slots=True)
class ThirdPartyJsScanResult:
    """Result of a third-party JavaScript scan for a single URL."""

    url: str
    is_reachable: bool
    scripts: List[ThirdPartyScript] = field(default_factory=list)
    error_message: Optional[str] = None
    scanned_at: Optional[str] = None

    @property
    def third_party_count(self) -> int:
        return len(self.scripts)

    @property
    def known_service_count(self) -> int:
        return sum(1 for s in self.scripts if s.service_name)


def _is_third_party(script_src: str, page_host: str) -> bool:
    """
    Return True when *script_src* points to a different host than *page_host*.

    Data URIs, inline scripts, and relative paths are ignored (not 3rd party).
    """
    if not script_src or script_src.startswith("data:"):
        return False

    try:
        parsed = urlparse(script_src)
    except ValueError:
        return False

    if not parsed.netloc:
        # Relative URL → same origin
        return False

    script_host = parsed.netloc.lower().lstrip("www.")
    page_host_clean = page_host.lower().lstrip("www.")

    return script_host != page_host_clean


def _identify_script(script_src: str) -> Optional[_ServiceSignature]:
    """
    Match *script_src* against known service signatures.

    Returns the first matching :class:`_ServiceSignature` or ``None``.
    """
    try:
        parsed = urlparse(script_src)
    except ValueError:
        return None

    host = parsed.netloc.lower()
    signatures = _SIGNATURES.get(host)
    if not signatures:
        return None

    # If a single signature for this host (most common), return it directly.
    if len(signatures) == 1:
        return signatures[0]

    # Multiple signatures on one host — pick by path prefix.
    for sig in signatures:
        if sig.version_pattern and sig.version_pattern.search(script_src):
            return sig

    # No pattern matched → return the first entry (most prominent service).
    return signatures[0]


def _extract_third_party_scripts(html: str, page_url: str) -> List[ThirdPartyScript]:
    """
    Parse *html* and return all third-party ``<script src>`` resources.

    Args:
        html: Raw HTML of the page.
        page_url: The URL the page was fetched from (used to determine origin).

    Returns:
        List of :class:`ThirdPartyScript` instances, deduplicated by ``src``.
    """
    try:
        page_host = urlparse(page_url).netloc
    except ValueError:
        page_host = ""

    soup = BeautifulSoup(html, "html.parser")
    seen_srcs: set[str] = set()
    scripts: List[ThirdPartyScript] = []

    for tag in soup.find_all("script", src=True):
        raw_src = tag.get("src", "").strip()
        if not raw_src or raw_src in seen_srcs:
            continue

        # Normalise protocol-relative URLs
        if raw_src.startswith("//"):
            raw_src = "https:" + raw_src

        if not _is_third_party(raw_src, page_host):
            continue

        seen_srcs.add(raw_src)

        try:
            host = urlparse(raw_src).netloc.lower()
        except ValueError:
            host = ""

        signature = _identify_script(raw_src)
        version = _extract_version(raw_src, signature)

        scripts.append(
            ThirdPartyScript(
                src=raw_src,
                host=host,
                service_name=signature.service_name if signature else None,
                version=version,
                categories=list(signature.categories) if signature else [],
            )
        )

    return scripts


class ThirdPartyJsScanner:
    """
    Service for scanning government website pages for third-party JavaScript.

    Fetches each URL with httpx, parses the HTML with BeautifulSoup, and
    identifies external script resources together with their service name
    (where known) and version number (where detectable).
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
        final_url: str | None = None,
        scanned_at: str | None = None,
    ) -> "ThirdPartyJsScanResult":
        """
        Analyse pre-fetched HTML for third-party JavaScript resources.

        Use this when the page content has already been retrieved (e.g. by a
        multi-scanner that shares a single HTTP request across several analyses).

        Args:
            url: The original URL requested.
            html: Raw HTML of the page.
            final_url: The URL after redirects (used for host comparison when
                detecting third-party scripts).  Defaults to *url*.
            scanned_at: ISO-8601 timestamp string.  Defaults to *now* in UTC.

        Returns:
            :class:`ThirdPartyJsScanResult` with ``is_reachable=True``.
        """
        if scanned_at is None:
            scanned_at = datetime.now(timezone.utc).isoformat()

        try:
            scripts = _extract_third_party_scripts(html, final_url or url)
        except Exception as exc:  # noqa: BLE001
            return ThirdPartyJsScanResult(
                url=url,
                is_reachable=True,
                error_message=f"Parse error: {exc}",
                scanned_at=scanned_at,
            )

        return ThirdPartyJsScanResult(
            url=url,
            is_reachable=True,
            scripts=scripts,
            scanned_at=scanned_at,
        )

    async def scan_url(self, url: str) -> ThirdPartyJsScanResult:
        """
        Scan a single URL for third-party JavaScript resources.

        Returns:
            :class:`ThirdPartyJsScanResult` with detected scripts.
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
                final_url = str(response.url)

        except httpx.TooManyRedirects as exc:
            return ThirdPartyJsScanResult(
                url=url,
                is_reachable=False,
                error_message=f"Too many redirects: {exc}",
                scanned_at=scanned_at,
            )
        except httpx.TimeoutException as exc:
            return ThirdPartyJsScanResult(
                url=url,
                is_reachable=False,
                error_message=f"Timeout: {exc}",
                scanned_at=scanned_at,
            )
        except httpx.ConnectError as exc:
            return ThirdPartyJsScanResult(
                url=url,
                is_reachable=False,
                error_message=f"Connection error: {exc}",
                scanned_at=scanned_at,
            )
        except httpx.HTTPError as exc:
            return ThirdPartyJsScanResult(
                url=url,
                is_reachable=False,
                error_message=f"HTTP error: {exc}",
                scanned_at=scanned_at,
            )
        except Exception as exc:  # noqa: BLE001
            return ThirdPartyJsScanResult(
                url=url,
                is_reachable=False,
                error_message=f"Unexpected error: {exc}",
                scanned_at=scanned_at,
            )

        return self.scan_html(url, html, final_url=final_url, scanned_at=scanned_at)

    async def scan_urls_batch(
        self,
        urls: List[str],
        rate_limit_per_second: float = 2.0,
        max_runtime_seconds: Optional[float] = None,
        start_time: Optional[float] = None,
        on_result: Optional[Callable[["ThirdPartyJsScanResult"], None]] = None,
    ) -> Dict[str, "ThirdPartyJsScanResult"]:
        """
        Scan multiple URLs for third-party JavaScript with rate limiting.

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
            Dictionary mapping URL to :class:`ThirdPartyJsScanResult`.  When
            stopped early the dict contains only the URLs that were scanned.
        """
        results: Dict[str, ThirdPartyJsScanResult] = {}
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
                known = result.known_service_count
                total_scripts = result.third_party_count
                summary = (
                    f"{total_scripts} 3rd-party script(s), "
                    f"{known} identified service(s)"
                )
                print(f"      ✓ {summary}")

            if delay > 0:
                await asyncio.sleep(delay)

        return results
