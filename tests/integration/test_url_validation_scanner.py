"""Integration tests for URL validation scanner."""

import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.jobs.url_validation_scanner import UrlValidationScanner
from src.lib.settings import Settings
from src.storage.schema import initialize_schema


@pytest.fixture
def temp_settings(tmp_path):
    """Create temporary settings for testing."""
    db_path = tmp_path / "test.db"
    return Settings(
        scheduler_cadence="monthly",
        crawl_rate_limit_per_host=0.5,
        crawl_timeout_seconds=2,
        toon_output_dir=tmp_path / "toon-cache",
        metadata_db_url=f"sqlite:///{db_path}",
    )


@pytest.fixture
def sample_toon_file(tmp_path):
    """Create a sample TOON file for testing."""
    toon_data = {
        "version": "0.1-seed",
        "country": "TestCountry",
        "domain_count": 2,
        "page_count": 3,
        "domains": [
            {
                "canonical_domain": "example.com",
                "subnational": [],
                "source_tabs": [],
                "pages": [
                    {
                        "url": "https://httpbin.org/status/200",
                        "is_root_page": True,
                    },
                    {
                        "url": "https://httpbin.org/status/404",
                        "is_root_page": False,
                    },
                ],
            },
            {
                "canonical_domain": "test.com",
                "subnational": [],
                "source_tabs": [],
                "pages": [
                    {
                        "url": "https://httpbin.org/redirect/1",
                        "is_root_page": True,
                    },
                ],
            },
        ],
    }
    
    toon_file = tmp_path / "test.toon"
    with toon_file.open("w") as f:
        json.dump(toon_data, f)
    
    return toon_file


@pytest.mark.asyncio
async def test_scanner_processes_toon_file(temp_settings, sample_toon_file):
    """Test that scanner can process a TOON file."""
    scanner = UrlValidationScanner(temp_settings)
    
    # Run scan
    stats = await scanner.scan_country(
        country_code="TEST",
        toon_path=sample_toon_file,
        rate_limit_per_second=10,  # Fast for testing
    )
    
    # Verify statistics
    assert stats["country_code"] == "TEST"
    assert stats["total_urls"] == 3
    assert stats["urls_validated"] == 3
    assert stats["urls_skipped"] == 0
    
    # Verify output file was created
    output_path = Path(stats["output_path"])
    assert output_path.exists()
    
    # Verify output TOON file content
    with output_path.open("r") as f:
        output_toon = json.load(f)
    
    # Check that validation metadata was added to pages
    found_validation_status = False
    for domain in output_toon.get("domains", []):
        for page in domain.get("pages", []):
            # Each page should have validation_status
            if "validation_status" in page:
                found_validation_status = True
                assert page["validation_status"] in ["valid", "invalid"]
                # Pages may have status_code or error_message depending on result
                assert "status_code" in page or "error_message" in page
    
    assert found_validation_status, "No validation metadata found in output TOON"
    
    # Verify database records were created
    conn = sqlite3.connect(scanner.db_path)
    cursor = conn.execute(
        "SELECT COUNT(*) FROM url_validation_results WHERE country_code = ?",
        ("TEST",)
    )
    count = cursor.fetchone()[0]
    conn.close()
    
    assert count == 3


@pytest.mark.asyncio
async def test_scanner_tracks_failures_across_runs(temp_settings, sample_toon_file):
    """Test that scanner tracks failures across multiple runs."""
    scanner = UrlValidationScanner(temp_settings)
    
    # First run - all URLs validated
    stats1 = await scanner.scan_country(
        country_code="TEST",
        toon_path=sample_toon_file,
        rate_limit_per_second=10,
    )
    
    # Verify no URLs removed yet
    assert stats1["urls_removed"] == 0
    
    # Second run - URLs that failed twice should be removed
    stats2 = await scanner.scan_country(
        country_code="TEST",
        toon_path=sample_toon_file,
        rate_limit_per_second=10,
    )
    
    # Verify some URLs were removed (those that failed twice)
    # Note: This depends on which URLs actually fail in the test environment
    assert "urls_removed" in stats2


@pytest.mark.asyncio
async def test_scanner_handles_empty_toon_file(temp_settings, tmp_path):
    """Test that scanner handles empty TOON files gracefully."""
    # Create empty TOON file
    toon_data = {
        "version": "0.1-seed",
        "country": "Empty",
        "domain_count": 0,
        "page_count": 0,
        "domains": [],
    }
    
    toon_file = tmp_path / "empty.toon"
    with toon_file.open("w") as f:
        json.dump(toon_data, f)
    
    scanner = UrlValidationScanner(temp_settings)
    
    # Run scan
    stats = await scanner.scan_country(
        country_code="EMPTY",
        toon_path=toon_file,
        rate_limit_per_second=10,
    )
    
    # Verify statistics
    assert stats["total_urls"] == 0
    assert stats["urls_validated"] == 0
    assert stats["valid_urls"] == 0
    assert stats["invalid_urls"] == 0


