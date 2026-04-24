"""Unit tests for the social media link scanner service."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from src.services.social_media_scanner import (
    SocialMediaScanResult,
    SocialMediaScanner,
    _classify_tier,
    _extract_social_links,
)


# ---------------------------------------------------------------------------
# _extract_social_links helpers
# ---------------------------------------------------------------------------

def test_extract_twitter_links():
    """Detect links to twitter.com."""
    html = """
    <html><body>
      <a href="https://twitter.com/govuk">Twitter</a>
      <a href="https://www.twitter.com/someagency">Follow us</a>
    </body></html>
    """
    links = _extract_social_links(html, "https://example.gov/")
    assert links["twitter"] == [
        "https://twitter.com/govuk",
        "https://www.twitter.com/someagency",
    ]
    assert links["x"] == []
    assert links["bluesky"] == []
    assert links["mastodon"] == []
    assert links["facebook"] == []
    assert links["linkedin"] == []


def test_extract_x_links():
    """Detect links to x.com."""
    html = """
    <html><body>
      <a href="https://x.com/govuk">X (Twitter)</a>
    </body></html>
    """
    links = _extract_social_links(html, "https://example.gov/")
    assert links["x"] == ["https://x.com/govuk"]
    assert links["twitter"] == []
    assert links["facebook"] == []
    assert links["linkedin"] == []


def test_extract_facebook_links():
    """Detect links to facebook.com and fb.com."""
    html = """
    <html><body>
      <a href="https://www.facebook.com/govagency">Facebook</a>
      <a href="https://fb.com/shortlink">FB short</a>
    </body></html>
    """
    links = _extract_social_links(html, "https://example.gov/")
    assert "https://www.facebook.com/govagency" in links["facebook"]
    assert "https://fb.com/shortlink" in links["facebook"]
    assert links["twitter"] == []
    assert links["linkedin"] == []


def test_extract_linkedin_links():
    """Detect links to linkedin.com."""
    html = """
    <html><body>
      <a href="https://www.linkedin.com/company/govagency">LinkedIn</a>
    </body></html>
    """
    links = _extract_social_links(html, "https://example.gov/")
    assert "https://www.linkedin.com/company/govagency" in links["linkedin"]
    assert links["twitter"] == []
    assert links["facebook"] == []


def test_extract_bluesky_links():
    """Detect links to bsky.app and bsky.social."""
    html = """
    <html><body>
      <a href="https://bsky.app/profile/gov.bsky.social">Bluesky</a>
      <a href="https://bsky.social/profile/agency">Agency</a>
    </body></html>
    """
    links = _extract_social_links(html, "https://example.gov/")
    assert "https://bsky.app/profile/gov.bsky.social" in links["bluesky"]
    assert "https://bsky.social/profile/agency" in links["bluesky"]


def test_extract_mastodon_known_instance():
    """Detect links to a known Mastodon instance."""
    html = """
    <html><body>
      <a href="https://mastodon.social/@govuk">Mastodon</a>
    </body></html>
    """
    links = _extract_social_links(html, "https://example.gov/")
    assert "https://mastodon.social/@govuk" in links["mastodon"]


def test_extract_mastodon_profile_pattern():
    """Detect links to unknown instances using the /@user path pattern."""
    html = """
    <html><body>
      <a href="https://social.example.org/@agency">Our Mastodon</a>
    </body></html>
    """
    links = _extract_social_links(html, "https://example.gov/")
    assert "https://social.example.org/@agency" in links["mastodon"]


def test_extract_mastodon_handle_in_text():
    """Detect @user@domain handles in plain text."""
    html = """
    <html><body>
      <p>Find us at @agency@mastodon.social for updates.</p>
    </body></html>
    """
    links = _extract_social_links(html, "https://example.gov/")
    assert any("mastodon.social" in m for m in links["mastodon"])


def test_extract_no_social_links():
    """Return empty lists when no social media links are present."""
    html = "<html><body><p>Nothing here</p></body></html>"
    links = _extract_social_links(html, "https://example.gov/")
    assert links["twitter"] == []
    assert links["x"] == []
    assert links["bluesky"] == []
    assert links["mastodon"] == []
    assert links["facebook"] == []
    assert links["linkedin"] == []


def test_extract_deduplicates_links():
    """Duplicate hrefs are only included once."""
    html = """
    <html><body>
      <a href="https://twitter.com/gov">Twitter</a>
      <a href="https://twitter.com/gov">Twitter (footer)</a>
    </body></html>
    """
    links = _extract_social_links(html, "https://example.gov/")
    assert links["twitter"].count("https://twitter.com/gov") == 1


# ---------------------------------------------------------------------------
# _classify_tier
# ---------------------------------------------------------------------------

def test_classify_tier_unreachable():
    result = SocialMediaScanResult(url="https://gone.gov/", is_reachable=False)
    assert _classify_tier(result) == "unreachable"


def test_classify_tier_no_social():
    result = SocialMediaScanResult(url="https://clean.gov/", is_reachable=True)
    assert _classify_tier(result) == "no_social"


def test_classify_tier_twitter_only():
    result = SocialMediaScanResult(
        url="https://legacy.gov/",
        is_reachable=True,
        twitter_links=["https://twitter.com/gov"],
    )
    assert _classify_tier(result) == "twitter_only"


def test_classify_tier_x_counts_as_legacy():
    result = SocialMediaScanResult(
        url="https://legacy.gov/",
        is_reachable=True,
        x_links=["https://x.com/gov"],
    )
    assert _classify_tier(result) == "twitter_only"


def test_classify_tier_facebook_counts_as_legacy():
    result = SocialMediaScanResult(
        url="https://legacy.gov/",
        is_reachable=True,
        facebook_links=["https://www.facebook.com/govpage"],
    )
    assert _classify_tier(result) == "twitter_only"


def test_classify_tier_linkedin_counts_as_legacy():
    result = SocialMediaScanResult(
        url="https://legacy.gov/",
        is_reachable=True,
        linkedin_links=["https://www.linkedin.com/company/govagency"],
    )
    assert _classify_tier(result) == "twitter_only"


def test_classify_tier_facebook_plus_modern_is_mixed():
    result = SocialMediaScanResult(
        url="https://both.gov/",
        is_reachable=True,
        facebook_links=["https://www.facebook.com/govpage"],
        bluesky_links=["https://bsky.app/profile/gov"],
    )
    assert _classify_tier(result) == "mixed"


def test_classify_tier_modern_only():
    result = SocialMediaScanResult(
        url="https://modern.gov/",
        is_reachable=True,
        bluesky_links=["https://bsky.app/profile/gov"],
    )
    assert _classify_tier(result) == "modern_only"


def test_classify_tier_mixed():
    result = SocialMediaScanResult(
        url="https://both.gov/",
        is_reachable=True,
        twitter_links=["https://twitter.com/gov"],
        mastodon_links=["https://mastodon.social/@gov"],
    )
    assert _classify_tier(result) == "mixed"


# ---------------------------------------------------------------------------
# SocialMediaScanner.scan_url
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scan_url_success_no_social():
    """Successful fetch of a page with no social media links."""
    scanner = SocialMediaScanner(timeout_seconds=10)

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.url = "https://example.gov/"
    mock_response.text = "<html><body><p>No social here</p></body></html>"

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        result = await scanner.scan_url("https://example.gov/")

    assert result.url == "https://example.gov/"
    assert result.is_reachable is True
    assert result.twitter_links == []
    assert result.x_links == []
    assert result.bluesky_links == []
    assert result.mastodon_links == []
    assert result.facebook_links == []
    assert result.linkedin_links == []
    assert result.social_tier == "no_social"
    assert result.error_message is None
    assert result.scanned_at is not None


@pytest.mark.asyncio
async def test_scan_url_success_with_twitter():
    """Successful fetch of a page that has Twitter links."""
    scanner = SocialMediaScanner(timeout_seconds=10)

    html = '<html><body><a href="https://twitter.com/gov">Twitter</a></body></html>'

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.url = "https://gov.example/"
    mock_response.text = html

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        result = await scanner.scan_url("https://gov.example/")

    assert result.is_reachable is True
    assert result.twitter_links == ["https://twitter.com/gov"]
    assert result.social_tier == "twitter_only"


@pytest.mark.asyncio
async def test_scan_url_success_mixed():
    """Page with both Twitter and Mastodon links → mixed tier."""
    scanner = SocialMediaScanner(timeout_seconds=10)

    html = """
    <html><body>
      <a href="https://twitter.com/gov">Twitter</a>
      <a href="https://mastodon.social/@gov">Mastodon</a>
    </body></html>
    """

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.url = "https://gov.example/"
    mock_response.text = html

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        result = await scanner.scan_url("https://gov.example/")

    assert result.social_tier == "mixed"
    assert result.twitter_links == ["https://twitter.com/gov"]
    assert "https://mastodon.social/@gov" in result.mastodon_links


@pytest.mark.asyncio
async def test_scan_url_timeout():
    """Timeout results in unreachable result."""
    scanner = SocialMediaScanner(timeout_seconds=1)

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
        mock_client.return_value.__aenter__.return_value.get = mock_get

        result = await scanner.scan_url("https://slow.gov/")

    assert result.is_reachable is False
    assert result.social_tier == "unreachable"
    assert "Timeout" in result.error_message


@pytest.mark.asyncio
async def test_scan_url_connection_error():
    """Connection error results in unreachable result."""
    scanner = SocialMediaScanner(timeout_seconds=10)

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.return_value.__aenter__.return_value.get = mock_get

        result = await scanner.scan_url("https://gone.gov/")

    assert result.is_reachable is False
    assert result.social_tier == "unreachable"
    assert "Connection error" in result.error_message


@pytest.mark.asyncio
async def test_scan_url_too_many_redirects():
    """Too many redirects results in unreachable result."""
    scanner = SocialMediaScanner(timeout_seconds=10)

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(
            side_effect=httpx.TooManyRedirects("loop", request=Mock())
        )
        mock_client.return_value.__aenter__.return_value.get = mock_get

        result = await scanner.scan_url("https://redirect-loop.gov/")

    assert result.is_reachable is False
    assert result.social_tier == "unreachable"


@pytest.mark.asyncio
async def test_scan_urls_batch():
    """Batch scanning returns results for all URLs."""
    scanner = SocialMediaScanner(timeout_seconds=10)

    urls = [
        "https://gov1.example/",
        "https://gov2.example/",
    ]

    html_no_social = "<html><body><p>No social</p></body></html>"
    html_twitter = '<html><body><a href="https://twitter.com/g2">T</a></body></html>'

    responses = {
        urls[0]: html_no_social,
        urls[1]: html_twitter,
    }

    async def mock_get(url, **kwargs):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.url = url
        mock_response.text = responses[url]
        return mock_response

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=mock_get
        )
        results = await scanner.scan_urls_batch(urls, rate_limit_per_second=0)

    assert len(results) == 2
    assert results[urls[0]].social_tier == "no_social"
    assert results[urls[1]].social_tier == "twitter_only"


# ---------------------------------------------------------------------------
# scan_urls_batch — on_result callback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_urls_batch_on_result_called_for_each_url():
    """on_result callback is invoked once per scanned URL, in order."""
    scanner = SocialMediaScanner(timeout_seconds=10)
    urls = ["https://gov1.example/", "https://gov2.example/"]

    saved: list[SocialMediaScanResult] = []

    def capture(result: SocialMediaScanResult) -> None:
        saved.append(result)

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
            urls, rate_limit_per_second=0, on_result=capture
        )

    assert len(saved) == 2
    assert saved[0].url == urls[0]
    assert saved[1].url == urls[1]
    # Callback results match the returned dict
    assert saved[0] is results[urls[0]]
    assert saved[1] is results[urls[1]]


@pytest.mark.asyncio
async def test_scan_urls_batch_no_callback_still_works():
    """Omitting on_result does not break anything — backward compatibility."""
    scanner = SocialMediaScanner(timeout_seconds=10)
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


# ---------------------------------------------------------------------------
# scan_urls_batch — max_runtime_seconds early stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_urls_batch_stops_early_when_budget_exhausted():
    """
    When start_time is in the distant past the budget is already exhausted
    and no URLs should be scanned.
    """
    scanner = SocialMediaScanner(timeout_seconds=10)
    urls = ["https://gov1.example/", "https://gov2.example/", "https://gov3.example/"]

    async def mock_get(url, **kwargs):
        r = Mock()
        r.status_code = 200
        r.url = url
        r.text = "<html><body></body></html>"
        return r

    # Simulate a start_time 1 hour ago with only a 1-second budget ⇒
    # remaining = 1.0 - 3600 ≈ -3599 < 60 (safety buffer) → stop immediately.
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
    scanner = SocialMediaScanner(timeout_seconds=10)
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
