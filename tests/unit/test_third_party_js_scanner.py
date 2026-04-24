"""Unit tests for the third-party JavaScript scanner service."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from src.services.third_party_js_scanner import (
    ThirdPartyJsScanResult,
    ThirdPartyJsScanner,
    ThirdPartyScript,
    _extract_third_party_scripts,
    _extract_version,
    _identify_script,
    _is_third_party,
)


# ---------------------------------------------------------------------------
# _is_third_party helpers
# ---------------------------------------------------------------------------


def test_is_third_party_absolute_different_host():
    """Script from a different host is third-party."""
    assert _is_third_party(
        "https://www.googletagmanager.com/gtm.js?id=GTM-XXXX",
        "example.gov",
    )


def test_is_third_party_same_host():
    """Script from the same host is NOT third-party."""
    assert not _is_third_party(
        "https://example.gov/js/app.js",
        "example.gov",
    )


def test_is_third_party_www_prefix_same_origin():
    """www. prefix is stripped when comparing origins."""
    assert not _is_third_party(
        "https://www.example.gov/js/app.js",
        "example.gov",
    )


def test_is_third_party_relative_url():
    """Relative URLs are always same-origin."""
    assert not _is_third_party("/js/app.js", "example.gov")


def test_is_third_party_protocol_relative():
    """Protocol-relative URLs pointing elsewhere are third-party."""
    # After normalisation //cdn.example.com/... becomes https://cdn.example.com/...
    assert _is_third_party("//cdn.example.com/lib.js", "gov.example")


def test_is_third_party_empty_src():
    """Empty src is treated as same-origin (not third-party)."""
    assert not _is_third_party("", "example.gov")


def test_is_third_party_data_uri():
    """data: URIs are not third-party."""
    assert not _is_third_party("data:text/javascript,alert(1)", "example.gov")


# ---------------------------------------------------------------------------
# _identify_script
# ---------------------------------------------------------------------------


def test_identify_google_tag_manager():
    """GTM script is identified correctly."""
    sig = _identify_script("https://www.googletagmanager.com/gtm.js?id=GTM-XXXX")
    assert sig is not None
    assert "Tag Manager" in sig.categories


def test_identify_google_analytics_ga4():
    """GA4 gtag script is identified correctly."""
    sig = _identify_script("https://www.googletagmanager.com/gtag/js?id=G-ABC123")
    assert sig is not None
    assert "Analytics" in sig.categories


def test_identify_facebook_pixel():
    """Facebook Pixel script is identified correctly."""
    sig = _identify_script("https://connect.facebook.net/en_US/fbevents.js")
    assert sig is not None
    assert sig.service_name == "Facebook Pixel"


def test_identify_jquery_cdn():
    """jQuery from code.jquery.com is identified correctly."""
    sig = _identify_script("https://code.jquery.com/jquery-3.6.0.min.js")
    assert sig is not None
    assert sig.service_name == "jQuery"


def test_identify_hotjar():
    """Hotjar script is identified correctly."""
    sig = _identify_script("https://static.hotjar.com/c/hotjar-12345.js")
    assert sig is not None
    assert sig.service_name == "Hotjar"


def test_identify_unknown_host_returns_none():
    """Unknown CDN host returns None."""
    sig = _identify_script("https://unknown-cdn.example.com/lib.js")
    assert sig is None


def test_identify_cookiebot():
    sig = _identify_script("https://consent.cookiebot.com/uc.js")
    assert sig is not None
    assert sig.service_name == "Cookiebot"


def test_identify_onetrust():
    sig = _identify_script("https://cdn.cookielaw.org/scripttemplates/otSDKStub.js")
    assert sig is not None
    assert sig.service_name == "OneTrust"


def test_identify_microsoft_clarity():
    sig = _identify_script("https://www.clarity.ms/tag/abc123")
    assert sig is not None
    assert sig.service_name == "Microsoft Clarity"


# ---------------------------------------------------------------------------
# _extract_version
# ---------------------------------------------------------------------------


def test_extract_version_jquery():
    """jQuery version extracted from filename."""
    from src.services.third_party_js_scanner import _SIGNATURES
    sig = _SIGNATURES["code.jquery.com"][0]
    version = _extract_version("https://code.jquery.com/jquery-3.6.0.min.js", sig)
    assert version == "3.6.0"


def test_extract_version_bootstrap_path():
    """Bootstrap version extracted from path segment."""
    from src.services.third_party_js_scanner import _SIGNATURES
    sig = _SIGNATURES["stackpath.bootstrapcdn.com"][0]
    version = _extract_version(
        "https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/js/bootstrap.min.js",
        sig,
    )
    assert version == "4.5.2"


def test_extract_version_generic_semver():
    """Generic semver pattern picks up version from URL."""
    version = _extract_version("https://cdn.example.com/lib-2.3.4.min.js", None)
    assert version == "2.3.4"


def test_extract_version_query_param():
    """Version in query parameter is detected by generic pattern."""
    version = _extract_version("https://cdn.example.com/lib.js?v=1.2.3", None)
    assert version == "1.2.3"


def test_extract_version_no_version_returns_none():
    """Returns None when no version can be extracted."""
    version = _extract_version("https://example.com/analytics.js", None)
    assert version is None


def test_extract_version_jsdelivr():
    from src.services.third_party_js_scanner import _SIGNATURES
    sig = _SIGNATURES["cdn.jsdelivr.net"][0]
    version = _extract_version(
        "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js",
        sig,
    )
    assert version == "5.3.0"


# ---------------------------------------------------------------------------
# _extract_third_party_scripts
# ---------------------------------------------------------------------------


def test_extract_detects_google_analytics():
    """Google Analytics GA4 script is detected."""
    html = """
    <html><head>
      <script async src="https://www.googletagmanager.com/gtag/js?id=G-XXXXXXX"></script>
    </head><body></body></html>
    """
    scripts = _extract_third_party_scripts(html, "https://example.gov/")
    assert len(scripts) == 1
    s = scripts[0]
    assert s.service_name == "Google Analytics (GA4)"
    assert "Analytics" in s.categories


def test_extract_detects_google_tag_manager():
    """Google Tag Manager script is detected."""
    html = """
    <html><head>
      <script src="https://www.googletagmanager.com/gtm.js?id=GTM-XXXX"></script>
    </head></html>
    """
    scripts = _extract_third_party_scripts(html, "https://gov.example/")
    assert any(s.service_name == "Google Tag Manager" for s in scripts)


def test_extract_detects_facebook_pixel():
    """Facebook Pixel script is detected."""
    html = """
    <html><head>
      <script src="https://connect.facebook.net/en_US/fbevents.js"></script>
    </head></html>
    """
    scripts = _extract_third_party_scripts(html, "https://agency.gov/")
    assert any(s.service_name == "Facebook Pixel" for s in scripts)


def test_extract_skips_local_scripts():
    """Scripts from the same origin are not included."""
    html = """
    <html><head>
      <script src="/js/main.js"></script>
      <script src="https://example.gov/js/app.js"></script>
    </head></html>
    """
    scripts = _extract_third_party_scripts(html, "https://example.gov/")
    assert len(scripts) == 0


def test_extract_deduplicates_same_src():
    """Duplicate script src values are only listed once."""
    html = """
    <html><head>
      <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
      <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    </head></html>
    """
    scripts = _extract_third_party_scripts(html, "https://example.gov/")
    assert len(scripts) == 1


def test_extract_multiple_third_party_scripts():
    """Multiple distinct third-party scripts are all detected."""
    html = """
    <html><head>
      <script src="https://www.googletagmanager.com/gtm.js?id=GTM-XXXX"></script>
      <script src="https://connect.facebook.net/en_US/fbevents.js"></script>
      <script src="https://static.hotjar.com/c/hotjar-99999.js"></script>
    </head></html>
    """
    scripts = _extract_third_party_scripts(html, "https://gov.example/")
    assert len(scripts) == 3
    service_names = {s.service_name for s in scripts}
    assert "Facebook Pixel" in service_names
    assert "Hotjar" in service_names


def test_extract_protocol_relative_url():
    """Protocol-relative script src is handled correctly."""
    html = """
    <html><head>
      <script src="//code.jquery.com/jquery-3.6.0.min.js"></script>
    </head></html>
    """
    scripts = _extract_third_party_scripts(html, "https://example.gov/")
    assert len(scripts) == 1
    assert scripts[0].service_name == "jQuery"
    assert scripts[0].version == "3.6.0"


def test_extract_extracts_host():
    """The host field is populated from the script src."""
    html = """
    <html><head>
      <script src="https://static.hotjar.com/c/hotjar-12345.js"></script>
    </head></html>
    """
    scripts = _extract_third_party_scripts(html, "https://example.gov/")
    assert len(scripts) == 1
    assert scripts[0].host == "static.hotjar.com"


def test_extract_no_scripts():
    """Pages without any scripts return an empty list."""
    html = "<html><body><p>No scripts here.</p></body></html>"
    scripts = _extract_third_party_scripts(html, "https://example.gov/")
    assert scripts == []


def test_extract_version_populated_for_known_service():
    """Version is extracted for scripts with a known pattern."""
    html = """
    <html><head>
      <script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
    </head></html>
    """
    scripts = _extract_third_party_scripts(html, "https://example.gov/")
    assert len(scripts) == 1
    assert scripts[0].version == "3.7.1"


def test_extract_unknown_third_party_no_service_name():
    """An unknown CDN host is still detected but has no service_name."""
    html = """
    <html><head>
      <script src="https://cdn.unknown-service.example/lib-2.0.0.js"></script>
    </head></html>
    """
    scripts = _extract_third_party_scripts(html, "https://example.gov/")
    assert len(scripts) == 1
    assert scripts[0].service_name is None
    assert scripts[0].version == "2.0.0"


# ---------------------------------------------------------------------------
# ThirdPartyJsScanner.scan_url
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_url_success_no_third_party():
    """Page with no external scripts returns empty script list."""
    scanner = ThirdPartyJsScanner(timeout_seconds=10)

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.url = "https://example.gov/"
    mock_response.text = "<html><body><script src='/js/app.js'></script></body></html>"

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=mock_response
        )
        result = await scanner.scan_url("https://example.gov/")

    assert result.url == "https://example.gov/"
    assert result.is_reachable is True
    assert result.scripts == []
    assert result.error_message is None
    assert result.scanned_at is not None


@pytest.mark.asyncio
async def test_scan_url_success_with_gtm():
    """Page with Google Tag Manager script is detected."""
    scanner = ThirdPartyJsScanner(timeout_seconds=10)

    html = (
        '<html><head>'
        '<script src="https://www.googletagmanager.com/gtm.js?id=GTM-XXXX"></script>'
        '</head></html>'
    )

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.url = "https://gov.example/"
    mock_response.text = html

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=mock_response
        )
        result = await scanner.scan_url("https://gov.example/")

    assert result.is_reachable is True
    assert result.third_party_count == 1
    assert result.scripts[0].service_name == "Google Tag Manager"


@pytest.mark.asyncio
async def test_scan_url_timeout():
    """Timeout results in unreachable result."""
    scanner = ThirdPartyJsScanner(timeout_seconds=1)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=httpx.TimeoutException("Timeout")
        )
        result = await scanner.scan_url("https://slow.gov/")

    assert result.is_reachable is False
    assert result.scripts == []
    assert "Timeout" in result.error_message


@pytest.mark.asyncio
async def test_scan_url_connection_error():
    """Connection error results in unreachable result."""
    scanner = ThirdPartyJsScanner(timeout_seconds=10)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=httpx.ConnectError("refused")
        )
        result = await scanner.scan_url("https://gone.gov/")

    assert result.is_reachable is False
    assert "Connection error" in result.error_message


@pytest.mark.asyncio
async def test_scan_url_too_many_redirects():
    """Too many redirects results in unreachable result."""
    scanner = ThirdPartyJsScanner(timeout_seconds=10)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=httpx.TooManyRedirects("loop", request=Mock())
        )
        result = await scanner.scan_url("https://redirect-loop.gov/")

    assert result.is_reachable is False
    assert "Too many redirects" in result.error_message


# ---------------------------------------------------------------------------
# ThirdPartyJsScanner.scan_urls_batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_urls_batch_returns_all_results():
    """Batch scanning returns results for all URLs."""
    scanner = ThirdPartyJsScanner(timeout_seconds=10)

    urls = [
        "https://gov1.example/",
        "https://gov2.example/",
    ]

    html_with_gtm = (
        '<html><head>'
        '<script src="https://www.googletagmanager.com/gtm.js?id=GTM-XXXX"></script>'
        '</head></html>'
    )
    html_clean = "<html><body><p>No scripts</p></body></html>"

    html_by_url = {urls[0]: html_with_gtm, urls[1]: html_clean}

    async def mock_get(url, **kwargs):
        r = Mock()
        r.status_code = 200
        r.url = url
        r.text = html_by_url[url]
        return r

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=mock_get
        )
        results = await scanner.scan_urls_batch(urls, rate_limit_per_second=0)

    assert len(results) == 2
    assert results[urls[0]].third_party_count == 1
    assert results[urls[1]].third_party_count == 0


@pytest.mark.asyncio
async def test_scan_urls_batch_on_result_called_for_each_url():
    """on_result callback is invoked once per scanned URL."""
    scanner = ThirdPartyJsScanner(timeout_seconds=10)
    urls = ["https://gov1.example/", "https://gov2.example/"]

    saved: list[ThirdPartyJsScanResult] = []

    async def mock_get(url, **kwargs):
        r = Mock()
        r.status_code = 200
        r.url = url
        r.text = "<html><body></body></html>"
        return r

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=mock_get
        )
        results = await scanner.scan_urls_batch(
            urls, rate_limit_per_second=0, on_result=saved.append
        )

    assert len(saved) == 2
    assert saved[0].url == urls[0]
    assert saved[1].url == urls[1]
    assert saved[0] is results[urls[0]]
    assert saved[1] is results[urls[1]]


@pytest.mark.asyncio
async def test_scan_urls_batch_no_callback_still_works():
    """Omitting on_result does not break anything."""
    scanner = ThirdPartyJsScanner(timeout_seconds=10)
    urls = ["https://gov1.example/"]

    async def mock_get(url, **kwargs):
        r = Mock()
        r.status_code = 200
        r.url = url
        r.text = "<html><body></body></html>"
        return r

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=mock_get
        )
        results = await scanner.scan_urls_batch(urls, rate_limit_per_second=0)

    assert len(results) == 1


@pytest.mark.asyncio
async def test_scan_urls_batch_stops_early_when_budget_exhausted():
    """
    When start_time is in the distant past the budget is already exhausted
    and no URLs should be scanned.
    """
    scanner = ThirdPartyJsScanner(timeout_seconds=10)
    urls = ["https://gov1.example/", "https://gov2.example/", "https://gov3.example/"]

    async def mock_get(url, **kwargs):
        r = Mock()
        r.status_code = 200
        r.url = url
        r.text = "<html><body></body></html>"
        return r

    past_start = time.monotonic() - 3600

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=mock_get
        )
        results = await scanner.scan_urls_batch(
            urls,
            rate_limit_per_second=0,
            max_runtime_seconds=1.0,
            start_time=past_start,
        )

    assert len(results) == 0


@pytest.mark.asyncio
async def test_scan_urls_batch_no_max_runtime_scans_all():
    """When max_runtime_seconds is None all URLs are scanned."""
    scanner = ThirdPartyJsScanner(timeout_seconds=10)
    urls = ["https://gov1.example/", "https://gov2.example/"]

    async def mock_get(url, **kwargs):
        r = Mock()
        r.status_code = 200
        r.url = url
        r.text = "<html><body></body></html>"
        return r

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=mock_get
        )
        results = await scanner.scan_urls_batch(
            urls,
            rate_limit_per_second=0,
            max_runtime_seconds=None,
        )

    assert len(results) == 2


# ---------------------------------------------------------------------------
# ThirdPartyJsScanResult properties
# ---------------------------------------------------------------------------


def test_result_third_party_count():
    scripts = [
        ThirdPartyScript(src="https://a.com/a.js", host="a.com"),
        ThirdPartyScript(src="https://b.com/b.js", host="b.com"),
    ]
    result = ThirdPartyJsScanResult(url="https://x.gov/", is_reachable=True, scripts=scripts)
    assert result.third_party_count == 2


def test_result_known_service_count():
    scripts = [
        ThirdPartyScript(
            src="https://a.com/a.js",
            host="a.com",
            service_name="Service A",
        ),
        ThirdPartyScript(src="https://b.com/b.js", host="b.com"),
    ]
    result = ThirdPartyJsScanResult(url="https://x.gov/", is_reachable=True, scripts=scripts)
    assert result.known_service_count == 1
