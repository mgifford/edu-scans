"""Unit tests for the accessibility overlay scanner service."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.services.overlay_scanner import (
    OVERLAY_SIGNATURES,
    OverlayScanResult,
    OverlayScanner,
    _detect_overlays,
)


# ---------------------------------------------------------------------------
# _detect_overlays
# ---------------------------------------------------------------------------


def test_detect_overlays_empty_html():
    """Empty page has no overlays."""
    assert _detect_overlays("") == []


def test_detect_overlays_no_match():
    """Page without overlay signatures returns empty list."""
    html = "<html><body><p>Hello world</p></body></html>"
    assert _detect_overlays(html) == []


def test_detect_overlays_accessibe():
    """accessibe.com signature detected correctly."""
    html = '<script src="https://acsbapp.com/apps/app/dist/js/app.js"></script>'
    result = _detect_overlays(html)
    assert "AccessiBe" in result


def test_detect_overlays_userway():
    """userway.org signature detected correctly."""
    html = '<script src="https://cdn.userway.org/widget.js" data-account="abc"></script>'
    result = _detect_overlays(html)
    assert "UserWay" in result


def test_detect_overlays_audioeye():
    """audioeye.com signature detected correctly."""
    html = '<script src="https://wfpjs.audioeye.com/audioeye.js"></script>'
    result = _detect_overlays(html)
    assert "AudioEye" in result


def test_detect_overlays_equalweb():
    """equalweb.com signature detected correctly."""
    html = '<script src="https://cdn.equalweb.com/core/3.0.0/nagishli.min.js"></script>'
    result = _detect_overlays(html)
    assert "EqualWeb" in result


def test_detect_overlays_multiple():
    """Multiple overlays on the same page are all reported."""
    html = (
        '<script src="https://cdn.userway.org/widget.js"></script>'
        '<script src="https://audioeye.com/audioeye.js"></script>'
    )
    result = _detect_overlays(html)
    assert "UserWay" in result
    assert "AudioEye" in result


def test_detect_overlays_case_insensitive():
    """Matching is case-insensitive."""
    html = '<script src="https://CDN.USERWAY.ORG/widget.js"></script>'
    result = _detect_overlays(html)
    assert "UserWay" in result


def test_detect_overlays_returns_sorted():
    """Results are returned in sorted order."""
    html = (
        '<script src="https://cdn.userway.org/widget.js"></script>'
        '<script src="https://acsbapp.com/app.js"></script>'
    )
    result = _detect_overlays(html)
    assert result == sorted(result)


def test_detect_overlays_each_vendor_counted_once():
    """A vendor appearing via multiple signatures is counted only once."""
    # AccessiBe has "accessibe.com", "acsbapp", "acsb.js"
    html = (
        '<script src="https://accessibe.com/accessibe.js"></script>'
        '<script src="https://acsbapp.com/app.js"></script>'
        '<script src="https://cdn.example.com/acsb.js"></script>'
    )
    result = _detect_overlays(html)
    assert result.count("AccessiBe") == 1


def test_overlay_signatures_dict_not_empty():
    """OVERLAY_SIGNATURES dict is populated with known vendors."""
    assert len(OVERLAY_SIGNATURES) > 20
    assert "AccessiBe" in OVERLAY_SIGNATURES
    assert "UserWay" in OVERLAY_SIGNATURES
    assert "AudioEye" in OVERLAY_SIGNATURES


# ---------------------------------------------------------------------------
# OverlayScanResult properties
# ---------------------------------------------------------------------------


def test_overlay_count_property():
    result = OverlayScanResult(url="https://example.gov/", overlays=["AccessiBe", "UserWay"])
    assert result.overlay_count == 2


def test_has_overlay_true():
    result = OverlayScanResult(url="https://example.gov/", overlays=["UserWay"])
    assert result.has_overlay is True


def test_has_overlay_false():
    result = OverlayScanResult(url="https://example.gov/", overlays=[])
    assert result.has_overlay is False


# ---------------------------------------------------------------------------
# OverlayScanner.scan_html
# ---------------------------------------------------------------------------


def test_scan_html_no_overlays():
    scanner = OverlayScanner()
    result = scanner.scan_html("https://gov.example/", "<html><body>Clean page</body></html>")
    assert result.is_reachable is True
    assert result.overlays == []
    assert result.error_message is None


def test_scan_html_with_overlay():
    scanner = OverlayScanner()
    html = '<script src="https://cdn.userway.org/widget.js"></script>'
    result = scanner.scan_html("https://gov.example/", html)
    assert result.is_reachable is True
    assert "UserWay" in result.overlays


def test_scan_html_uses_provided_timestamp():
    scanner = OverlayScanner()
    result = scanner.scan_html("https://gov.example/", "<html/>", scanned_at="2024-01-01T00:00:00+00:00")
    assert result.scanned_at == "2024-01-01T00:00:00+00:00"


def test_scan_html_sets_timestamp_when_none():
    scanner = OverlayScanner()
    result = scanner.scan_html("https://gov.example/", "<html/>")
    assert result.scanned_at is not None


# ---------------------------------------------------------------------------
# OverlayScanner.scan_url (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_url_success():
    """Successful HTTP response is parsed for overlays."""
    scanner = OverlayScanner()
    html = '<script src="https://cdn.userway.org/widget.js"></script>'
    mock_response = AsyncMock()
    mock_response.text = html
    mock_response.url = "https://gov.example/"

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await scanner.scan_url("https://gov.example/")

    assert result.is_reachable is True
    assert "UserWay" in result.overlays


@pytest.mark.asyncio
async def test_scan_url_timeout():
    """Timeout exception sets is_reachable=False and records error."""
    scanner = OverlayScanner()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client_cls.return_value = mock_client

        result = await scanner.scan_url("https://slow.gov/")

    assert result.is_reachable is False
    assert result.error_message is not None
    assert "Timeout" in result.error_message


@pytest.mark.asyncio
async def test_scan_url_connect_error():
    """Connection error sets is_reachable=False."""
    scanner = OverlayScanner()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client_cls.return_value = mock_client

        result = await scanner.scan_url("https://gone.gov/")

    assert result.is_reachable is False
    assert "Connection error" in result.error_message


@pytest.mark.asyncio
async def test_scan_url_too_many_redirects():
    """TooManyRedirects sets is_reachable=False."""
    scanner = OverlayScanner()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=httpx.TooManyRedirects("loop"))
        mock_client_cls.return_value = mock_client

        result = await scanner.scan_url("https://loop.gov/")

    assert result.is_reachable is False
    assert "Too many redirects" in result.error_message


# ---------------------------------------------------------------------------
# OverlayScanner.scan_urls_batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_urls_batch_returns_all():
    """Batch scan returns results for every URL."""
    scanner = OverlayScanner()

    async def _fake_scan(url: str) -> OverlayScanResult:
        return OverlayScanResult(url=url, is_reachable=True)

    scanner.scan_url = _fake_scan

    urls = ["https://a.gov/", "https://b.gov/"]
    results = await scanner.scan_urls_batch(urls, rate_limit_per_second=100)

    assert set(results.keys()) == set(urls)


@pytest.mark.asyncio
async def test_scan_urls_batch_calls_on_result():
    """on_result callback is invoked for each scanned URL."""
    scanner = OverlayScanner()

    async def _fake_scan(url: str) -> OverlayScanResult:
        return OverlayScanResult(url=url, is_reachable=True)

    scanner.scan_url = _fake_scan

    collected: list[OverlayScanResult] = []
    await scanner.scan_urls_batch(
        ["https://a.gov/", "https://b.gov/"],
        rate_limit_per_second=100,
        on_result=collected.append,
    )

    assert len(collected) == 2


@pytest.mark.asyncio
async def test_scan_urls_batch_respects_time_budget():
    """When the time budget is exhausted, scanning stops early."""
    scanner = OverlayScanner()
    call_count = 0

    async def _fake_scan(url: str) -> OverlayScanResult:
        nonlocal call_count
        call_count += 1
        return OverlayScanResult(url=url, is_reachable=True)

    scanner.scan_url = _fake_scan

    # Set start_time so that elapsed > max_runtime - safety_buffer immediately
    past_start = time.monotonic() - 3600  # 1 hour ago
    results = await scanner.scan_urls_batch(
        ["https://a.gov/", "https://b.gov/", "https://c.gov/"],
        rate_limit_per_second=100,
        max_runtime_seconds=10,  # only 10 s budget but 3600 s already elapsed
        start_time=past_start,
    )

    # Budget was exhausted before any URL could be scanned
    assert len(results) == 0
    assert call_count == 0


@pytest.mark.asyncio
async def test_scan_urls_batch_empty_list():
    """Empty URL list returns an empty dict."""
    scanner = OverlayScanner()
    results = await scanner.scan_urls_batch([], rate_limit_per_second=100)
    assert results == {}
