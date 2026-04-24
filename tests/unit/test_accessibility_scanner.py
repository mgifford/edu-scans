"""Unit tests for the accessibility statement scanner service."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from src.services.accessibility_scanner import (
    AccessibilityScanResult,
    AccessibilityScanner,
    _extract_accessibility_links,
    _href_matches,
    _text_matches,
)


# ---------------------------------------------------------------------------
# _text_matches helpers
# ---------------------------------------------------------------------------


def test_text_matches_english():
    """Detect English 'accessibility statement' term."""
    hit, term = _text_matches("Accessibility Statement")
    assert hit is True
    assert "accessibility" in term


def test_text_matches_german():
    """Detect German Barrierefreiheit term."""
    hit, term = _text_matches("Erklärung zur Barrierefreiheit")
    assert hit is True


def test_text_matches_french():
    """Detect French accessibilité term."""
    hit, term = _text_matches("Déclaration d'accessibilité")
    assert hit is True


def test_text_matches_no_match():
    """Return (False, '') when text contains no known accessibility term."""
    hit, term = _text_matches("Contact us | Privacy policy")
    assert hit is False
    assert term == ""


# ---------------------------------------------------------------------------
# _href_matches helpers
# ---------------------------------------------------------------------------


def test_href_matches_english_path():
    assert _href_matches("https://example.gov/accessibility-statement") is True


def test_href_matches_german_path():
    assert _href_matches("https://example.de/barrierefreiheit") is True


def test_href_matches_no_match():
    assert _href_matches("https://example.gov/contact-us") is False


# ---------------------------------------------------------------------------
# _extract_accessibility_links
# ---------------------------------------------------------------------------


def test_extract_from_footer_by_text():
    """Link in <footer> with matching text is detected and found_in_footer=True."""
    html = """
    <html><body>
      <main><p>Main content</p></main>
      <footer>
        <a href="/accessibility-statement">Accessibility Statement</a>
      </footer>
    </body></html>
    """
    links, terms, found_in_footer = _extract_accessibility_links(
        html, "https://example.gov/"
    )
    assert len(links) == 1
    assert "accessibility-statement" in links[0]
    assert found_in_footer is True


def test_extract_from_footer_by_href():
    """Link in <footer> with matching href path is detected even if text differs."""
    html = """
    <html><body>
      <footer>
        <a href="/barrierefreiheit">Barrierefreiheit</a>
      </footer>
    </body></html>
    """
    links, terms, found_in_footer = _extract_accessibility_links(
        html, "https://example.de/"
    )
    assert len(links) >= 1
    assert found_in_footer is True


def test_extract_fallback_to_full_page():
    """When no <footer> element exists, the full page is scanned as fallback."""
    html = """
    <html><body>
      <div class="nav">
        <a href="/accessibility">Accessibility</a>
      </div>
    </body></html>
    """
    links, terms, found_in_footer = _extract_accessibility_links(
        html, "https://example.gov/"
    )
    assert len(links) >= 1
    assert found_in_footer is False


def test_extract_aria_contentinfo():
    """Elements with role='contentinfo' are treated as footers."""
    html = """
    <html><body>
      <div role="contentinfo">
        <a href="/accessibility-statement">Accessibility Statement</a>
      </div>
    </body></html>
    """
    links, terms, found_in_footer = _extract_accessibility_links(
        html, "https://example.gov/"
    )
    assert len(links) >= 1
    assert found_in_footer is True


def test_extract_footer_class():
    """Elements with a footer-related CSS class are treated as footers."""
    html = """
    <html><body>
      <div class="site-footer">
        <a href="/tilgaengelighed">Tilgængelighed</a>
      </div>
    </body></html>
    """
    links, terms, found_in_footer = _extract_accessibility_links(
        html, "https://example.dk/"
    )
    assert len(links) >= 1
    assert found_in_footer is True


def test_extract_no_links():
    """Returns empty lists when no accessibility links are present."""
    html = "<html><body><footer><a href='/home'>Home</a></footer></body></html>"
    links, terms, found_in_footer = _extract_accessibility_links(
        html, "https://example.gov/"
    )
    assert links == []
    assert terms == []
    assert found_in_footer is False


def test_extract_multilingual_dutch():
    """Detect Dutch toegankelijkheidsverklaring term."""
    html = """
    <html><body>
      <footer>
        <a href="/toegankelijkheidsverklaring">Toegankelijkheidsverklaring</a>
      </footer>
    </body></html>
    """
    links, terms, found_in_footer = _extract_accessibility_links(
        html, "https://example.nl/"
    )
    assert len(links) >= 1
    assert found_in_footer is True


def test_extract_multilingual_polish():
    """Detect Polish deklaracja dostępności term."""
    html = """
    <html><body>
      <footer>
        <a href="/deklaracja-dostepnosci">Deklaracja dostępności</a>
      </footer>
    </body></html>
    """
    links, terms, found_in_footer = _extract_accessibility_links(
        html, "https://example.pl/"
    )
    assert len(links) >= 1
    assert found_in_footer is True


def test_extract_relative_url_resolved():
    """Relative hrefs are resolved against the base URL."""
    html = """
    <html><body>
      <footer>
        <a href="/en/accessibility">Accessibility</a>
      </footer>
    </body></html>
    """
    links, terms, found_in_footer = _extract_accessibility_links(
        html, "https://example.gov/"
    )
    assert links[0].startswith("https://example.gov/")


def test_extract_skips_mailto_and_anchor():
    """mailto: and anchor (#) hrefs are not processed."""
    html = """
    <html><body>
      <footer>
        <a href="mailto:accessibility@example.gov">Email us</a>
        <a href="#accessibility">Skip</a>
      </footer>
    </body></html>
    """
    links, terms, found_in_footer = _extract_accessibility_links(
        html, "https://example.gov/"
    )
    assert links == []


def test_extract_deduplicates_links():
    """The same absolute URL appears only once in the results."""
    html = """
    <html><body>
      <footer>
        <a href="/accessibility">Accessibility Statement</a>
        <a href="/accessibility">Accessibility Statement (copy)</a>
      </footer>
    </body></html>
    """
    links, terms, found_in_footer = _extract_accessibility_links(
        html, "https://example.gov/"
    )
    assert links.count("https://example.gov/accessibility") == 1


# ---------------------------------------------------------------------------
# AccessibilityScanner.scan_url
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_url_no_statement():
    """Successful fetch of a page with no accessibility statement."""
    scanner = AccessibilityScanner(timeout_seconds=10)

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.url = "https://example.gov/"
    mock_response.text = "<html><body><footer><p>No statement</p></footer></body></html>"

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        result = await scanner.scan_url("https://example.gov/")

    assert result.url == "https://example.gov/"
    assert result.is_reachable is True
    assert result.has_statement is False
    assert result.statement_links == []
    assert result.error_message is None
    assert result.scanned_at is not None


@pytest.mark.asyncio
async def test_scan_url_with_statement_in_footer():
    """Successful fetch of a page that has an accessibility statement in the footer."""
    scanner = AccessibilityScanner(timeout_seconds=10)

    html = """
    <html><body>
      <footer>
        <a href="/accessibility-statement">Accessibility Statement</a>
      </footer>
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

    assert result.is_reachable is True
    assert result.has_statement is True
    assert result.found_in_footer is True
    assert len(result.statement_links) >= 1


@pytest.mark.asyncio
async def test_scan_url_timeout():
    """Timeout results in unreachable result."""
    scanner = AccessibilityScanner(timeout_seconds=1)

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
        mock_client.return_value.__aenter__.return_value.get = mock_get

        result = await scanner.scan_url("https://slow.gov/")

    assert result.is_reachable is False
    assert result.has_statement is False
    assert "Timeout" in result.error_message


@pytest.mark.asyncio
async def test_scan_url_connection_error():
    """Connection error results in unreachable result."""
    scanner = AccessibilityScanner(timeout_seconds=10)

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.return_value.__aenter__.return_value.get = mock_get

        result = await scanner.scan_url("https://gone.gov/")

    assert result.is_reachable is False
    assert "Connection error" in result.error_message


@pytest.mark.asyncio
async def test_scan_url_too_many_redirects():
    """Too many redirects results in unreachable result."""
    scanner = AccessibilityScanner(timeout_seconds=10)

    with patch("httpx.AsyncClient") as mock_client:
        mock_get = AsyncMock(
            side_effect=httpx.TooManyRedirects("loop", request=Mock())
        )
        mock_client.return_value.__aenter__.return_value.get = mock_get

        result = await scanner.scan_url("https://redirect-loop.gov/")

    assert result.is_reachable is False


# ---------------------------------------------------------------------------
# AccessibilityScanner.scan_urls_batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_urls_batch():
    """Batch scanning returns results for all URLs."""
    scanner = AccessibilityScanner(timeout_seconds=10)

    urls = [
        "https://gov1.example/",
        "https://gov2.example/",
    ]

    html_no_statement = "<html><body><footer><p>No statement</p></footer></body></html>"
    html_with_statement = (
        '<html><body><footer>'
        '<a href="/accessibility">Accessibility Statement</a>'
        "</footer></body></html>"
    )

    responses = {
        urls[0]: html_no_statement,
        urls[1]: html_with_statement,
    }

    async def mock_get(url, **kwargs):
        r = Mock()
        r.status_code = 200
        r.url = url
        r.text = responses[url]
        return r

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=mock_get
        )
        results = await scanner.scan_urls_batch(urls, rate_limit_per_second=0)

    assert len(results) == 2
    assert results[urls[0]].has_statement is False
    assert results[urls[1]].has_statement is True


@pytest.mark.asyncio
async def test_scan_urls_batch_on_result_callback():
    """on_result callback is invoked once per scanned URL."""
    scanner = AccessibilityScanner(timeout_seconds=10)
    urls = ["https://gov1.example/", "https://gov2.example/"]

    saved: list[AccessibilityScanResult] = []

    def capture(result: AccessibilityScanResult) -> None:
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
    assert saved[0] is results[urls[0]]
    assert saved[1] is results[urls[1]]


@pytest.mark.asyncio
async def test_scan_urls_batch_stops_early_when_budget_exhausted():
    """When the time budget is already exhausted no URLs are scanned."""
    scanner = AccessibilityScanner(timeout_seconds=10)
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
    scanner = AccessibilityScanner(timeout_seconds=10)
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
            urls, rate_limit_per_second=0, max_runtime_seconds=None
        )

    assert len(results) == 2
