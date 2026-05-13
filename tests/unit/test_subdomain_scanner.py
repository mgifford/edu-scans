"""Unit tests for the subdomain scanner service."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import urlparse

import pytest
import yaml

from src.services.subdomain_scanner import (
    SubdomainScanner,
    _extract_apex_domains_from_toon,
    _existing_urls_for_domain,
    _make_candidate_url,
    load_subdomain_patterns,
)
from src.services.url_validator import ValidationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_toon(domains: list[dict]) -> dict:
    """Minimal TOON dict for testing."""
    return {
        "version": "0.1-seed",
        "country": "TEST",
        "domains": domains,
    }


def _make_domain_entry(
    canonical_domain: str,
    pages: list[dict] | None = None,
) -> dict:
    return {
        "canonical_domain": canonical_domain,
        "pages": pages or [],
    }


# ---------------------------------------------------------------------------
# load_subdomain_patterns
# ---------------------------------------------------------------------------


def test_load_subdomain_patterns_returns_flat_list(tmp_path: Path) -> None:
    """Prefixes from multiple categories are returned as one flat list."""
    patterns_file = tmp_path / "subdomains.yml"
    patterns_file.write_text(
        yaml.dump(
            {
                "academic": ["law", "engineering"],
                "administrative": ["library", "admissions"],
            }
        ),
        encoding="utf-8",
    )

    prefixes = load_subdomain_patterns(patterns_file)

    assert prefixes == ["law", "engineering", "library", "admissions"]


def test_load_subdomain_patterns_deduplicates(tmp_path: Path) -> None:
    """Duplicate entries across categories are de-duplicated."""
    patterns_file = tmp_path / "subdomains.yml"
    patterns_file.write_text(
        yaml.dump({"a": ["law", "library"], "b": ["library", "it"]}),
        encoding="utf-8",
    )

    prefixes = load_subdomain_patterns(patterns_file)

    assert prefixes == ["law", "library", "it"]


def test_load_subdomain_patterns_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_subdomain_patterns(tmp_path / "nonexistent.yml")


def test_load_subdomain_patterns_bad_format_raises(tmp_path: Path) -> None:
    patterns_file = tmp_path / "bad.yml"
    patterns_file.write_text("[a, b, c]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_subdomain_patterns(patterns_file)


def test_load_subdomain_patterns_non_list_category_raises(tmp_path: Path) -> None:
    patterns_file = tmp_path / "bad.yml"
    patterns_file.write_text(yaml.dump({"academic": "law"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_subdomain_patterns(patterns_file)


# ---------------------------------------------------------------------------
# _extract_apex_domains_from_toon
# ---------------------------------------------------------------------------


def test_extract_apex_domains_returns_only_apex() -> None:
    toon = _make_toon(
        [
            _make_domain_entry("mit.edu"),
            _make_domain_entry("library.mit.edu"),  # subdomain — should be excluded
            _make_domain_entry("harvard.edu"),
        ]
    )

    apex = _extract_apex_domains_from_toon(toon)

    apex_set = set(apex)
    assert apex_set == {"mit.edu", "harvard.edu"}
    assert "library.mit.edu" not in apex_set


def test_extract_apex_domains_deduplicates() -> None:
    toon = _make_toon(
        [
            _make_domain_entry("mit.edu"),
            _make_domain_entry("mit.edu"),
        ]
    )

    apex = _extract_apex_domains_from_toon(toon)

    assert apex.count("mit.edu") == 1


def test_extract_apex_domains_empty_toon() -> None:
    assert _extract_apex_domains_from_toon({"domains": []}) == []


# ---------------------------------------------------------------------------
# _existing_urls_for_domain
# ---------------------------------------------------------------------------


def test_existing_urls_returns_page_urls() -> None:
    entry = _make_domain_entry(
        "mit.edu",
        pages=[
            {"url": "https://mit.edu/", "is_root_page": True},
            {"url": "https://mit.edu/accessibility", "is_root_page": False},
        ],
    )

    urls = _existing_urls_for_domain(entry)

    assert urls == {"https://mit.edu/", "https://mit.edu/accessibility"}


def test_existing_urls_empty_pages() -> None:
    assert _existing_urls_for_domain(_make_domain_entry("mit.edu")) == set()


# ---------------------------------------------------------------------------
# _make_candidate_url
# ---------------------------------------------------------------------------


def test_make_candidate_url_builds_https_root() -> None:
    subdomain, url = _make_candidate_url("library", "mit.edu")

    assert subdomain == "library.mit.edu"
    assert url == "https://library.mit.edu/"


# ---------------------------------------------------------------------------
# SubdomainScanner.scan_domain
# ---------------------------------------------------------------------------


def _mock_validator_results(results_map: dict[str, ValidationResult]) -> AsyncMock:
    """Return an AsyncMock for validate_urls_batch that yields *results_map*.

    Args:
        results_map: Mapping from URL to ``ValidationResult``.  The mock
            returns this dict regardless of what URLs are passed to it.

    Returns:
        ``AsyncMock`` suitable for patching ``UrlValidator.validate_urls_batch``.
    """
    mock = AsyncMock(return_value=results_map)
    return mock


@pytest.mark.asyncio
async def test_scan_domain_returns_valid_results() -> None:
    scanner = SubdomainScanner()
    valid_result = ValidationResult(
        url="https://library.mit.edu/",
        is_valid=True,
        status_code=200,
        validated_at="2024-01-01T00:00:00+00:00",
    )
    invalid_result = ValidationResult(
        url="https://law.mit.edu/",
        is_valid=False,
        status_code=404,
    )

    with patch.object(
        scanner._validator,
        "validate_urls_batch",
        new=_mock_validator_results(
            {
                "https://library.mit.edu/": valid_result,
                "https://law.mit.edu/": invalid_result,
            }
        ),
    ):
        results, probed = await scanner.scan_domain(
            apex_domain="mit.edu",
            prefixes=["library", "law"],
            existing_urls=set(),
        )

    assert probed == 2
    assert len(results) == 1
    assert results[0].subdomain == "library.mit.edu"
    assert results[0].is_valid is True


@pytest.mark.asyncio
async def test_scan_domain_skips_existing_urls() -> None:
    """Prefixes whose URL already exists in the TOON are not probed."""
    scanner = SubdomainScanner()

    mock_batch = AsyncMock(return_value={})
    with patch.object(scanner._validator, "validate_urls_batch", new=mock_batch):
        results, probed = await scanner.scan_domain(
            apex_domain="mit.edu",
            prefixes=["library"],
            existing_urls={"https://library.mit.edu/"},
        )

    # No network request should be made because the URL already exists.
    mock_batch.assert_not_called()
    assert results == []
    assert probed == 0


@pytest.mark.asyncio
async def test_scan_domain_records_redirect_target() -> None:
    """When a candidate redirects, redirected_to is captured."""
    scanner = SubdomainScanner()
    redirect_result = ValidationResult(
        url="https://admissions.mit.edu/",
        is_valid=True,
        status_code=301,
        redirected_to="https://mit.edu/admissions/",
        validated_at="2024-01-01T00:00:00+00:00",
    )

    with patch.object(
        scanner._validator,
        "validate_urls_batch",
        new=_mock_validator_results({"https://admissions.mit.edu/": redirect_result}),
    ):
        results, probed = await scanner.scan_domain(
            apex_domain="mit.edu",
            prefixes=["admissions"],
            existing_urls=set(),
        )

    assert probed == 1
    assert len(results) == 1
    assert results[0].redirected_to == "https://mit.edu/admissions/"


@pytest.mark.asyncio
async def test_scan_domain_skips_duplicate_redirect_target() -> None:
    """Redirect targets that already exist in the TOON are not added again."""
    scanner = SubdomainScanner()
    redirect_result = ValidationResult(
        url="https://admissions.mit.edu/",
        is_valid=True,
        status_code=301,
        redirected_to="https://mit.edu/admissions/",
        validated_at="2024-01-01T00:00:00+00:00",
    )

    with patch.object(
        scanner._validator,
        "validate_urls_batch",
        new=_mock_validator_results({"https://admissions.mit.edu/": redirect_result}),
    ):
        results, probed = await scanner.scan_domain(
            apex_domain="mit.edu",
            prefixes=["admissions"],
            # The redirect target is already recorded — should be skipped.
            existing_urls={"https://mit.edu/admissions/"},
        )

    assert probed == 1
    assert results == []


# ---------------------------------------------------------------------------
# SubdomainScanner.scan_toon
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_toon_updates_domain_entry_in_place() -> None:
    """scan_toon appends new page entries to the apex TOON domain dict."""
    toon = _make_toon([_make_domain_entry("mit.edu", pages=[{"url": "https://mit.edu/", "is_root_page": True}])])

    scanner = SubdomainScanner()
    valid_result = ValidationResult(
        url="https://library.mit.edu/",
        is_valid=True,
        status_code=200,
        validated_at="2024-01-01T00:00:00+00:00",
    )

    with patch.object(
        scanner._validator,
        "validate_urls_batch",
        new=_mock_validator_results({"https://library.mit.edu/": valid_result}),
    ):
        stats = await scanner.scan_toon(toon, prefixes=["library"])

    assert stats.valid_found == 1
    # The apex domain entry should now have two pages.
    apex_pages = toon["domains"][0]["pages"]
    assert len(apex_pages) == 2
    new_page = apex_pages[1]
    assert new_page["url"] == "https://library.mit.edu/"
    assert new_page["discovered_via"] == "subdomain-scan"
    assert new_page["is_root_page"] is False


@pytest.mark.asyncio
async def test_scan_toon_adds_subdomain_domain_entry() -> None:
    """scan_toon creates a new domain entry for each discovered subdomain."""
    toon = _make_toon([_make_domain_entry("mit.edu", pages=[{"url": "https://mit.edu/", "is_root_page": True}])])

    scanner = SubdomainScanner()
    valid_result = ValidationResult(
        url="https://library.mit.edu/",
        is_valid=True,
        status_code=200,
        validated_at="2024-01-01T00:00:00+00:00",
    )

    with patch.object(
        scanner._validator,
        "validate_urls_batch",
        new=_mock_validator_results({"https://library.mit.edu/": valid_result}),
    ):
        stats = await scanner.scan_toon(toon, prefixes=["library"])

    assert stats.valid_found == 1
    # A new domain entry for the subdomain should have been appended.
    all_canonical = [d["canonical_domain"] for d in toon["domains"]]
    assert "library.mit.edu" in all_canonical

    subdomain_entry = next(d for d in toon["domains"] if d["canonical_domain"] == "library.mit.edu")
    assert subdomain_entry["is_subdomain"] is True
    assert subdomain_entry["parent_domain"] == "mit.edu"
    assert subdomain_entry["subdomain_prefix"] == "library"
    assert len(subdomain_entry["pages"]) == 1
    assert subdomain_entry["pages"][0]["url"] == "https://library.mit.edu/"


@pytest.mark.asyncio
async def test_scan_toon_no_duplicate_domain_entry_on_rerun() -> None:
    """scan_toon skips adding a domain entry that already exists as a canonical_domain."""
    # Pre-populate the TOON with a subdomain domain entry (simulates a previous scan).
    toon = _make_toon([
        _make_domain_entry("mit.edu", pages=[
            {"url": "https://mit.edu/", "is_root_page": True},
            # The subdomain URL is also recorded as a page under the apex.
            {
                "url": "https://library.mit.edu/",
                "is_root_page": False,
                "discovered_via": "subdomain-scan",
            },
        ]),
        {
            "canonical_domain": "library.mit.edu",
            "is_subdomain": True,
            "parent_domain": "mit.edu",
            "pages": [{"url": "https://library.mit.edu/", "is_root_page": True}],
        },
    ])

    scanner = SubdomainScanner()
    mock_batch = AsyncMock(return_value={})
    with patch.object(scanner._validator, "validate_urls_batch", new=mock_batch):
        stats = await scanner.scan_toon(toon, prefixes=["library"])

    # The URL is already in the apex domain's pages list, so no request is made.
    mock_batch.assert_not_called()
    assert stats.valid_found == 0
    # Domain list is unchanged — no duplicate entry appended.
    assert len(toon["domains"]) == 2


@pytest.mark.asyncio
async def test_scan_toon_respects_max_domains() -> None:
    """max_domains limits which apex domains are probed."""
    toon = _make_toon(
        [
            _make_domain_entry("mit.edu"),
            _make_domain_entry("harvard.edu"),
        ]
    )

    scanner = SubdomainScanner()
    call_args_log: list[list[str]] = []

    async def capture_batch(urls, **kwargs):
        call_args_log.append(list(urls))
        return {}

    with patch.object(scanner._validator, "validate_urls_batch", side_effect=capture_batch):
        stats = await scanner.scan_toon(toon, prefixes=["library"], max_domains=1)

    assert stats.domains_scanned == 1
    # Only mit.edu (first apex domain) should have been scanned.
    all_urls = [url for batch in call_args_log for url in batch]
    assert all(urlparse(url).hostname == "library.mit.edu" for url in all_urls)
    assert not any(urlparse(url).hostname == "library.harvard.edu" for url in all_urls)


@pytest.mark.asyncio
async def test_scan_toon_respects_start_offset() -> None:
    """start_offset skips the first N apex domains."""
    toon = _make_toon(
        [
            _make_domain_entry("mit.edu"),
            _make_domain_entry("harvard.edu"),
            _make_domain_entry("stanford.edu"),
        ]
    )

    scanner = SubdomainScanner()
    call_args_log: list[list[str]] = []

    async def capture_batch(urls, **kwargs):
        call_args_log.append(list(urls))
        return {}

    with patch.object(scanner._validator, "validate_urls_batch", side_effect=capture_batch):
        # Skip the first domain (mit.edu), scan the remaining two.
        stats = await scanner.scan_toon(toon, prefixes=["library"], start_offset=1)

    assert stats.domains_scanned == 2
    all_urls = [url for batch in call_args_log for url in batch]
    assert not any(urlparse(url).hostname == "library.mit.edu" for url in all_urls)
    assert any(urlparse(url).hostname == "library.harvard.edu" for url in all_urls)
    assert any(urlparse(url).hostname == "library.stanford.edu" for url in all_urls)


@pytest.mark.asyncio
async def test_scan_toon_offset_plus_max_domains() -> None:
    """start_offset and max_domains together select a slice of domains."""
    toon = _make_toon(
        [
            _make_domain_entry("mit.edu"),
            _make_domain_entry("harvard.edu"),
            _make_domain_entry("stanford.edu"),
            _make_domain_entry("yale.edu"),
        ]
    )

    scanner = SubdomainScanner()
    scanned_hostnames: set[str] = set()

    async def capture_batch(urls, **kwargs):
        for url in urls:
            scanned_hostnames.add(urlparse(url).hostname)
        return {}

    with patch.object(scanner._validator, "validate_urls_batch", side_effect=capture_batch):
        # Offset 1, max 2 → should scan harvard.edu and stanford.edu only.
        stats = await scanner.scan_toon(
            toon, prefixes=["library"], start_offset=1, max_domains=2
        )

    assert stats.domains_scanned == 2
    assert scanned_hostnames == {"library.harvard.edu", "library.stanford.edu"}


@pytest.mark.asyncio
async def test_scan_toon_concurrency_limit_processes_all_domains() -> None:
    """concurrency_limit > 1 scans all domains and produces the same results."""
    toon = _make_toon(
        [
            _make_domain_entry("mit.edu"),
            _make_domain_entry("harvard.edu"),
        ]
    )

    scanner = SubdomainScanner()
    valid_result_mit = ValidationResult(
        url="https://library.mit.edu/",
        is_valid=True,
        status_code=200,
        validated_at="2024-01-01T00:00:00+00:00",
    )
    valid_result_harvard = ValidationResult(
        url="https://library.harvard.edu/",
        is_valid=True,
        status_code=200,
        validated_at="2024-01-01T00:00:00+00:00",
    )

    async def mock_batch(urls, **kwargs):
        results = {}
        for url in urls:
            hostname = urlparse(url).hostname or ""
            if hostname.endswith(".mit.edu"):
                results[url] = valid_result_mit
            elif hostname.endswith(".harvard.edu"):
                results[url] = valid_result_harvard
        return results

    with patch.object(scanner._validator, "validate_urls_batch", side_effect=mock_batch):
        stats = await scanner.scan_toon(
            toon, prefixes=["library"], concurrency_limit=2
        )

    assert stats.domains_scanned == 2
    assert stats.valid_found == 2
    all_canonical = [d["canonical_domain"] for d in toon["domains"]]
    assert "library.mit.edu" in all_canonical
    assert "library.harvard.edu" in all_canonical


@pytest.mark.asyncio
async def test_scan_toon_on_progress_callback_called() -> None:
    """on_progress is called once per domain with correct counters."""
    toon = _make_toon(
        [
            _make_domain_entry("mit.edu"),
            _make_domain_entry("harvard.edu"),
        ]
    )

    scanner = SubdomainScanner()
    progress_calls: list[tuple[int, int]] = []

    def record_progress(completed: int, total: int) -> None:
        progress_calls.append((completed, total))

    mock_batch = AsyncMock(return_value={})
    with patch.object(scanner._validator, "validate_urls_batch", new=mock_batch):
        await scanner.scan_toon(
            toon, prefixes=["library"], on_progress=record_progress
        )

    assert len(progress_calls) == 2
    totals = {t for _, t in progress_calls}
    assert totals == {2}
    completed_values = sorted(c for c, _ in progress_calls)
    assert completed_values == [1, 2]


@pytest.mark.asyncio
async def test_scan_toon_stats_counts_redirects() -> None:
    toon = _make_toon([_make_domain_entry("mit.edu")])

    scanner = SubdomainScanner()
    redirect_result = ValidationResult(
        url="https://library.mit.edu/",
        is_valid=True,
        status_code=301,
        redirected_to="https://mit.edu/libraries/",
        validated_at="2024-01-01T00:00:00+00:00",
    )

    with patch.object(
        scanner._validator,
        "validate_urls_batch",
        new=_mock_validator_results({"https://library.mit.edu/": redirect_result}),
    ):
        stats = await scanner.scan_toon(toon, prefixes=["library"])

    assert stats.redirected == 1
    assert stats.valid_found == 1
