"""Integration tests for skip-recently-scanned-days in social media and tech scanner jobs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.jobs.accessibility_scanner import AccessibilityScannerJob
from src.jobs.social_media_scanner import SocialMediaScannerJob
from src.jobs.tech_scanner import TechScanner
from src.lib.settings import Settings
from src.services.social_media_scanner import SOCIAL_PLATFORMS_VERSION, SocialMediaScanResult
from src.services.tech_detector import TechDetectionResult
from src.storage.schema import initialize_schema


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_settings(tmp_path: Path) -> Settings:
    """Settings backed by a temporary database."""
    db_path = tmp_path / "test.db"
    return Settings(
        scheduler_cadence="monthly",
        crawl_rate_limit_per_host=0.5,
        crawl_timeout_seconds=2,
        toon_output_dir=tmp_path / "toon-cache",
        metadata_db_url=f"sqlite:///{db_path}",
    )


@pytest.fixture
def sample_toon_file(tmp_path: Path) -> Path:
    """Minimal TOON file with three page URLs."""
    toon_data = {
        "version": "0.1-seed",
        "country": "TestLand",
        "domains": [
            {
                "canonical_domain": "example.test",
                "pages": [
                    {"url": "https://example.test/page1"},
                    {"url": "https://example.test/page2"},
                    {"url": "https://example.test/page3"},
                ],
            }
        ],
    }
    toon_path = tmp_path / "testland.toon"
    toon_path.write_text(json.dumps(toon_data), encoding="utf-8")
    return toon_path


# ---------------------------------------------------------------------------
# SocialMediaScannerJob._get_recently_scanned_urls
# ---------------------------------------------------------------------------

def test_social_get_recently_scanned_empty_db(temp_settings):
    """Returns empty set when the database has no records."""
    job = SocialMediaScannerJob(temp_settings)
    result = job._get_recently_scanned_urls("TESTLAND", within_days=7)
    assert result == set()


def test_social_get_recently_scanned_returns_recent_urls(temp_settings):
    """URLs scanned within the window are returned."""
    job = SocialMediaScannerJob(temp_settings)
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(job.db_path)
    try:
        conn.execute(
            """
            INSERT INTO url_social_media_results
            (url, country_code, scan_id, is_reachable, social_tier,
             twitter_links, x_links, bluesky_links, mastodon_links,
             platforms_version, scanned_at)
            VALUES (?, ?, ?, ?, ?, '[]', '[]', '[]', '[]', ?, ?)
            """,
            ("https://example.test/page1", "TESTLAND", "s-001", 1, "no_social",
             SOCIAL_PLATFORMS_VERSION, now),
        )
        conn.commit()
    finally:
        conn.close()

    result = job._get_recently_scanned_urls("TESTLAND", within_days=7)
    assert "https://example.test/page1" in result


def test_social_get_recently_scanned_excludes_old_results(temp_settings):
    """URLs scanned outside the window are not returned."""
    job = SocialMediaScannerJob(temp_settings)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    conn = sqlite3.connect(job.db_path)
    try:
        conn.execute(
            """
            INSERT INTO url_social_media_results
            (url, country_code, scan_id, is_reachable, social_tier,
             twitter_links, x_links, bluesky_links, mastodon_links,
             platforms_version, scanned_at)
            VALUES (?, ?, ?, ?, ?, '[]', '[]', '[]', '[]', ?, ?)
            """,
            ("https://example.test/old", "TESTLAND", "s-old", 1, "no_social",
             SOCIAL_PLATFORMS_VERSION, old_ts),
        )
        conn.commit()
    finally:
        conn.close()

    result = job._get_recently_scanned_urls("TESTLAND", within_days=7)
    assert "https://example.test/old" not in result


def test_social_get_recently_scanned_excludes_other_countries(temp_settings):
    """URLs for a different country are not returned."""
    job = SocialMediaScannerJob(temp_settings)
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(job.db_path)
    try:
        conn.execute(
            """
            INSERT INTO url_social_media_results
            (url, country_code, scan_id, is_reachable, social_tier,
             twitter_links, x_links, bluesky_links, mastodon_links,
             platforms_version, scanned_at)
            VALUES (?, ?, ?, ?, ?, '[]', '[]', '[]', '[]', ?, ?)
            """,
            ("https://example.fr/page1", "FRANCE", "s-001", 1, "no_social",
             SOCIAL_PLATFORMS_VERSION, now),
        )
        conn.commit()
    finally:
        conn.close()

    result = job._get_recently_scanned_urls("TESTLAND", within_days=7)
    assert result == set()


def test_social_get_recently_scanned_excludes_old_platform_version(temp_settings):
    """URLs scanned with an older platforms_version are not considered recently scanned.

    This ensures that when a new social-media platform is added (and
    SOCIAL_PLATFORMS_VERSION is bumped), previously-scanned URLs are
    re-processed to collect data for the new platform rather than being
    silently skipped.
    """
    job = SocialMediaScannerJob(temp_settings)
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(job.db_path)
    try:
        conn.execute(
            """
            INSERT INTO url_social_media_results
            (url, country_code, scan_id, is_reachable, social_tier,
             twitter_links, x_links, bluesky_links, mastodon_links,
             platforms_version, scanned_at)
            VALUES (?, ?, ?, ?, ?, '[]', '[]', '[]', '[]', ?, ?)
            """,
            # platforms_version = 0 simulates a pre-Facebook/LinkedIn scan row
            ("https://example.test/old-platform", "TESTLAND", "s-v0",
             1, "no_social", 0, now),
        )
        conn.commit()
    finally:
        conn.close()

    result = job._get_recently_scanned_urls("TESTLAND", within_days=7)
    assert "https://example.test/old-platform" not in result, (
        "URLs scanned with an outdated platforms_version should not be "
        "treated as recently scanned — they need a re-scan."
    )


@pytest.mark.asyncio
async def test_social_scan_country_skips_recently_scanned_urls(
    temp_settings, sample_toon_file
):
    """scan_country skips URLs already in the recent-scan window."""
    job = SocialMediaScannerJob(temp_settings)
    now = datetime.now(timezone.utc).isoformat()

    # Pre-populate page1 and page2 as recently scanned
    conn = sqlite3.connect(job.db_path)
    try:
        for url in ["https://example.test/page1", "https://example.test/page2"]:
            conn.execute(
                """
                INSERT INTO url_social_media_results
                (url, country_code, scan_id, is_reachable, social_tier,
                 twitter_links, x_links, bluesky_links, mastodon_links,
                 platforms_version, scanned_at)
                VALUES (?, ?, ?, ?, ?, '[]', '[]', '[]', '[]', ?, ?)
                """,
                (url, "TESTLAND", "s-prev", 1, "no_social", SOCIAL_PLATFORMS_VERSION, now),
            )
        conn.commit()
    finally:
        conn.close()

    scan_results: list[str] = []

    mock_result = SocialMediaScanResult(
        url="https://example.test/page3",
        is_reachable=True,
        social_tier="no_social",
    )

    async def _fake_scan_batch(urls, **kwargs):
        scan_results.extend(urls)
        on_result = kwargs.get("on_result")
        for url in urls:
            r = SocialMediaScanResult(url=url, is_reachable=True, social_tier="no_social")
            if on_result:
                on_result(r)
        return {u: SocialMediaScanResult(url=u, is_reachable=True, social_tier="no_social") for u in urls}

    with patch.object(job.scanner, "scan_urls_batch", side_effect=_fake_scan_batch):
        stats = await job.scan_country(
            "TESTLAND",
            sample_toon_file,
            skip_recently_scanned_days=7,
        )

    # Only page3 should have been submitted to the scanner
    assert scan_results == ["https://example.test/page3"]
    assert stats["urls_scanned"] == 1
    assert stats["urls_skipped_recently_scanned"] == 2
    assert stats["total_urls"] == 3


@pytest.mark.asyncio
async def test_social_scan_country_all_recently_scanned_skips_scan(
    temp_settings, sample_toon_file
):
    """When all URLs are recently scanned scan_country returns immediately."""
    job = SocialMediaScannerJob(temp_settings)
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(job.db_path)
    try:
        for url in [
            "https://example.test/page1",
            "https://example.test/page2",
            "https://example.test/page3",
        ]:
            conn.execute(
                """
                INSERT INTO url_social_media_results
                (url, country_code, scan_id, is_reachable, social_tier,
                 twitter_links, x_links, bluesky_links, mastodon_links,
                 platforms_version, scanned_at)
                VALUES (?, ?, ?, ?, ?, '[]', '[]', '[]', '[]', ?, ?)
                """,
                (url, "TESTLAND", "s-prev", 1, "no_social", SOCIAL_PLATFORMS_VERSION, now),
            )
        conn.commit()
    finally:
        conn.close()

    with patch.object(job.scanner, "scan_urls_batch", new_callable=AsyncMock) as mock_scan:
        stats = await job.scan_country(
            "TESTLAND",
            sample_toon_file,
            skip_recently_scanned_days=7,
        )

    mock_scan.assert_not_called()
    assert stats["urls_scanned"] == 0
    assert stats["urls_skipped_recently_scanned"] == 3
    assert stats["is_complete"] is True


# ---------------------------------------------------------------------------
# TechScanner._get_recently_scanned_urls
# ---------------------------------------------------------------------------

def test_tech_get_recently_scanned_empty_db(temp_settings):
    """Returns empty set when the database has no records."""
    scanner = TechScanner(temp_settings)
    result = scanner._get_recently_scanned_urls("TESTLAND", within_days=7)
    assert result == set()


def test_tech_get_recently_scanned_returns_recent_urls(temp_settings):
    """URLs scanned within the window are returned."""
    scanner = TechScanner(temp_settings)
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(scanner.db_path)
    try:
        conn.execute(
            """
            INSERT INTO url_tech_results
            (url, country_code, scan_id, technologies, scanned_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("https://example.test/page1", "TESTLAND", "t-001", "{}", now),
        )
        conn.commit()
    finally:
        conn.close()

    result = scanner._get_recently_scanned_urls("TESTLAND", within_days=7)
    assert "https://example.test/page1" in result


