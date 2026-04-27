"""Tests for the social media stats report generator."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.cli.generate_social_media_report import (
    _build_interactive_block,
    _build_stats_block,
    _build_top100_section,
    _build_sovereignty_section,
    _enrich_sovereignty_metrics,
    _legacy_exposure,
    _load_top100_institution_metadata,
    _query_by_country,
    _query_metric_drilldowns_by_country,
    _query_platform_drilldowns_by_country,
    _query_summary,
    _query_top100_results,
    _sovereignty_score,
    _sovereignty_tier,
    _TOP100_COUNTRY_CODE,
    generate_social_media_report,
)
from src.storage.schema import initialize_schema


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

_STATS_MARKER_START = "<!-- SOCIAL_MEDIA_STATS_START -->"
_STATS_MARKER_END = "<!-- SOCIAL_MEDIA_STATS_END -->"

_SOCIAL_MEDIA_PAGE_TEMPLATE = """\
---
title: Social Media Scanning
layout: page
---

# Social Media Scanning

## Current Stats

<!-- SOCIAL_MEDIA_STATS_START -->

_No scan data yet._

<!-- SOCIAL_MEDIA_STATS_END -->

## Overview

Some content.
"""


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """Return path to a freshly initialised, empty database."""
    db_path = tmp_path / "test.db"
    initialize_schema(f"sqlite:///{db_path}")
    return db_path


@pytest.fixture
def populated_db(tmp_path: Path) -> Path:
    """Return path to a database with sample social media scan data."""
    db_path = tmp_path / "test.db"
    initialize_schema(f"sqlite:///{db_path}")

    conn = sqlite3.connect(db_path)
    try:
        rows = [
            # url, country, scan_id, is_reachable, twitter, x, bluesky, mastodon,
            # facebook, linkedin, tier
            (
                "https://example.is/page1",
                "ICELAND",
                "social-ICELAND-20240601-001",
                1, '["https://twitter.com/gov_is"]', '[]', '[]', '[]',
                '[]', '[]',
                "twitter_only", "2024-06-01T10:00:00+00:00",
            ),
            (
                "https://example.is/page2",
                "ICELAND",
                "social-ICELAND-20240601-001",
                0, '[]', '[]', '[]', '[]',
                '[]', '[]',
                "unreachable", "2024-06-01T10:01:00+00:00",
            ),
            (
                "https://example.is/page3",
                "ICELAND",
                "social-ICELAND-20240601-001",
                1, '[]', '[]',
                '["https://bsky.app/profile/gov.is"]',
                '["https://mastodon.social/@gov_is"]',
                '[]', '[]',
                "modern_only", "2024-06-01T10:02:00+00:00",
            ),
            (
                "https://example.fr/page1",
                "FRANCE",
                "social-FRANCE-20240602-001",
                1, '[]', '["https://x.com/france_gov"]',
                '[]', '[]',
                '["https://www.facebook.com/francegov"]', '[]',
                "twitter_only", "2024-06-02T08:00:00+00:00",
            ),
            (
                "https://example.fr/page2",
                "FRANCE",
                "social-FRANCE-20240602-001",
                1, '[]', '[]', '[]', '[]',
                '[]', '[]',
                "no_social", "2024-06-02T08:01:00+00:00",
            ),
        ]
        for row in rows:
            conn.execute(
                """
                INSERT INTO url_social_media_results
                (url, country_code, scan_id, is_reachable,
                 twitter_links, x_links, bluesky_links, mastodon_links,
                 facebook_links, linkedin_links,
                 social_tier, scanned_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
        conn.commit()
    finally:
        conn.close()

    return db_path


# ---------------------------------------------------------------------------
# _query_summary tests
# ---------------------------------------------------------------------------

def test_query_summary_empty_db(empty_db: Path):
    """Should return zero/null values from an empty database."""
    conn = sqlite3.connect(empty_db)
    conn.row_factory = sqlite3.Row
    try:
        result = _query_summary(conn)
    finally:
        conn.close()

    assert result.get("total_batches", 0) == 0
    assert result.get("total_scanned", 0) == 0


def test_query_summary_populated_db(populated_db: Path):
    """Should aggregate stats correctly across countries."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        result = _query_summary(conn)
    finally:
        conn.close()

    assert result["total_batches"] == 2   # 2 distinct scan_ids
    assert result["total_scanned"] == 5   # 5 distinct URLs
    assert result["total_reachable"] == 4  # 4 reachable
    assert result["twitter_pages"] == 1    # 1 page with twitter links
    assert result["x_pages"] == 1          # 1 page with x links
    assert result["bluesky_pages"] == 1    # 1 page with bluesky links
    assert result["mastodon_pages"] == 1   # 1 page with mastodon links
    assert result["facebook_pages"] == 1   # 1 page with facebook links
    assert result["linkedin_pages"] == 0   # no pages with linkedin links


# ---------------------------------------------------------------------------
# _query_by_country tests
# ---------------------------------------------------------------------------

def test_query_by_country_populated_db(populated_db: Path):
    """Should return per-country rows sorted alphabetically."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_by_country(conn)
    finally:
        conn.close()

    assert len(rows) == 2
    countries = [r["country_code"] for r in rows]
    assert countries == ["FRANCE", "ICELAND"]

    iceland = next(r for r in rows if r["country_code"] == "ICELAND")
    assert iceland["total_scanned"] == 3
    assert iceland["reachable"] == 2


# ---------------------------------------------------------------------------
# _build_stats_block tests
# ---------------------------------------------------------------------------

def test_build_stats_block_empty_summary():
    """Should return a placeholder block when no summary data is available."""
    block = _build_stats_block({}, "2024-06-01 12:00 UTC")
    assert _STATS_MARKER_START in block
    assert _STATS_MARKER_END in block
    assert "No scan data yet" in block


def test_build_stats_block_with_data():
    """Should produce a block containing the key stat figures."""
    summary = {
        "total_batches": 10,
        "total_scanned": 500,
        "total_reachable": 450,
        "twitter_pages": 30,
        "x_pages": 20,
        "bluesky_pages": 15,
        "mastodon_pages": 12,
        "facebook_pages": 40,
        "linkedin_pages": 25,
        "last_scan": "2024-06-01T12:00:00",
    }
    block = _build_stats_block(summary, "2024-06-01 12:00 UTC")
    assert _STATS_MARKER_START in block
    assert _STATS_MARKER_END in block
    assert "10" in block          # batches
    assert "500" in block         # scanned
    assert "450" in block         # reachable
    assert "30" in block          # twitter
    assert "15" in block          # bluesky
    assert "12" in block          # mastodon
    assert "40" in block          # facebook
    assert "25" in block          # linkedin
    assert "social-media-data.json" in block


# ---------------------------------------------------------------------------
# generate_social_media_report tests
# ---------------------------------------------------------------------------

def test_generate_social_media_report_missing_db(tmp_path: Path):
    """Should write an empty-data JSON file and a placeholder stats block."""
    page_path = tmp_path / "social-media.md"
    page_path.write_text(_SOCIAL_MEDIA_PAGE_TEMPLATE)
    data_path = tmp_path / "social-media-data.json"
    db_path = tmp_path / "nonexistent.db"

    result = generate_social_media_report(db_path, page_path, data_path)

    assert result is True
    assert data_path.exists()
    data = json.loads(data_path.read_text())
    assert data["summary"]["total_scanned"] == 0

    content = page_path.read_text()
    assert _STATS_MARKER_START in content
    assert _STATS_MARKER_END in content
    assert "No scan data yet" in content
    assert "## Overview" in content  # rest of page preserved


def test_generate_social_media_report_with_data(populated_db: Path, tmp_path: Path):
    """Should inject real stats and write accurate JSON data."""
    page_path = tmp_path / "social-media.md"
    page_path.write_text(_SOCIAL_MEDIA_PAGE_TEMPLATE)
    data_path = tmp_path / "social-media-data.json"

    result = generate_social_media_report(populated_db, page_path, data_path)

    assert result is True

    # Check JSON data file
    assert data_path.exists()
    data = json.loads(data_path.read_text())
    assert data["summary"]["total_batches"] == 2
    assert data["summary"]["total_scanned"] == 5
    assert data["summary"]["total_reachable"] == 4
    assert data["summary"]["twitter_pages"] == 1
    assert data["summary"]["x_pages"] == 1
    assert data["summary"]["bluesky_pages"] == 1
    assert data["summary"]["mastodon_pages"] == 1
    assert len(data["by_country"]) == 2

    # Check Markdown page was updated
    content = page_path.read_text()
    assert _STATS_MARKER_START in content
    assert _STATS_MARKER_END in content
    assert "5" in content       # total scanned
    assert "4" in content       # reachable
    assert "social-media-data.json" in content
    # Rest of the page must still be present
    assert "## Overview" in content


def test_generate_social_media_report_missing_markers(populated_db: Path, tmp_path: Path):
    """Should return False without modifying the page when markers are absent."""
    page_path = tmp_path / "social-media.md"
    original = "# Social Media\n\nNo markers here.\n"
    page_path.write_text(original)
    data_path = tmp_path / "social-media-data.json"

    result = generate_social_media_report(populated_db, page_path, data_path)

    assert result is False
    assert page_path.read_text() == original
    # JSON data file is still written even when the page update fails
    assert data_path.exists()


def test_generate_social_media_report_missing_page(populated_db: Path, tmp_path: Path):
    """Should return False when the social-media.md page does not exist."""
    page_path = tmp_path / "nonexistent.md"
    data_path = tmp_path / "social-media-data.json"

    result = generate_social_media_report(populated_db, page_path, data_path)

    assert result is False
    # JSON data file is still written
    assert data_path.exists()


def test_generate_social_media_report_json_structure(populated_db: Path, tmp_path: Path):
    """JSON data file should have the expected top-level keys."""
    page_path = tmp_path / "social-media.md"
    page_path.write_text(_SOCIAL_MEDIA_PAGE_TEMPLATE)
    data_path = tmp_path / "social-media-data.json"

    generate_social_media_report(populated_db, page_path, data_path)

    data = json.loads(data_path.read_text())
    assert "generated_at" in data
    assert "summary" in data
    assert "by_country" in data
    assert "platform_drilldowns" in data

    summary = data["summary"]
    for key in ("total_batches", "total_scanned", "total_reachable",
                "twitter_pages", "x_pages", "bluesky_pages", "mastodon_pages",
                "facebook_pages", "linkedin_pages"):
        assert key in summary, f"Missing key: {key}"


def test_generate_social_media_report_preserves_page_structure(
    populated_db: Path, tmp_path: Path
):
    """Content outside the markers must be preserved after an update."""
    page_path = tmp_path / "social-media.md"
    page_path.write_text(_SOCIAL_MEDIA_PAGE_TEMPLATE)
    data_path = tmp_path / "social-media-data.json"

    generate_social_media_report(populated_db, page_path, data_path)

    content = page_path.read_text()
    # Front matter and heading
    assert "title: Social Media Scanning" in content
    assert "# Social Media Scanning" in content
    # Section after the markers
    assert "## Overview" in content
    assert "Some content." in content


# ---------------------------------------------------------------------------
# Tests for duplicate URL handling (inflated counts bug)
# ---------------------------------------------------------------------------

@pytest.fixture
def duplicate_scan_db(tmp_path: Path) -> Path:
    """DB where the same URL appears in two different scan batches."""
    db_path = tmp_path / "test.db"
    initialize_schema(f"sqlite:///{db_path}")
    conn = sqlite3.connect(db_path)
    try:
        # Same URL scanned twice in different batches
        rows = [
            (
                "https://example.is/page1", "ICELAND",
                "social-ICELAND-scan-001", 1,
                '["https://twitter.com/gov_is"]', '[]', '[]', '[]',
                '[]', '[]',
                "twitter_only", "2024-06-01T10:00:00+00:00",
            ),
            # Same URL in a second batch - should NOT be double-counted
            (
                "https://example.is/page1", "ICELAND",
                "social-ICELAND-scan-002", 1,
                '["https://twitter.com/gov_is"]', '[]', '[]', '[]',
                '[]', '[]',
                "twitter_only", "2024-06-02T10:00:00+00:00",
            ),
            (
                "https://example.is/page2", "ICELAND",
                "social-ICELAND-scan-001", 0,
                '[]', '[]', '[]', '[]',
                '[]', '[]',
                "unreachable", "2024-06-01T10:01:00+00:00",
            ),
        ]
        for row in rows:
            conn.execute(
                """
                INSERT INTO url_social_media_results
                (url, country_code, scan_id, is_reachable,
                 twitter_links, x_links, bluesky_links, mastodon_links,
                 facebook_links, linkedin_links,
                 social_tier, scanned_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_query_summary_no_double_counting(duplicate_scan_db: Path):
    """URL that appears in multiple scan batches should be counted only once."""
    conn = sqlite3.connect(duplicate_scan_db)
    conn.row_factory = sqlite3.Row
    try:
        result = _query_summary(conn)
    finally:
        conn.close()

    assert result["total_batches"] == 2     # 2 distinct scan_ids
    assert result["total_scanned"] == 2     # only 2 distinct URLs
    assert result["total_reachable"] == 1   # page1 is reachable (counted once)
    assert result["twitter_pages"] == 1     # page1 has twitter (counted once)


def test_query_by_country_no_double_counting(duplicate_scan_db: Path):
    """Per-country query must not inflate counts for multi-batch URLs."""
    conn = sqlite3.connect(duplicate_scan_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_by_country(conn)
    finally:
        conn.close()

    assert len(rows) == 1
    iceland = rows[0]
    assert iceland["total_scanned"] == 2   # 2 distinct URLs
    assert iceland["reachable"] == 1       # only page1 is reachable
    assert iceland["twitter_pages"] == 1   # only page1 has twitter


def test_build_stats_block_with_total_available():
    """Stats block should include coverage line when total_available > 0."""
    summary = {
        "total_batches": 5,
        "total_scanned": 100,
        "total_reachable": 80,
        "twitter_pages": 20,
        "x_pages": 10,
        "bluesky_pages": 5,
        "mastodon_pages": 15,
        "facebook_pages": 30,
        "linkedin_pages": 8,
        "last_scan": "2024-06-01T12:00:00",
    }
    block = _build_stats_block(summary, "2024-06-01 12:00 UTC", total_available=1000)
    assert "100" in block                          # scanned
    assert "1,000" in block                        # available
    assert "10.0%" in block                        # 100/1000 coverage


def test_generate_social_media_report_json_includes_total_available(
    populated_db: Path, tmp_path: Path
):
    """JSON data file should include total_available when seeds_dir is provided."""
    # Create a minimal toon seed directory with one file
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    seed_data = {"version": "0.1-seed", "country": "Iceland", "page_count": 50, "domains": []}
    (seeds_dir / "iceland.toon").write_text(json.dumps(seed_data), encoding="utf-8")

    page_path = tmp_path / "social-media.md"
    page_path.write_text(_SOCIAL_MEDIA_PAGE_TEMPLATE)
    data_path = tmp_path / "social-media-data.json"

    generate_social_media_report(populated_db, page_path, data_path, seeds_dir)

    data = json.loads(data_path.read_text())
    assert data["summary"]["total_available"] == 50


# ---------------------------------------------------------------------------
# Tests for _count_toon_seed_urls
# ---------------------------------------------------------------------------

def test_count_toon_seed_urls_missing_dir(tmp_path: Path):
    """Should return empty dict when the directory does not exist."""
    from src.cli.generate_social_media_report import _count_toon_seed_urls
    result = _count_toon_seed_urls(tmp_path / "nonexistent")
    assert result == {}


def test_count_toon_seed_urls_empty_dir(tmp_path: Path):
    """Should return empty dict when the directory contains no .toon files."""
    from src.cli.generate_social_media_report import _count_toon_seed_urls
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    result = _count_toon_seed_urls(seeds_dir)
    assert result == {}


def test_count_toon_seed_urls_reads_page_count(tmp_path: Path):
    """Should correctly read page_count from toon seed files."""
    from src.cli.generate_social_media_report import _count_toon_seed_urls
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    for name, count in [("iceland", 139), ("norway", 239)]:
        data = {"page_count": count, "domains": []}
        (seeds_dir / f"{name}.toon").write_text(json.dumps(data), encoding="utf-8")
    result = _count_toon_seed_urls(seeds_dir)
    assert result == {"ICELAND": 139, "NORWAY": 239}


# ---------------------------------------------------------------------------
# Tests for new platform columns (Facebook, LinkedIn) and column ordering
# ---------------------------------------------------------------------------

def test_build_stats_block_includes_facebook_linkedin():
    """Platform overview table must include Facebook and LinkedIn rows."""
    summary = {
        "total_batches": 3,
        "total_scanned": 200,
        "total_reachable": 180,
        "twitter_pages": 10,
        "x_pages": 5,
        "bluesky_pages": 8,
        "mastodon_pages": 12,
        "facebook_pages": 25,
        "linkedin_pages": 15,
        "last_scan": "2024-06-01T12:00:00",
    }
    block = _build_stats_block(summary, "2024-06-01 12:00 UTC")
    assert "Facebook" in block
    assert "LinkedIn" in block
    assert "Legacy social media" in block
    assert "Modern" in block or "modern" in block


def test_build_stats_block_country_table_column_order(populated_db: Path):
    """Country table must place No Social and Legacy-only before platform columns."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        summary = _query_summary(conn)
        by_country = _query_by_country(conn)
    finally:
        conn.close()

    block = _build_stats_block(summary, "2024-06-01 12:00 UTC", by_country=by_country)

    # Find the header row of the country table
    header_line = None
    for line in block.splitlines():
        if "No Social" in line and "Legacy-only" in line and "Scan Period" in line:
            header_line = line
            break

    assert header_line is not None, "Country table header not found"
    # No Social must come before Legacy-only, which must come before Twitter column
    ns_pos = header_line.index("No Social")
    lo_pos = header_line.index("Legacy-only")
    # Find " Twitter |" to avoid matching "Legacy-only" or "Twitter-only"
    tw_pos = header_line.index("| Twitter |")
    assert ns_pos < lo_pos < tw_pos, (
        f"Column order wrong: No Social={ns_pos}, Legacy-only={lo_pos}, Twitter={tw_pos}"
    )


def test_build_stats_block_sortable_table_uses_scan_period_identifier(populated_db: Path):
    """Country table should still identify itself via the Scan Period column."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        summary = _query_summary(conn)
        by_country = _query_by_country(conn)
    finally:
        conn.close()

    block = _build_stats_block(summary, "2024-06-01 12:00 UTC", by_country=by_country)

    assert "| Country |" in block
    assert "Scan Period" in block
    assert "Non-X Score" not in block


def test_build_stats_block_available_reachable_clarification(populated_db: Path):
    """Stats block must explain Available and Reachable in the country table section."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        summary = _query_summary(conn)
        by_country = _query_by_country(conn)
    finally:
        conn.close()

    block = _build_stats_block(summary, "2024-06-01 12:00 UTC", by_country=by_country)

    assert "Available" in block
    assert "Reachable" in block
    # The introductory sentence should explain both terms
    assert "valid HTTP response" in block or "tracked in our domain list" in block


def test_generate_social_media_report_json_includes_facebook_linkedin(
    populated_db: Path, tmp_path: Path
):
    """JSON data file should include facebook_pages and linkedin_pages."""
    page_path = tmp_path / "social-media.md"
    page_path.write_text(_SOCIAL_MEDIA_PAGE_TEMPLATE)
    data_path = tmp_path / "social-media-data.json"

    generate_social_media_report(populated_db, page_path, data_path)

    data = json.loads(data_path.read_text())
    assert "facebook_pages" in data["summary"]
    assert "linkedin_pages" in data["summary"]
    assert data["summary"]["facebook_pages"] == 1   # one France page has Facebook
    assert data["summary"]["linkedin_pages"] == 0


# ---------------------------------------------------------------------------
# Tests for Digital Sovereignty helpers and section
# ---------------------------------------------------------------------------

def test_sovereignty_score_all_no_social():
    """Score should be 100% when all reachable pages have no social links."""
    row = {"reachable": 10, "no_social": 10, "modern_only": 0}
    assert _sovereignty_score(row) == 100.0


def test_sovereignty_score_all_modern_only():
    """Score should be 100% when all reachable pages use modern platforms only."""
    row = {"reachable": 10, "no_social": 0, "modern_only": 10}
    assert _sovereignty_score(row) == 100.0


def test_sovereignty_score_mixed():
    """Score reflects the proportion of no_social + modern_only pages."""
    row = {"reachable": 20, "no_social": 10, "modern_only": 5}
    assert _sovereignty_score(row) == 75.0  # 15/20


def test_sovereignty_score_zero_reachable():
    """Score should not raise; uses max(reachable, 1) guard."""
    row = {"reachable": 0, "no_social": 0, "modern_only": 0}
    assert _sovereignty_score(row) == 0.0


def test_legacy_exposure_all_legacy():
    """Legacy exposure should be 100% when all reachable pages link to legacy platforms."""
    row = {"reachable": 5, "has_any_legacy": 5}
    assert _legacy_exposure(row) == 100.0


def test_legacy_exposure_none():
    """Legacy exposure should be 0% when no pages link to legacy platforms."""
    row = {"reachable": 5, "has_any_legacy": 0}
    assert _legacy_exposure(row) == 0.0


def test_legacy_exposure_partial():
    """Legacy exposure reflects the ratio of legacy-linked pages to reachable."""
    row = {"reachable": 10, "has_any_legacy": 3}
    assert _legacy_exposure(row) == 30.0


def test_sovereignty_tier_leader():
    """Should be Leader when score >= 80 and legacy <= 5."""
    assert _sovereignty_tier(85.0, 3.0) == "🥇 Leader"


def test_sovereignty_tier_strong():
    """Should be Strong when score >= 60 and legacy <= 20."""
    assert _sovereignty_tier(65.0, 15.0) == "🥈 Strong"


def test_sovereignty_tier_growing():
    """Should be Growing when score >= 40."""
    assert _sovereignty_tier(45.0, 30.0) == "🥉 Growing"


def test_sovereignty_tier_legacy_heavy():
    """Should be Legacy-heavy when legacy_pct >= 50 and score is low."""
    assert _sovereignty_tier(10.0, 60.0) == "⚠️ Legacy-heavy"


def test_sovereignty_tier_mixed():
    """Should be Mixed for moderate scores that don't fit other tiers."""
    assert _sovereignty_tier(20.0, 35.0) == "➡️ Mixed"


def test_build_sovereignty_section_empty():
    """Should return empty list when by_country is empty."""
    assert _build_sovereignty_section([]) == []


def test_enrich_sovereignty_metrics_with_reachable():
    """_enrich_sovereignty_metrics should add sovereignty fields to a row dict."""
    row = {
        "country_code": "TEST", "reachable": 10, "no_social": 6,
        "modern_only": 2, "has_any_legacy": 1,
    }
    enriched = _enrich_sovereignty_metrics(row)
    assert enriched["sovereignty_score"] == 80.0   # (6+2)/10
    assert enriched["legacy_exposure"] == 10.0     # 1/10
    # score=80, legacy=10 → Strong (Leader needs legacy <= 5)
    assert enriched["sovereignty_tier"] == "🥈 Strong"
    # Original row should not be mutated
    assert "sovereignty_score" not in row


def test_enrich_sovereignty_metrics_zero_reachable():
    """_enrich_sovereignty_metrics should set score/exposure to None when no reachable pages."""
    row = {"country_code": "EMPTY", "reachable": 0, "no_social": 0, "modern_only": 0, "has_any_legacy": 0}
    enriched = _enrich_sovereignty_metrics(row)
    assert enriched["sovereignty_score"] is None
    assert enriched["legacy_exposure"] is None


def test_build_sovereignty_section_skips_zero_reachable():
    """Countries with reachable = 0 should be excluded from the leaderboard."""
    rows = [
        {"country_code": "NOWHERE", "reachable": 0, "no_social": 0,
         "modern_only": 0, "has_any_legacy": 0},
    ]
    assert _build_sovereignty_section(rows) == []


def test_build_sovereignty_section_sorted_by_score():
    """Countries should be sorted by sovereignty score descending."""
    rows = [
        {"country_code": "LOW", "reachable": 10, "no_social": 2,
         "modern_only": 0, "has_any_legacy": 8},
        {"country_code": "HIGH", "reachable": 10, "no_social": 9,
         "modern_only": 1, "has_any_legacy": 0},
    ]
    lines = _build_sovereignty_section(rows)
    content = "\n".join(lines)
    # HIGH should appear before LOW in the output
    assert content.index("High") < content.index("Low")


def test_build_sovereignty_section_contains_key_fields():
    """Leaderboard should contain country code, score, and tier columns."""
    rows = [
        {"country_code": "ICELAND", "reachable": 10, "no_social": 8,
         "modern_only": 2, "has_any_legacy": 0},
    ]
    lines = _build_sovereignty_section(rows)
    content = "\n".join(lines)
    assert "Iceland" in content
    assert "100.0%" in content       # sovereignty score
    assert "0.0%" in content         # legacy exposure
    assert "🥇 Leader" in content    # tier


def test_build_stats_block_includes_sovereignty_section(populated_db: Path):
    """Stats block should include the Digital Sovereignty Rankings section."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        summary = _query_summary(conn)
        by_country = _query_by_country(conn)
    finally:
        conn.close()

    block = _build_stats_block(summary, "2024-06-01 12:00 UTC", by_country=by_country)

    assert "Digital Sovereignty Rankings" in block
    assert "Sovereignty Score" in block
    assert "Legacy Exposure" in block


def test_build_stats_block_country_table_has_sov_score_column(populated_db: Path):
    """Per-country table should include a Sov. Score column."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        summary = _query_summary(conn)
        by_country = _query_by_country(conn)
    finally:
        conn.close()

    block = _build_stats_block(summary, "2024-06-01 12:00 UTC", by_country=by_country)

    # Find the header row of the detailed country table
    header_line = None
    for line in block.splitlines():
        if "Sov. Score" in line and "Scan Period" in line:
            header_line = line
            break

    assert header_line is not None, "Sov. Score column not found in country table header"
    # Sov. Score should come before No Social
    sov_pos = header_line.index("Sov. Score")
    ns_pos = header_line.index("No Social")
    assert sov_pos < ns_pos, "Sov. Score column should appear before No Social"


def test_generate_social_media_report_json_includes_sovereignty(
    populated_db: Path, tmp_path: Path
):
    """JSON data file should include sovereignty_score and sovereignty_tier per country."""
    page_path = tmp_path / "social-media.md"
    page_path.write_text(_SOCIAL_MEDIA_PAGE_TEMPLATE)
    data_path = tmp_path / "social-media-data.json"

    generate_social_media_report(populated_db, page_path, data_path)

    data = json.loads(data_path.read_text())
    assert "by_country" in data
    for entry in data["by_country"]:
        assert "sovereignty_score" in entry, f"Missing sovereignty_score for {entry['country_code']}"
        assert "sovereignty_tier" in entry, f"Missing sovereignty_tier for {entry['country_code']}"
        assert "legacy_exposure" in entry, f"Missing legacy_exposure for {entry['country_code']}"

    # ICELAND has 2 reachable pages: 1 twitter_only, 1 modern_only
    iceland = next(e for e in data["by_country"] if e["country_code"] == "ICELAND")
    # modern_only=1, no_social=0, reachable=2 → score = 1/2*100 = 50.0
    assert iceland["sovereignty_score"] == 50.0

    # FRANCE has 2 reachable pages: 1 twitter_only, 1 no_social
    france = next(e for e in data["by_country"] if e["country_code"] == "FRANCE")
    # no_social=1, modern_only=0, reachable=2 → score = 1/2*100 = 50.0
    assert france["sovereignty_score"] == 50.0



# ---------------------------------------------------------------------------
# Tests for platform drilldown data
# ---------------------------------------------------------------------------

def test_query_platform_drilldowns_by_country_empty_db(empty_db: Path):
    """Should return empty drilldown data from an empty database."""
    conn = sqlite3.connect(empty_db)
    conn.row_factory = sqlite3.Row
    try:
        result = _query_platform_drilldowns_by_country(conn)
    finally:
        conn.close()

    assert result == {}


def test_query_platform_drilldowns_by_country_populated_db(populated_db: Path):
    """Should return page URLs and detected links grouped by country/platform."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        result = _query_platform_drilldowns_by_country(conn)
    finally:
        conn.close()

    assert result["ICELAND"]["twitter"] == [
        {
            "page_url": "https://example.is/page1",
            "detected_links": ["https://twitter.com/gov_is"],
        }
    ]
    assert result["ICELAND"]["mastodon"] == [
        {
            "page_url": "https://example.is/page3",
            "detected_links": ["https://mastodon.social/@gov_is"],
        }
    ]
    assert result["FRANCE"]["x"] == [
        {
            "page_url": "https://example.fr/page1",
            "detected_links": ["https://x.com/france_gov"],
        }
    ]


def test_query_platform_drilldowns_by_country_no_double_counting(
    duplicate_scan_db: Path,
):
    """Repeated scans of the same page should collapse into one drilldown row."""
    conn = sqlite3.connect(duplicate_scan_db)
    conn.row_factory = sqlite3.Row
    try:
        result = _query_platform_drilldowns_by_country(conn)
    finally:
        conn.close()

    assert result["ICELAND"]["twitter"] == [
        {
            "page_url": "https://example.is/page1",
            "detected_links": ["https://twitter.com/gov_is"],
        }
    ]


def test_query_metric_drilldowns_by_country_populated_db(populated_db: Path):
    """Should return evidence rows for social country-table metrics."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        result = _query_metric_drilldowns_by_country(conn)
    finally:
        conn.close()

    assert result["ICELAND"]["scanned"][0]["page_url"] == "https://example.is/page1"
    assert result["ICELAND"]["reachable"][0]["is_reachable"] is True
    assert result["ICELAND"]["legacy_only"][0]["social_tier"] == "twitter_only"
    assert result["ICELAND"]["modern"][0]["social_tier"] == "modern_only"


def test_build_stats_block_includes_drilldown_instructions(populated_db: Path):
    """Country table block should explain the hover/focus download workflow."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        summary = _query_summary(conn)
        by_country = _query_by_country(conn)
    finally:
        conn.close()

    block = _build_stats_block(summary, "2024-06-01 12:00 UTC", by_country=by_country)

    assert "Hover or focus any non-zero country-table count" in block
    assert "social-media-data.json" in block
    assert "artifact" in block


def test_generate_social_media_report_writes_platform_drilldowns(
    populated_db: Path, tmp_path: Path
):
    """Full report generation should expose platform drilldowns in the JSON file."""
    page_path = tmp_path / "social-media.md"
    page_path.write_text(_SOCIAL_MEDIA_PAGE_TEMPLATE)
    data_path = tmp_path / "social-media-data.json"

    result = generate_social_media_report(populated_db, page_path, data_path)

    assert result is True
    data = json.loads(data_path.read_text())
    assert data["platform_drilldowns"]["ICELAND"]["twitter"][0]["page_url"] == "https://example.is/page1"
    assert data["metric_drilldowns"]["ICELAND"]["legacy_only"][0]["social_tier"] == "twitter_only"
    assert (
        data["platform_drilldowns"]["ICELAND"]["mastodon"][0]["detected_links"][0]
        == "https://mastodon.social/@gov_is"
    )

    content = page_path.read_text()
    assert "Hover or focus any non-zero country-table count" in content


def test_build_interactive_block_uses_descriptive_site_link_labels():
    """Twitter/X drilldown details should use descriptive anchor text."""
    block = "".join(_build_interactive_block({"Iceland": ["https://example.is/about"]}))

    assert "_formatSiteLinkLabel" in block
    assert 'var linkLabel = _escHtml(_formatSiteLinkLabel(u));' in block
    assert '" homepage"' in block
    assert "_escHtml(u)" in block


# ---------------------------------------------------------------------------
# Tests for Top 100 functionality
# ---------------------------------------------------------------------------

def _make_top100_toon(path: Path, n: int = 5) -> None:
    """Write a minimal top-100 TOON fixture with *n* institutions."""
    domains = []
    for i in range(1, n + 1):
        domains.append({
            "canonical_domain": f"rank{i}.edu",
            "institution_name": f"Rank {i} Master Name",
            "ranking": i,
            "ranking_institution_name": f"Rank {i} University",
            "pages": [{"url": f"https://rank{i}.edu/", "is_root_page": True}],
        })
    data = {
        "version": "0.1-seed",
        "country": _TOP100_COUNTRY_CODE,
        "page_count": n,
        "domains": domains,
    }
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def top100_seeds_dir(tmp_path: Path) -> Path:
    """Seeds directory containing a minimal top-100 TOON fixture."""
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    _make_top100_toon(seeds_dir / "usa-edu-top100.toon", n=5)
    return seeds_dir


@pytest.fixture
def top100_db(tmp_path: Path) -> Path:
    """DB with scan results for the top-100 country code."""
    db_path = tmp_path / "test.db"
    initialize_schema(f"sqlite:///{db_path}")
    conn = sqlite3.connect(db_path)
    try:
        rows = [
            (
                "https://rank1.edu/", _TOP100_COUNTRY_CODE, "scan-001", 1,
                '["https://twitter.com/rank1"]', '[]', '[]', '[]', '[]', '[]',
                "twitter_only", "2024-06-01T10:00:00+00:00",
            ),
            (
                "https://rank2.edu/", _TOP100_COUNTRY_CODE, "scan-001", 1,
                '[]', '[]', '["https://bsky.app/profile/rank2"]', '[]', '[]', '[]',
                "modern_only", "2024-06-01T10:01:00+00:00",
            ),
            (
                "https://rank3.edu/", _TOP100_COUNTRY_CODE, "scan-001", 0,
                '[]', '[]', '[]', '[]', '[]', '[]',
                "unreachable", "2024-06-01T10:02:00+00:00",
            ),
        ]
        for row in rows:
            conn.execute(
                """
                INSERT INTO url_social_media_results
                (url, country_code, scan_id, is_reachable,
                 twitter_links, x_links, bluesky_links, mastodon_links,
                 facebook_links, linkedin_links, social_tier, scanned_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


# --- _load_top100_institution_metadata ---

def test_load_top100_metadata_missing_dir(tmp_path: Path):
    """Should return empty list when seeds dir does not exist."""
    result = _load_top100_institution_metadata(tmp_path / "nonexistent")
    assert result == []


def test_load_top100_metadata_missing_file(tmp_path: Path):
    """Should return empty list when usa-edu-top100.toon is absent."""
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    result = _load_top100_institution_metadata(seeds_dir)
    assert result == []


def test_load_top100_metadata_sorted_by_rank(top100_seeds_dir: Path):
    """Returned list must be sorted ascending by rank."""
    result = _load_top100_institution_metadata(top100_seeds_dir)
    assert len(result) == 5
    ranks = [r["rank"] for r in result]
    assert ranks == sorted(ranks)


def test_load_top100_metadata_fields(top100_seeds_dir: Path):
    """Each entry must contain rank, institution_name, canonical_domain, url."""
    result = _load_top100_institution_metadata(top100_seeds_dir)
    first = result[0]
    assert first["rank"] == 1
    assert first["institution_name"] == "Rank 1 University"   # ranking_institution_name
    assert first["canonical_domain"] == "rank1.edu"
    assert first["url"] == "https://rank1.edu/"


def test_load_top100_metadata_falls_back_to_master_name(tmp_path: Path):
    """When ranking_institution_name is absent, falls back to institution_name."""
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    data = {
        "country": _TOP100_COUNTRY_CODE,
        "page_count": 1,
        "domains": [{
            "canonical_domain": "test.edu",
            "institution_name": "Test University",
            "ranking": 1,
            # no ranking_institution_name
            "pages": [{"url": "https://test.edu/", "is_root_page": True}],
        }],
    }
    (seeds_dir / "usa-edu-top100.toon").write_text(json.dumps(data))
    result = _load_top100_institution_metadata(seeds_dir)
    assert len(result) == 1
    assert result[0]["institution_name"] == "Test University"


# --- _query_top100_results ---

def test_query_top100_results_empty_db(empty_db: Path):
    """Should return empty dict when no top-100 rows exist."""
    conn = sqlite3.connect(empty_db)
    conn.row_factory = sqlite3.Row
    try:
        result = _query_top100_results(conn)
    finally:
        conn.close()
    assert result == {}


def test_query_top100_results_populated(top100_db: Path):
    """Should return a dict keyed by URL for top-100 scan results."""
    conn = sqlite3.connect(top100_db)
    conn.row_factory = sqlite3.Row
    try:
        result = _query_top100_results(conn)
    finally:
        conn.close()

    assert len(result) == 3
    assert "https://rank1.edu/" in result
    assert result["https://rank1.edu/"]["social_tier"] == "twitter_only"
    assert result["https://rank2.edu/"]["social_tier"] == "modern_only"
    assert result["https://rank3.edu/"]["is_reachable"] == 0


def test_query_top100_results_only_includes_top100_country(populated_db: Path):
    """Results from other country codes must not appear in the top-100 query."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        result = _query_top100_results(conn)
    finally:
        conn.close()
    # populated_db has ICELAND and FRANCE rows, not USA_EDU_TOP100
    assert result == {}


def test_query_top100_results_deduplicates_by_url(tmp_path: Path):
    """When a URL appears in multiple scan batches, only the most recent row is kept."""
    db_path = tmp_path / "test.db"
    initialize_schema(f"sqlite:///{db_path}")
    conn = sqlite3.connect(db_path)
    try:
        for scan_id, tier, ts in [
            ("scan-001", "twitter_only", "2024-06-01T10:00:00"),
            ("scan-002", "no_social",   "2024-06-02T10:00:00"),
        ]:
            conn.execute(
                """
                INSERT INTO url_social_media_results
                (url, country_code, scan_id, is_reachable,
                 twitter_links, x_links, bluesky_links, mastodon_links,
                 facebook_links, linkedin_links, social_tier, scanned_at)
                VALUES (?, ?, ?, 1, '[]', '[]', '[]', '[]', '[]', '[]', ?, ?)
                """,
                ("https://rank1.edu/", _TOP100_COUNTRY_CODE, scan_id, tier, ts),
            )
        conn.commit()
        conn.row_factory = sqlite3.Row
        result = _query_top100_results(conn)
    finally:
        conn.close()

    assert len(result) == 1
    assert result["https://rank1.edu/"]["social_tier"] == "no_social"


# --- _build_top100_section ---

def test_build_top100_section_empty_meta():
    """Should return empty list when institution_meta is empty."""
    assert _build_top100_section([], {}) == []


def test_build_top100_section_renders_all_institutions():
    """Should render one row per institution regardless of scan status."""
    meta = [
        {"rank": 1, "institution_name": "Alpha U", "url": "https://alpha.edu/"},
        {"rank": 2, "institution_name": "Beta U", "url": "https://beta.edu/"},
    ]
    url_results = {
        "https://alpha.edu/": {
            "social_tier": "twitter_only",
            "is_reachable": 1,
            "twitter_links": '["https://twitter.com/alpha"]',
            "x_links": "[]",
            "facebook_links": "[]",
            "linkedin_links": "[]",
            "bluesky_links": "[]",
            "mastodon_links": "[]",
        },
    }
    lines = _build_top100_section(meta, url_results)
    text = "\n".join(lines)

    assert "Alpha U" in text
    assert "Beta U" in text
    assert "⚠️ Legacy-only" in text          # alpha.edu tier
    assert "*Not yet scanned*" in text       # beta.edu not in url_results


def test_build_top100_section_includes_heading():
    """Should emit a '## Top 100 Universities' section heading."""
    meta = [{"rank": 1, "institution_name": "Test U", "url": "https://test.edu/"}]
    lines = _build_top100_section(meta, {})
    text = "\n".join(lines)
    assert "## Top 100 Universities" in text


def test_build_top100_section_unreachable_tier():
    """Unreachable pages should show the unreachable tier label."""
    meta = [{"rank": 1, "institution_name": "Down U", "url": "https://down.edu/"}]
    url_results = {
        "https://down.edu/": {
            "social_tier": "no_social",
            "is_reachable": 0,
            "twitter_links": "[]", "x_links": "[]",
            "facebook_links": "[]", "linkedin_links": "[]",
            "bluesky_links": "[]", "mastodon_links": "[]",
        },
    }
    lines = _build_top100_section(meta, url_results)
    text = "\n".join(lines)
    assert "❌ Unreachable" in text


def test_build_top100_section_scanned_count_summary():
    """Footer line should report the number of scanned vs total institutions."""
    meta = [
        {"rank": 1, "institution_name": "A U", "url": "https://a.edu/"},
        {"rank": 2, "institution_name": "B U", "url": "https://b.edu/"},
        {"rank": 3, "institution_name": "C U", "url": "https://c.edu/"},
    ]
    url_results = {
        "https://a.edu/": {
            "social_tier": "no_social", "is_reachable": 1,
            "twitter_links": "[]", "x_links": "[]",
            "facebook_links": "[]", "linkedin_links": "[]",
            "bluesky_links": "[]", "mastodon_links": "[]",
        },
    }
    lines = _build_top100_section(meta, url_results)
    text = "\n".join(lines)
    # 1 of 3 scanned
    assert "1 of 3" in text


# --- _build_stats_block includes top100 section ---

def test_build_stats_block_with_top100_meta():
    """Stats block should include the Top 100 table when top100_meta is provided."""
    summary = {
        "total_batches": 1,
        "total_scanned": 100,
        "total_reachable": 90,
        "twitter_pages": 10,
        "x_pages": 5,
        "bluesky_pages": 3,
        "mastodon_pages": 2,
        "facebook_pages": 8,
        "linkedin_pages": 7,
        "last_scan": "2024-06-01T12:00:00",
    }
    meta = [{"rank": 1, "institution_name": "Harvard University", "url": "https://harvard.edu/"}]
    block = _build_stats_block(
        summary,
        "2024-06-01 12:00 UTC",
        top100_meta=meta,
        top100_results={},
    )
    assert "## Top 100 Universities" in block
    assert "Harvard University" in block
    assert "*Not yet scanned*" in block


def test_build_stats_block_without_top100_meta():
    """Stats block should not include the Top 100 section when top100_meta is absent."""
    summary = {
        "total_batches": 1,
        "total_scanned": 100,
        "total_reachable": 90,
        "twitter_pages": 10, "x_pages": 5, "bluesky_pages": 3,
        "mastodon_pages": 2, "facebook_pages": 8, "linkedin_pages": 7,
        "last_scan": "2024-06-01T12:00:00",
    }
    block = _build_stats_block(summary, "2024-06-01 12:00 UTC")
    assert "## Top 100 Universities" not in block


# --- Institution Group table heading ---

def test_stats_block_uses_institution_group_heading(populated_db: Path):
    """The per-seed table should be titled 'Social Media Scan by Institution Group'."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        summary = _query_summary(conn)
        by_country = _query_by_country(conn)
    finally:
        conn.close()

    block = _build_stats_block(summary, "2024-06-01 12:00 UTC", by_country=by_country)
    assert "## Social Media Scan by Institution Group" in block
    assert "## Social Media Scan by Country" not in block


# --- Full report integration with top100 ---

def test_generate_social_media_report_with_top100(
    top100_db: Path, top100_seeds_dir: Path, tmp_path: Path
):
    """Full report generation should include Top 100 section when seed file exists."""
    page_path = tmp_path / "social-media.md"
    page_path.write_text(_SOCIAL_MEDIA_PAGE_TEMPLATE)
    data_path = tmp_path / "social-media-data.json"

    result = generate_social_media_report(top100_db, page_path, data_path, top100_seeds_dir)

    assert result is True
    content = page_path.read_text()
    assert "## Top 100 Universities" in content
    assert "Rank 1 University" in content

    data = json.loads(data_path.read_text())
    assert "top100_institutions" in data
    assert len(data["top100_institutions"]) == 5


def test_generate_social_media_report_top100_json_fields(
    top100_db: Path, top100_seeds_dir: Path, tmp_path: Path
):
    """JSON data file top100_institutions should contain expected fields."""
    page_path = tmp_path / "social-media.md"
    page_path.write_text(_SOCIAL_MEDIA_PAGE_TEMPLATE)
    data_path = tmp_path / "social-media-data.json"

    generate_social_media_report(top100_db, page_path, data_path, top100_seeds_dir)

    data = json.loads(data_path.read_text())
    inst = data["top100_institutions"][0]
    assert inst["rank"] == 1
    assert "institution_name" in inst
    assert "canonical_domain" in inst
    assert "url" in inst