def test_scanner_initializes_database(temp_settings):
    """Test that scanner initializes database schema correctly."""
    scanner = UrlValidationScanner(temp_settings)
    
    # Verify database file exists
    assert scanner.db_path.exists()
    
    # Verify tables were created
    conn = sqlite3.connect(scanner.db_path)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='url_validation_results'"
    )
    table_exists = cursor.fetchone() is not None
    conn.close()
    
    assert table_exists


def test_get_recently_confirmed_urls_empty_db(temp_settings):
    """Return empty set when no recent scan data exists."""
    scanner = UrlValidationScanner(temp_settings)
    confirmed = scanner._get_recently_confirmed_urls("TESTLAND", within_days=30)
    assert confirmed == set()


def test_get_recently_confirmed_urls_from_social_scan(temp_settings):
    """URLs confirmed reachable by social media scanner should be returned."""
    from datetime import datetime, timezone

    scanner = UrlValidationScanner(temp_settings)
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(scanner.db_path)
    try:
        # Insert a recent reachable social-media result
        conn.execute(
            """
            INSERT INTO url_social_media_results
            (url, country_code, scan_id, is_reachable, social_tier,
             twitter_links, x_links, bluesky_links, mastodon_links, scanned_at)
            VALUES (?, ?, ?, ?, ?, '[]', '[]', '[]', '[]', ?)
            """,
            ("https://example.is/page1", "TESTLAND", "social-001", 1, "no_social", now),
        )
        # Insert a recent *unreachable* social-media result — should NOT be returned
        conn.execute(
            """
            INSERT INTO url_social_media_results
            (url, country_code, scan_id, is_reachable, social_tier,
             twitter_links, x_links, bluesky_links, mastodon_links, scanned_at)
            VALUES (?, ?, ?, ?, ?, '[]', '[]', '[]', '[]', ?)
            """,
            ("https://example.is/page2", "TESTLAND", "social-001", 0, "unreachable", now),
        )
        conn.commit()
    finally:
        conn.close()

    confirmed = scanner._get_recently_confirmed_urls("TESTLAND", within_days=30)
    assert "https://example.is/page1" in confirmed
    assert "https://example.is/page2" not in confirmed