def test_tech_get_recently_scanned_excludes_old_results(temp_settings):
    """URLs scanned outside the window are not returned."""
    scanner = TechScanner(temp_settings)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    conn = sqlite3.connect(scanner.db_path)
    try:
        conn.execute(
            """
            INSERT INTO url_tech_results
            (url, country_code, scan_id, technologies, scanned_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("https://example.test/old", "TESTLAND", "t-old", "{}", old_ts),
        )
        conn.commit()
    finally:
        conn.close()

    result = scanner._get_recently_scanned_urls("TESTLAND", within_days=7)
    assert "https://example.test/old" not in result


@pytest.mark.asyncio
async def test_tech_scan_country_skips_recently_scanned_urls(
    temp_settings, sample_toon_file
):
    """scan_country skips URLs already in the recent-scan window."""
    scanner = TechScanner(temp_settings)
    now = datetime.now(timezone.utc).isoformat()

    # Pre-populate page1 and page2 as recently scanned
    conn = sqlite3.connect(scanner.db_path)
    try:
        for url in ["https://example.test/page1", "https://example.test/page2"]:
            conn.execute(
                """
                INSERT INTO url_tech_results
                (url, country_code, scan_id, technologies, scanned_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (url, "TESTLAND", "t-prev", "{}", now),
            )
        conn.commit()
    finally:
        conn.close()

    scan_results: list[str] = []

    async def _fake_detect_batch(urls, **kwargs):
        scan_results.extend(urls)
        on_result = kwargs.get("on_result")
        for url in urls:
            r = TechDetectionResult(url=url, technologies={})
            if on_result:
                on_result(r)
        return {u: TechDetectionResult(url=u, technologies={}) for u in urls}

    with patch.object(scanner.detector, "detect_urls_batch", side_effect=_fake_detect_batch):
        stats = await scanner.scan_country(
            "TESTLAND",
            sample_toon_file,
            skip_recently_scanned_days=7,
        )

    # Only page3 should have been submitted to the detector
    assert scan_results == ["https://example.test/page3"]
    assert stats["urls_scanned"] == 1
    assert stats["urls_skipped_recently_scanned"] == 2
    assert stats["total_urls"] == 3


@pytest.mark.asyncio
async def test_tech_scan_country_all_recently_scanned_skips_scan(
    temp_settings, sample_toon_file
):
    """When all URLs are recently scanned scan_country returns immediately."""
    scanner = TechScanner(temp_settings)
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(scanner.db_path)
    try:
        for url in [
            "https://example.test/page1",
            "https://example.test/page2",
            "https://example.test/page3",
        ]:
            conn.execute(
                """
                INSERT INTO url_tech_results
                (url, country_code, scan_id, technologies, scanned_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (url, "TESTLAND", "t-prev", "{}", now),
            )
        conn.commit()
    finally:
        conn.close()

    with patch.object(scanner.detector, "detect_urls_batch", new_callable=AsyncMock) as mock_detect:
        stats = await scanner.scan_country(
            "TESTLAND",
            sample_toon_file,
            skip_recently_scanned_days=7,
        )

    mock_detect.assert_not_called()
    assert stats["urls_scanned"] == 0
    assert stats["urls_skipped_recently_scanned"] == 3
    assert stats["is_complete"] is True


# ---------------------------------------------------------------------------
# _get_last_scan_time_per_country — SocialMediaScannerJob
# ---------------------------------------------------------------------------

def test_social_get_last_scan_time_empty_db(temp_settings):
    """Returns empty dict when no scans have been recorded."""
    job = SocialMediaScannerJob(temp_settings)
    result = job._get_last_scan_time_per_country()
    assert result == {}


def test_social_get_last_scan_time_returns_max_per_country(temp_settings):
    """Returns the latest scanned_at for each country_code."""
    job = SocialMediaScannerJob(temp_settings)
    earlier = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    later = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(job.db_path)
    try:
        for ts, scan_id in [(earlier, "s-old"), (later, "s-new")]:
            conn.execute(
                """
                INSERT INTO url_social_media_results
                (url, country_code, scan_id, is_reachable, social_tier,
                 twitter_links, x_links, bluesky_links, mastodon_links,
                 platforms_version, scanned_at)
                VALUES (?, ?, ?, ?, ?, '[]', '[]', '[]', '[]', ?, ?)
                """,
                ("https://example.test/p", "TESTLAND", scan_id, 1, "no_social",
                 SOCIAL_PLATFORMS_VERSION, ts),
            )
        conn.commit()
    finally:
        conn.close()

    result = job._get_last_scan_time_per_country()
    assert result["TESTLAND"] == later


def test_social_get_last_scan_time_multiple_countries(temp_settings):
    """Returns separate max timestamps for each country."""
    job = SocialMediaScannerJob(temp_settings)
    ts_a = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    ts_b = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(job.db_path)
    try:
        conn.execute(
            """
            INSERT INTO url_social_media_results
            (url, country_code, scan_id, is_reachable, social_tier,
             twitter_links, x_links, bluesky_links, mastodon_links,
             platforms_version, scanned_at)
            VALUES (?, ?, ?, ?, ?, '[]', '[]', '[]', '[]', ?, ?)
            """,
            ("https://a.test/p", "COUNTRY_A", "s-a", 1, "no_social",
             SOCIAL_PLATFORMS_VERSION, ts_a),
        )
        conn.execute(
            """
            INSERT INTO url_social_media_results
            (url, country_code, scan_id, is_reachable, social_tier,
             twitter_links, x_links, bluesky_links, mastodon_links,
             platforms_version, scanned_at)
            VALUES (?, ?, ?, ?, ?, '[]', '[]', '[]', '[]', ?, ?)
            """,
            ("https://b.test/p", "COUNTRY_B", "s-b", 1, "no_social",
             SOCIAL_PLATFORMS_VERSION, ts_b),
        )
        conn.commit()
    finally:
        conn.close()

    result = job._get_last_scan_time_per_country()
    assert result["COUNTRY_A"] == ts_a
    assert result["COUNTRY_B"] == ts_b


# ---------------------------------------------------------------------------
# scan_all_countries sorts by last scan time — SocialMediaScannerJob
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_social_scan_all_countries_unseen_first(tmp_path):
    """Countries not yet scanned are processed before recently-scanned ones."""
    db_path = tmp_path / "test.db"
    settings = Settings(
        scheduler_cadence="monthly",
        crawl_rate_limit_per_host=0.5,
        crawl_timeout_seconds=2,
        toon_output_dir=tmp_path / "toon-cache",
        metadata_db_url=f"sqlite:///{db_path}",
    )
    job = SocialMediaScannerJob(settings)

    # Create two TOON files: "alpha" (already scanned) and "zulu" (never scanned)
    for country in ("alpha", "zulu"):
        toon_data = {
            "version": "0.1-seed",
            "country": country.capitalize(),
            "page_count": 1,
            "domains": [
                {
                    "canonical_domain": f"{country}.test",
                    "pages": [{"url": f"https://{country}.test/page"}],
                }
            ],
        }
        (tmp_path / f"{country}.toon").write_text(
            json.dumps(toon_data), encoding="utf-8"
        )

    # Pre-populate "alpha" as recently scanned so it would be skipped
    recent_ts = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(job.db_path)
    try:
        conn.execute(
            """
            INSERT INTO url_social_media_results
            (url, country_code, scan_id, is_reachable, social_tier,
             twitter_links, x_links, bluesky_links, mastodon_links,
             platforms_version, scanned_at)
            VALUES (?, ?, ?, ?, ?, '[]', '[]', '[]', '[]', ?, ?)
            """,
            ("https://alpha.test/page", "ALPHA", "s-alpha", 1, "no_social",
             SOCIAL_PLATFORMS_VERSION, recent_ts),
        )
        conn.commit()
    finally:
        conn.close()

    scanned_countries: list[str] = []

    async def _fake_scan_batch(urls, **kwargs):
        on_result = kwargs.get("on_result")
        results = {}
        for url in urls:
            r = SocialMediaScanResult(url=url, is_reachable=True, social_tier="no_social")
            results[url] = r
            if on_result:
                on_result(r)
        return results

    with patch.object(job.scanner, "scan_urls_batch", side_effect=_fake_scan_batch):
        # Use a very short runtime so the scanner stops after the first country
        stats_list = await job.scan_all_countries(
            tmp_path,
            rate_limit_per_second=100.0,
            max_runtime_seconds=3600,
            skip_recently_scanned_days=7,
        )

    # "zulu" (never scanned) should come before "alpha" (recently scanned)
    # "alpha" should be skipped (all URLs recently scanned)
    processed = [s["country_code"] for s in stats_list]
    zulu_idx = processed.index("ZULU") if "ZULU" in processed else -1
    alpha_idx = processed.index("ALPHA") if "ALPHA" in processed else len(processed)
    assert zulu_idx < alpha_idx, (
        f"Expected ZULU (never scanned) before ALPHA (recently scanned), "
        f"got order: {processed}"
    )


# ---------------------------------------------------------------------------
# _get_last_scan_time_per_country — TechScanner
# ---------------------------------------------------------------------------

def test_tech_get_last_scan_time_empty_db(temp_settings):
    """Returns empty dict when no tech scans have been recorded."""
    scanner = TechScanner(temp_settings)
    result = scanner._get_last_scan_time_per_country()
    assert result == {}


def test_tech_get_last_scan_time_returns_max_per_country(temp_settings):
    """Returns the latest scanned_at for each country_code in tech results."""
    scanner = TechScanner(temp_settings)
    earlier = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    later = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(scanner.db_path)
    try:
        for ts, scan_id in [(earlier, "t-old"), (later, "t-new")]:
            conn.execute(
                """
                INSERT INTO url_tech_results
                (url, country_code, scan_id, technologies, scanned_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("https://example.test/p", "TESTLAND", scan_id, "{}", ts),
            )
        conn.commit()
    finally:
        conn.close()

    result = scanner._get_last_scan_time_per_country()
    assert result["TESTLAND"] == later


# ---------------------------------------------------------------------------
# scan_all_countries sorts by last scan time — TechScanner
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tech_scan_all_countries_unseen_first(tmp_path):
    """Countries not yet scanned are processed before recently-scanned ones."""
    db_path = tmp_path / "test.db"
    settings = Settings(
        scheduler_cadence="monthly",
        crawl_rate_limit_per_host=0.5,
        crawl_timeout_seconds=2,
        toon_output_dir=tmp_path / "toon-cache",
        metadata_db_url=f"sqlite:///{db_path}",
    )
    scanner = TechScanner(settings)

    for country in ("alpha", "zulu"):
        toon_data = {
            "version": "0.1-seed",
            "country": country.capitalize(),
            "page_count": 1,
            "domains": [
                {
                    "canonical_domain": f"{country}.test",
                    "pages": [{"url": f"https://{country}.test/page"}],
                }
            ],
        }
        (tmp_path / f"{country}.toon").write_text(
            json.dumps(toon_data), encoding="utf-8"
        )

    recent_ts = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(scanner.db_path)
    try:
        conn.execute(
            """
            INSERT INTO url_tech_results
            (url, country_code, scan_id, technologies, scanned_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("https://alpha.test/page", "ALPHA", "t-alpha", "{}", recent_ts),
        )
        conn.commit()
    finally:
        conn.close()

    async def _fake_detect_batch(urls, **kwargs):
        on_result = kwargs.get("on_result")
        results = {}
        for url in urls:
            r = TechDetectionResult(url=url, technologies={})
            results[url] = r
            if on_result:
                on_result(r)
        return results

    with patch.object(scanner.detector, "detect_urls_batch", side_effect=_fake_detect_batch):
        stats_list = await scanner.scan_all_countries(
            tmp_path,
            rate_limit_per_second=100.0,
            max_runtime_seconds=3600,
            skip_recently_scanned_days=7,
        )

    processed = [s["country_code"] for s in stats_list]
    zulu_idx = processed.index("ZULU") if "ZULU" in processed else -1
    alpha_idx = processed.index("ALPHA") if "ALPHA" in processed else len(processed)
    assert zulu_idx < alpha_idx, (
        f"Expected ZULU (never scanned) before ALPHA (recently scanned), "
        f"got order: {processed}"
    )


# ---------------------------------------------------------------------------
# _get_last_scan_time_per_country — AccessibilityScannerJob
# ---------------------------------------------------------------------------

def test_accessibility_get_last_scan_time_empty_db(temp_settings):
    """Returns empty dict when no accessibility scans have been recorded."""
    job = AccessibilityScannerJob(temp_settings)
    result = job._get_last_scan_time_per_country()
    assert result == {}


def test_accessibility_get_last_scan_time_returns_max_per_country(temp_settings):
    """Returns the latest scanned_at for each country_code in accessibility results."""
    job = AccessibilityScannerJob(temp_settings)
    earlier = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    later = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(job.db_path)
    try:
        for ts, scan_id in [(earlier, "a-old"), (later, "a-new")]:
            conn.execute(
                """
                INSERT INTO url_accessibility_results
                (url, country_code, scan_id, is_reachable,
                 has_statement, found_in_footer,
                 statement_links, matched_terms, scanned_at)
                VALUES (?, ?, ?, ?, ?, ?, '[]', '[]', ?)
                """,
                ("https://example.test/p", "TESTLAND", scan_id, 1, 0, 0, ts),
            )
        conn.commit()
    finally:
        conn.close()

    result = job._get_last_scan_time_per_country()
    assert result["TESTLAND"] == later

