"""Unit tests for the technology detection service."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from src.services.tech_detector import TechDetector


@pytest.mark.asyncio
async def test_detect_url_success():
    """Test successful technology detection."""
    detector = TechDetector(timeout_seconds=10)

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.url = "https://example.gov/"
    mock_response.text = "<html><head><meta name='generator' content='WordPress 6.0'></head></html>"
    mock_response.headers = {"content-type": "text/html", "x-powered-by": "PHP/8.1"}

    expected_techs = {
        "WordPress": {"versions": ["6.0"], "categories": ["CMS", "Blogs"]},
        "PHP": {"versions": ["8.1"], "categories": ["Programming languages"]},
    }

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        with patch.object(
            detector,
            "_get_wappalyzer",
        ) as mock_get_wap:
            mock_wap = Mock()
            mock_wap.analyze_with_versions_and_categories.return_value = expected_techs
            mock_get_wap.return_value = mock_wap

            with patch("src.services.tech_detector.WebPage") as mock_webpage_cls:
                mock_webpage_cls.return_value = Mock()
                result = await detector.detect_url("https://example.gov/")

    assert result.url == "https://example.gov/"
    assert result.technologies == expected_techs
    assert result.error_message is None
    assert result.scanned_at is not None


@pytest.mark.asyncio
async def test_detect_url_no_technologies_detected():
    """Test URL where no technologies are detected."""
    detector = TechDetector(timeout_seconds=10)

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.url = "https://minimal.gov/"
    mock_response.text = "<html><body>Hello</body></html>"
    mock_response.headers = {}

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        with patch.object(detector, "_get_wappalyzer") as mock_get_wap:
            mock_wap = Mock()
            mock_wap.analyze_with_versions_and_categories.return_value = {}
            mock_get_wap.return_value = mock_wap

            with patch("src.services.tech_detector.WebPage") as mock_webpage_cls:
                mock_webpage_cls.return_value = Mock()
                result = await detector.detect_url("https://minimal.gov/")

    assert result.technologies == {}
    assert result.error_message is None


@pytest.mark.asyncio
async def test_detect_url_timeout():
    """Test technology detection when request times out."""
    detector = TechDetector(timeout_seconds=1)

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
        mock_client.return_value.__aenter__.return_value.get = mock_get

        result = await detector.detect_url("https://slow.gov/")

    assert result.technologies == {}
    assert result.error_message is not None
    assert "Timeout" in result.error_message


@pytest.mark.asyncio
async def test_detect_url_connection_error():
    """Test technology detection when the host is unreachable."""
    detector = TechDetector(timeout_seconds=10)

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(side_effect=httpx.ConnectError("Connection failed"))
        mock_client.return_value.__aenter__.return_value.get = mock_get

        result = await detector.detect_url("https://unreachable.gov/")

    assert result.technologies == {}
    assert "Connection error" in result.error_message


@pytest.mark.asyncio
async def test_detect_url_too_many_redirects():
    """Test technology detection with redirect loop."""
    detector = TechDetector(timeout_seconds=10)

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(
            side_effect=httpx.TooManyRedirects("Too many redirects", request=Mock())
        )
        mock_client.return_value.__aenter__.return_value.get = mock_get

        result = await detector.detect_url("https://loop.gov/")

    assert result.technologies == {}
    assert "Too many redirects" in result.error_message


@pytest.mark.asyncio
async def test_detect_urls_batch_no_delay():
    """Test batch technology detection without rate-limit delay."""
    detector = TechDetector(timeout_seconds=10)

    urls = [
        "https://gov1.example/",
        "https://gov2.example/",
    ]

    expected_techs = {"Nginx": {"versions": ["1.24"], "categories": ["Web servers"]}}

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = "<html></html>"
    mock_response.headers = {"server": "nginx/1.24"}

    async def mock_get_side_effect(*args, **kwargs):
        url_arg = args[0] if args else kwargs.get("url", urls[0])
        mock_response.url = url_arg
        return mock_response

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(side_effect=mock_get_side_effect)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        with patch.object(detector, "_get_wappalyzer") as mock_get_wap:
            mock_wap = Mock()
            mock_wap.analyze_with_versions_and_categories.return_value = expected_techs
            mock_get_wap.return_value = mock_wap

            with patch("src.services.tech_detector.WebPage") as mock_webpage_cls:
                mock_webpage_cls.return_value = Mock()
                results = await detector.detect_urls_batch(urls, rate_limit_per_second=0)

    assert len(results) == 2
    for url in urls:
        assert url in results
        assert results[url].technologies == expected_techs
        assert results[url].error_message is None


@pytest.mark.asyncio
async def test_detect_urls_batch():
    """Test batch technology detection."""
    detector = TechDetector(timeout_seconds=10)

    urls = [
        "https://gov1.example/",
        "https://gov2.example/",
    ]

    expected_techs = {"Nginx": {"versions": ["1.24"], "categories": ["Web servers"]}}

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = "<html></html>"
    mock_response.headers = {"server": "nginx/1.24"}

    async def mock_get_side_effect(*args, **kwargs):
        url_arg = args[0] if args else kwargs.get("url", urls[0])
        mock_response.url = url_arg
        return mock_response

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(side_effect=mock_get_side_effect)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        with patch.object(detector, "_get_wappalyzer") as mock_get_wap:
            mock_wap = Mock()
            mock_wap.analyze_with_versions_and_categories.return_value = expected_techs
            mock_get_wap.return_value = mock_wap

            with patch("src.services.tech_detector.WebPage") as mock_webpage_cls:
                mock_webpage_cls.return_value = Mock()
                results = await detector.detect_urls_batch(urls, rate_limit_per_second=0)

    assert len(results) == 2
    for url in urls:
        assert url in results
        assert results[url].technologies == expected_techs
        assert results[url].error_message is None


@pytest.mark.asyncio
async def test_detect_urls_batch_on_result_called_for_each_url():
    """Test that on_result callback is invoked for every scanned URL."""
    detector = TechDetector(timeout_seconds=10)

    urls = [
        "https://gov1.example/",
        "https://gov2.example/",
    ]

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = "<html></html>"
    mock_response.headers = {}

    async def mock_get_side_effect(*args, **kwargs):
        url_arg = args[0] if args else kwargs.get("url", urls[0])
        mock_response.url = url_arg
        return mock_response

    collected: list = []

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(side_effect=mock_get_side_effect)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        with patch.object(detector, "_get_wappalyzer") as mock_get_wap:
            mock_wap = Mock()
            mock_wap.analyze_with_versions_and_categories.return_value = {}
            mock_get_wap.return_value = mock_wap

            with patch("src.services.tech_detector.WebPage") as mock_webpage_cls:
                mock_webpage_cls.return_value = Mock()
                await detector.detect_urls_batch(
                    urls,
                    rate_limit_per_second=0,
                    on_result=collected.append,
                )

    assert len(collected) == 2
    assert {r.url for r in collected} == set(urls)


@pytest.mark.asyncio
async def test_detect_urls_batch_stops_early_when_budget_exhausted():
    """Test that scanning stops when max_runtime_seconds budget is used up."""
    import time as time_mod

    detector = TechDetector(timeout_seconds=10)

    urls = [
        "https://gov1.example/",
        "https://gov2.example/",
        "https://gov3.example/",
    ]

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = "<html></html>"
    mock_response.headers = {}

    async def mock_get_side_effect(*args, **kwargs):
        url_arg = args[0] if args else kwargs.get("url", urls[0])
        mock_response.url = url_arg
        return mock_response

    # Budget is already almost exhausted (only 30 s left, safety buffer is 60 s)
    elapsed_start = time_mod.monotonic() - 9970  # 9970 s ago → 30 s remaining of 10000

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(side_effect=mock_get_side_effect)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        with patch.object(detector, "_get_wappalyzer") as mock_get_wap:
            mock_wap = Mock()
            mock_wap.analyze_with_versions_and_categories.return_value = {}
            mock_get_wap.return_value = mock_wap

            with patch("src.services.tech_detector.WebPage") as mock_webpage_cls:
                mock_webpage_cls.return_value = Mock()
                results = await detector.detect_urls_batch(
                    urls,
                    rate_limit_per_second=0,
                    max_runtime_seconds=10000,
                    start_time=elapsed_start,
                )

    # All 3 URLs should be skipped because the budget is already exhausted
    assert len(results) == 0


@pytest.mark.asyncio
async def test_detect_urls_batch_no_max_runtime_scans_all():
    """Test that all URLs are scanned when max_runtime_seconds is None."""
    detector = TechDetector(timeout_seconds=10)

    urls = ["https://gov1.example/", "https://gov2.example/", "https://gov3.example/"]

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = "<html></html>"
    mock_response.headers = {}

    async def mock_get_side_effect(*args, **kwargs):
        url_arg = args[0] if args else kwargs.get("url", urls[0])
        mock_response.url = url_arg
        return mock_response

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(side_effect=mock_get_side_effect)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        with patch.object(detector, "_get_wappalyzer") as mock_get_wap:
            mock_wap = Mock()
            mock_wap.analyze_with_versions_and_categories.return_value = {}
            mock_get_wap.return_value = mock_wap

            with patch("src.services.tech_detector.WebPage") as mock_webpage_cls:
                mock_webpage_cls.return_value = Mock()
                results = await detector.detect_urls_batch(
                    urls,
                    rate_limit_per_second=0,
                    max_runtime_seconds=None,
                )

    assert len(results) == 3


@pytest.mark.asyncio
async def test_detect_url_analysis_error():
    """Test graceful handling of Wappalyzer analysis failure."""
    detector = TechDetector(timeout_seconds=10)

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.url = "https://broken.gov/"
    mock_response.text = "<html></html>"
    mock_response.headers = {}

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        with patch.object(detector, "_get_wappalyzer") as mock_get_wap:
            mock_wap = Mock()
            mock_wap.analyze_with_versions_and_categories.side_effect = RuntimeError(
                "parser failed"
            )
            mock_get_wap.return_value = mock_wap

            with patch("src.services.tech_detector.WebPage") as mock_webpage_cls:
                mock_webpage_cls.return_value = Mock()
                result = await detector.detect_url("https://broken.gov/")

    assert result.technologies == {}
    assert "Analysis error" in result.error_message