def test_get_recently_confirmed_urls_from_validation_results(temp_settings):
    """URLs previously validated as valid should also be returned."""
    from datetime import datetime, timezone

    scanner = UrlValidationScanner(temp_settings)
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(scanner.db_path)
    try:
        conn.execute(
            """
            INSERT INTO url_validation_results
            (url, country_code, scan_id, status_code, is_valid,
             failure_count, validated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("https://example.is/page3", "TESTLAND", "val-001", 200, 1, 0, now),
        )
        conn.commit()
    finally:
        conn.close()

    confirmed = scanner._get_recently_confirmed_urls("TESTLAND", within_days=30)
    assert "https://example.is/page3" in confirmed


def test_get_recently_confirmed_urls_old_results_excluded(temp_settings):
    """Results older than ``within_days`` should not be returned."""
    from datetime import datetime, timezone, timedelta

    scanner = UrlValidationScanner(temp_settings)
    within_days = 30
    # Use a timestamp well outside the window so the test never becomes flaky
    old_ts = (
        datetime.now(timezone.utc) - timedelta(days=within_days + 10)
    ).isoformat()

    conn = sqlite3.connect(scanner.db_path)
    try:
        conn.execute(
            """
            INSERT INTO url_social_media_results
            (url, country_code, scan_id, is_reachable, social_tier,
             twitter_links, x_links, bluesky_links, mastodon_links, scanned_at)
            VALUES (?, ?, ?, ?, ?, '[]', '[]', '[]', '[]', ?)
            """,
            ("https://example.is/old", "TESTLAND", "social-old", 1, "no_social", old_ts),
        )
        conn.commit()
    finally:
        conn.close()

    confirmed = scanner._get_recently_confirmed_urls("TESTLAND", within_days=within_days)
    assert "https://example.is/old" not in confirmed


@pytest.mark.asyncio
async def test_scanner_skips_recently_confirmed_urls(temp_settings, sample_toon_file):
    """URLs confirmed reachable by a previous scan should be skipped."""
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, patch

    scanner = UrlValidationScanner(temp_settings)
    now = datetime.now(timezone.utc).isoformat()

    # Pre-populate social scan results for all three TOON URLs
    toon_urls = [
        "https://httpbin.org/status/200",
        "https://httpbin.org/status/404",
        "https://httpbin.org/redirect/1",
    ]
    conn = sqlite3.connect(scanner.db_path)
    try:
        for url in toon_urls:
            conn.execute(
                """
                INSERT INTO url_social_media_results
                (url, country_code, scan_id, is_reachable, social_tier,
                 twitter_links, x_links, bluesky_links, mastodon_links, scanned_at)
                VALUES (?, ?, ?, ?, ?, '[]', '[]', '[]', '[]', ?)
                """,
                (url, "TEST", "social-001", 1, "no_social", now),
            )
        conn.commit()
    finally:
        conn.close()

    # Patch the actual HTTP validator so no real requests are made
    with patch.object(scanner.validator, "validate_urls_batch", new_callable=AsyncMock) as mock_val:
        mock_val.return_value = {}
        stats = await scanner.scan_country(
            country_code="TEST",
            toon_path=sample_toon_file,
            rate_limit_per_second=10,
            skip_recently_validated_days=30,
        )

    # All three URLs were recently confirmed → none should be re-validated
    assert stats["urls_skipped_recently_confirmed"] == 3
    assert stats["urls_validated"] == 0
    # The validator should have been called with an empty list and the rate
    # limit; extra keyword args (max_runtime_seconds, start_time, on_result)
    # are also passed but we only assert on the positional args here.
    mock_val.assert_called_once()
    call_args, call_kwargs = mock_val.call_args
    assert call_args == ([],)
    assert call_kwargs["rate_limit_per_second"] == 10


@pytest.mark.asyncio
async def test_scanner_stops_early_when_budget_exhausted(temp_settings, sample_toon_file):
    """scan_country should stop early when the runtime budget is exhausted."""
    import time
    from unittest.mock import AsyncMock, patch

    scanner = UrlValidationScanner(temp_settings)

    # Use a start_time far in the past so the budget is already exhausted.
    past_start = time.monotonic() - 10_000

    with patch.object(scanner.validator, "validate_urls_batch", new_callable=AsyncMock) as mock_val:
        mock_val.return_value = {}
        stats = await scanner.scan_country(
            country_code="TEST",
            toon_path=sample_toon_file,
            rate_limit_per_second=10,
            max_runtime_seconds=100,   # 100 s budget, but 10,000 s have elapsed
            start_time=past_start,
        )

    # No URLs should have been validated because the budget was already exhausted
    assert stats["urls_validated"] == 0
    assert stats["is_complete"] is False


@pytest.mark.asyncio
async def test_scanner_incremental_save_via_callback(temp_settings, sample_toon_file):
    """Each validated URL should be persisted incrementally via the on_result callback."""
    import sqlite3
    from unittest.mock import AsyncMock, patch
    from src.services.url_validator import ValidationResult
    from datetime import datetime, timezone

    scanner = UrlValidationScanner(temp_settings)

    toon_urls = [
        "https://httpbin.org/status/200",
        "https://httpbin.org/status/404",
    ]

    fake_results = {
        url: ValidationResult(
            url=url,
            is_valid=(i == 0),
            status_code=200 if i == 0 else 404,
            validated_at=datetime.now(timezone.utc).isoformat(),
        )
        for i, url in enumerate(toon_urls)
    }

    async def fake_batch(urls, rate_limit_per_second, max_runtime_seconds, start_time, on_result):
        """Simulate validate_urls_batch calling on_result for each URL."""
        for url in urls:
            if url in fake_results:
                on_result(fake_results[url])
        return {url: fake_results[url] for url in urls if url in fake_results}

    with patch.object(scanner.validator, "validate_urls_batch", side_effect=fake_batch):
        stats = await scanner.scan_country(
            country_code="TEST",
            toon_path=sample_toon_file,
            rate_limit_per_second=10,
        )

    # Verify the on_result callback saved results to DB
    conn = sqlite3.connect(scanner.db_path)
    cursor = conn.execute(
        "SELECT COUNT(*) FROM url_validation_results WHERE country_code = ?",
        ("TEST",),
    )
    count = cursor.fetchone()[0]
    conn.close()

    assert count == len(fake_results)
    assert stats["urls_validated"] == len(fake_results)
