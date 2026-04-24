"""Unit tests for URL validator service."""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from src.services.url_validator import UrlValidator, ValidationResult


@pytest.mark.asyncio
async def test_validate_url_success():
    """Test successful URL validation."""
    validator = UrlValidator(timeout_seconds=10)
    
    # Mock httpx response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.url = "https://example.com/"
    mock_response.is_redirect = False
    
    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get
        
        result = await validator.validate_url("https://example.com/")
        
        assert result.is_valid is True
        assert result.status_code == 200
        assert result.url == "https://example.com/"
        assert result.error_message is None
        assert result.redirected_to is None


@pytest.mark.asyncio
async def test_validate_url_redirect():
    """Test URL validation with redirect."""
    validator = UrlValidator(timeout_seconds=10)
    
    # Mock httpx response with redirect (final URL different from original)
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.url = "https://example.com/new-page"
    mock_response.is_redirect = False
    
    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get
        
        result = await validator.validate_url("https://example.com/old-page")
        
        # Verify redirect was detected
        assert result.is_valid is True
        assert result.status_code == 200
        assert result.url == "https://example.com/old-page"
        assert result.redirected_to == "https://example.com/new-page"
        # Note: redirect_chain tracking is tested in integration tests with real httpx behavior


@pytest.mark.asyncio
async def test_validate_url_404():
    """Test URL validation with 404 error."""
    validator = UrlValidator(timeout_seconds=10)
    
    # Mock httpx response with 404
    mock_response = Mock()
    mock_response.status_code = 404
    mock_response.url = "https://example.com/missing"
    mock_response.is_redirect = False
    
    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get
        
        result = await validator.validate_url("https://example.com/missing")
        
        assert result.is_valid is False
        assert result.status_code == 404
        assert result.error_message is None


@pytest.mark.asyncio
async def test_validate_url_timeout():
    """Test URL validation with timeout."""
    import httpx
    
    validator = UrlValidator(timeout_seconds=1)
    
    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
        mock_client.return_value.__aenter__.return_value.get = mock_get
        
        result = await validator.validate_url("https://slow-example.com/")
        
        assert result.is_valid is False
        assert result.status_code is None
        assert "Timeout" in result.error_message


@pytest.mark.asyncio
async def test_validate_url_connection_error():
    """Test URL validation with connection error."""
    import httpx
    
    validator = UrlValidator(timeout_seconds=10)
    
    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(side_effect=httpx.ConnectError("Connection failed"))
        mock_client.return_value.__aenter__.return_value.get = mock_get
        
        result = await validator.validate_url("https://unreachable.example.com/")
        
        assert result.is_valid is False
        assert result.status_code is None
        assert "Connection error" in result.error_message


@pytest.mark.asyncio
async def test_validate_urls_batch():
    """Test batch URL validation."""
    validator = UrlValidator(timeout_seconds=10)
    
    urls = [
        "https://example1.com/",
        "https://example2.com/",
        "https://example3.com/",
    ]
    
    # Mock successful responses for all URLs
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.is_redirect = False
    
    async def mock_get_side_effect(*args, **kwargs):
        # Return mock response with URL from the call
        url_arg = args[0] if args else kwargs.get('url', urls[0])
        mock_response.url = url_arg
        return mock_response
    
    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(side_effect=mock_get_side_effect)
        mock_client.return_value.__aenter__.return_value.get = mock_get
        
        results = await validator.validate_urls_batch(urls, rate_limit_per_second=0)
        
        assert len(results) == 3
        assert all(r.is_valid for r in results.values())
        assert all(r.url in urls for r in results.values())


@pytest.mark.asyncio
async def test_validate_urls_batch_stops_early_when_budget_exhausted():
    """Test that validate_urls_batch stops early when the time budget runs out."""
    import time

    validator = UrlValidator(timeout_seconds=10)

    urls = [f"https://example{i}.com/" for i in range(10)]

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.is_redirect = False

    async def mock_get_side_effect(*args, **kwargs):
        url_arg = args[0] if args else kwargs.get("url", urls[0])
        mock_response.url = url_arg
        return mock_response

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(side_effect=mock_get_side_effect)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        # Set start_time far in the past so the budget is already exhausted
        past_start = time.monotonic() - 10_000
        results = await validator.validate_urls_batch(
            urls,
            rate_limit_per_second=0,
            max_runtime_seconds=100,   # budget = 100 s; but 10,000 s have elapsed
            start_time=past_start,
        )

    # Should have processed 0 URLs because the budget is already exhausted
    assert len(results) == 0


@pytest.mark.asyncio
async def test_validate_urls_batch_on_result_called_for_each_url():
    """Test that the on_result callback is called for every URL validated."""
    validator = UrlValidator(timeout_seconds=10)

    urls = [
        "https://example1.com/",
        "https://example2.com/",
    ]

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.is_redirect = False

    async def mock_get_side_effect(*args, **kwargs):
        url_arg = args[0] if args else kwargs.get("url", urls[0])
        mock_response.url = url_arg
        return mock_response

    collected: list = []

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(side_effect=mock_get_side_effect)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        results = await validator.validate_urls_batch(
            urls,
            rate_limit_per_second=0,
            on_result=collected.append,
        )

    assert len(collected) == 2
    assert len(results) == 2


@pytest.mark.asyncio
async def test_validate_urls_batch_no_max_runtime_validates_all():
    """With no max_runtime_seconds all URLs should be validated."""
    validator = UrlValidator(timeout_seconds=10)

    urls = [f"https://example{i}.com/" for i in range(5)]

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.is_redirect = False

    async def mock_get_side_effect(*args, **kwargs):
        url_arg = args[0] if args else kwargs.get("url", urls[0])
        mock_response.url = url_arg
        return mock_response

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(side_effect=mock_get_side_effect)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        results = await validator.validate_urls_batch(urls, rate_limit_per_second=0)

    assert len(results) == 5
