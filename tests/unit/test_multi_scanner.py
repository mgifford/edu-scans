"""Unit tests for the multi-scanner service."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from src.services.accessibility_scanner import AccessibilityScanResult
from src.services.multi_scanner import MultiScanResult, MultiScanner, _print_result_summary
from src.services.social_media_scanner import SocialMediaScanResult
from src.services.tech_detector import TechDetectionResult
from src.services.third_party_js_scanner import ThirdPartyJsScanResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SIMPLE_HTML = """
<html>
<head><title>Gov Page</title></head>
<body>
  <main><p>Welcome to the government site.</p></main>
  <footer>
    <a href="/accessibility">Accessibility statement</a>
    <a href="https://twitter.com/govuk">Twitter</a>
  </footer>
  <script src="https://www.googletagmanager.com/gtm.js?id=GTM-XXXX"></script>
</body>
</html>
"""

_MOCK_HEADERS = {"content-type": "text/html; charset=utf-8"}


def _make_mock_response(url: str, html: str = _SIMPLE_HTML) -> Mock:
    """Return a minimal mock httpx response."""
    response = Mock()
    response.status_code = 200
    response.url = url
    response.text = html
    response.headers = _MOCK_HEADERS
    return response


# ---------------------------------------------------------------------------
# MultiScanResult dataclass
# ---------------------------------------------------------------------------


def test_multi_scan_result_defaults():
    """MultiScanResult can be constructed with minimal arguments."""
    result = MultiScanResult(url="https://example.gov/", is_reachable=True)
    assert result.url == "https://example.gov/"
    assert result.is_reachable is True
    assert result.final_url is None
    assert result.error_message is None
    assert result.accessibility is None
    assert result.social_media is None
    assert result.tech is None
    assert result.third_party_js is None
    assert result.scanned_at is None


def test_multi_scan_result_unreachable():
    """MultiScanResult with is_reachable=False stores an error message."""
    result = MultiScanResult(
        url="https://gone.gov/",
        is_reachable=False,
        error_message="Connection error: refused",
    )
    assert result.is_reachable is False
    assert "Connection error" in result.error_message


# ---------------------------------------------------------------------------
# MultiScanner.scan_url — successful fetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_url_success_returns_all_sub_results():
    """When the page is reachable all four sub-results are populated."""
    scanner = MultiScanner(timeout_seconds=10)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=_make_mock_response("https://example.gov/")
        )
        result = await scanner.scan_url("https://example.gov/")

    assert result.is_reachable is True
    assert result.final_url == "https://example.gov/"
    assert result.error_message is None
    assert result.scanned_at is not None

    # All sub-results should be populated
    assert result.accessibility is not None
    assert result.social_media is not None
    assert result.tech is not None
    assert result.third_party_js is not None


@pytest.mark.asyncio
async def test_scan_url_detects_accessibility_statement():
    """Accessibility statement link in footer is detected."""
    scanner = MultiScanner(timeout_seconds=10)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=_make_mock_response("https://example.gov/")
        )
        result = await scanner.scan_url("https://example.gov/")

    assert result.accessibility is not None
    assert result.accessibility.has_statement is True


@pytest.mark.asyncio
async def test_scan_url_detects_twitter_links():
    """Social media scanner finds Twitter link in the shared HTML."""
    scanner = MultiScanner(timeout_seconds=10)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=_make_mock_response("https://example.gov/")
        )
        result = await scanner.scan_url("https://example.gov/")

    assert result.social_media is not None
    assert result.social_media.social_tier in {"twitter_only", "mixed"}
    assert "https://twitter.com/govuk" in result.social_media.twitter_links


@pytest.mark.asyncio
async def test_scan_url_detects_third_party_js():
    """Third-party JS scanner finds GTM script in the shared HTML."""
    scanner = MultiScanner(timeout_seconds=10)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=_make_mock_response("https://example.gov/")
        )
        result = await scanner.scan_url("https://example.gov/")

    assert result.third_party_js is not None
    assert result.third_party_js.third_party_count >= 1
    service_names = [s.service_name for s in result.third_party_js.scripts]
    assert any("Tag Manager" in (n or "") for n in service_names)


# ---------------------------------------------------------------------------
# MultiScanner.scan_url — selective scanners
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_url_only_social_media():
    """When only social_media is enabled the other sub-results are None."""
    scanner = MultiScanner(
        timeout_seconds=10,
        run_accessibility=False,
        run_social_media=True,
        run_tech=False,
        run_third_party_js=False,
    )

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=_make_mock_response("https://example.gov/")
        )
        result = await scanner.scan_url("https://example.gov/")

    assert result.is_reachable is True
    assert result.accessibility is None
    assert result.social_media is not None
    assert result.tech is None
    assert result.third_party_js is None


@pytest.mark.asyncio
async def test_scan_url_only_accessibility():
    """When only accessibility is enabled the other sub-results are None."""
    scanner = MultiScanner(
        timeout_seconds=10,
        run_accessibility=True,
        run_social_media=False,
        run_tech=False,
        run_third_party_js=False,
    )

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=_make_mock_response("https://example.gov/")
        )
        result = await scanner.scan_url("https://example.gov/")

    assert result.accessibility is not None
    assert result.social_media is None
    assert result.tech is None
    assert result.third_party_js is None


# ---------------------------------------------------------------------------
# MultiScanner.scan_url — HTTP error cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_url_timeout():
    """Timeout results in is_reachable=False with no sub-results."""
    scanner = MultiScanner(timeout_seconds=1)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=httpx.TimeoutException("Timeout")
        )
        result = await scanner.scan_url("https://slow.gov/")

    assert result.is_reachable is False
    assert "Timeout" in result.error_message
    assert result.accessibility is None
    assert result.social_media is None
    assert result.tech is None
    assert result.third_party_js is None


@pytest.mark.asyncio
async def test_scan_url_connection_error():
    """Connection error results in is_reachable=False."""
    scanner = MultiScanner(timeout_seconds=10)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=httpx.ConnectError("refused")
        )
        result = await scanner.scan_url("https://gone.gov/")

    assert result.is_reachable is False
    assert "Connection error" in result.error_message


@pytest.mark.asyncio
async def test_scan_url_too_many_redirects():
    """Too many redirects results in is_reachable=False."""
    scanner = MultiScanner(timeout_seconds=10)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=httpx.TooManyRedirects("loop", request=Mock())
        )
        result = await scanner.scan_url("https://loop.gov/")

    assert result.is_reachable is False
    assert "redirects" in result.error_message.lower()


@pytest.mark.asyncio
async def test_scan_url_http_error():
    """Generic HTTP error results in is_reachable=False."""
    scanner = MultiScanner(timeout_seconds=10)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=httpx.HTTPError("bad request")
        )
        result = await scanner.scan_url("https://bad.gov/")

    assert result.is_reachable is False
    assert "HTTP error" in result.error_message


# ---------------------------------------------------------------------------
# MultiScanner.scan_urls_batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_urls_batch_returns_results_for_all_urls():
    """Batch scanning returns a result entry for every URL."""
    scanner = MultiScanner(timeout_seconds=10)

    urls = [
        "https://gov1.example/",
        "https://gov2.example/",
    ]

    async def mock_get(url, **kwargs):
        return _make_mock_response(url)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=mock_get
        )
        results = await scanner.scan_urls_batch(urls, rate_limit_per_second=0)

    assert len(results) == 2
    for url in urls:
        assert url in results
        assert results[url].is_reachable is True


@pytest.mark.asyncio
async def test_scan_urls_batch_on_result_callback():
    """on_result callback is invoked once per URL in order."""
    scanner = MultiScanner(timeout_seconds=10)
    urls = ["https://gov1.example/", "https://gov2.example/"]
    captured: list[MultiScanResult] = []

    async def mock_get(url, **kwargs):
        return _make_mock_response(url)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=mock_get
        )
        results = await scanner.scan_urls_batch(
            urls,
            rate_limit_per_second=0,
            on_result=captured.append,
        )

    assert len(captured) == 2
    assert captured[0].url == urls[0]
    assert captured[1].url == urls[1]
    assert captured[0] is results[urls[0]]
    assert captured[1] is results[urls[1]]
    # Verify the callback receives complete, valid result objects
    assert captured[0].is_reachable is True
    assert captured[0].accessibility is not None
    assert captured[1].is_reachable is True
    assert captured[1].social_media is not None


@pytest.mark.asyncio
async def test_scan_urls_batch_stops_early_when_budget_exhausted():
    """Batch stops immediately when the time budget is already exceeded."""
    scanner = MultiScanner(timeout_seconds=10)
    urls = ["https://gov1.example/", "https://gov2.example/", "https://gov3.example/"]

    past_start = time.monotonic() - 3600  # 1 hour ago

    async def mock_get(url, **kwargs):
        return _make_mock_response(url)

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
    scanner = MultiScanner(timeout_seconds=10)
    urls = ["https://gov1.example/", "https://gov2.example/"]

    async def mock_get(url, **kwargs):
        return _make_mock_response(url)

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
# _print_result_summary (smoke test)
# ---------------------------------------------------------------------------


def test_print_result_summary_reachable(capsys):
    """Summary prints sub-result counts for a reachable URL."""
    result = MultiScanResult(
        url="https://example.gov/",
        is_reachable=True,
        accessibility=AccessibilityScanResult(
            url="https://example.gov/",
            is_reachable=True,
            has_statement=True,
        ),
        social_media=SocialMediaScanResult(
            url="https://example.gov/",
            is_reachable=True,
            social_tier="twitter_only",
        ),
        tech=TechDetectionResult(
            url="https://example.gov/",
            technologies={"WordPress": {"versions": [], "categories": ["CMS"]}},
        ),
        third_party_js=ThirdPartyJsScanResult(
            url="https://example.gov/",
            is_reachable=True,
        ),
    )
    _print_result_summary(result)
    captured = capsys.readouterr()
    assert "statement found" in captured.out
    assert "twitter_only" in captured.out
    assert "1 tech" in captured.out


def test_print_result_summary_unreachable(capsys):
    """Summary prints an error note for an unreachable URL."""
    result = MultiScanResult(
        url="https://gone.gov/",
        is_reachable=False,
        error_message="Timeout: read timeout",
    )
    _print_result_summary(result)
    captured = capsys.readouterr()
    assert "Unreachable" in captured.out


# ---------------------------------------------------------------------------
# scan_html / detect_html passthrough (regression: existing scan_url still works)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accessibility_scan_url_still_works():
    """Refactored AccessibilityScanner.scan_url still produces correct results."""
    from src.services.accessibility_scanner import AccessibilityScanner

    scanner = AccessibilityScanner()

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.url = "https://example.gov/"
    mock_response.text = _SIMPLE_HTML

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=mock_response
        )
        result = await scanner.scan_url("https://example.gov/")

    assert result.is_reachable is True
    assert result.has_statement is True


@pytest.mark.asyncio
async def test_social_media_scan_url_still_works():
    """Refactored SocialMediaScanner.scan_url still produces correct results."""
    from src.services.social_media_scanner import SocialMediaScanner

    scanner = SocialMediaScanner()

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.url = "https://example.gov/"
    mock_response.text = _SIMPLE_HTML

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=mock_response
        )
        result = await scanner.scan_url("https://example.gov/")

    assert result.is_reachable is True
    assert len(result.twitter_links) > 0


@pytest.mark.asyncio
async def test_third_party_js_scan_url_still_works():
    """Refactored ThirdPartyJsScanner.scan_url still produces correct results."""
    from src.services.third_party_js_scanner import ThirdPartyJsScanner

    scanner = ThirdPartyJsScanner()

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.url = "https://example.gov/"
    mock_response.text = _SIMPLE_HTML

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=mock_response
        )
        result = await scanner.scan_url("https://example.gov/")

    assert result.is_reachable is True
    assert result.third_party_count >= 1
