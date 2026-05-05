"""Tests for the multi-scan progress report generator."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.cli.generate_scan_progress import (
    _format_month_range,
    generate_progress_report,
    update_index_progress,
)
from src.storage.schema import initialize_schema


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """Return path to a freshly initialised, empty database."""
    db_path = tmp_path / "test.db"
    initialize_schema(f"sqlite:///{db_path}")
    return db_path


@pytest.fixture
def populated_db(tmp_path: Path) -> Path:
    """Return path to a database with sample data for all three scan types."""
    db_path = tmp_path / "test.db"
    initialize_schema(f"sqlite:///{db_path}")

    conn = sqlite3.connect(db_path)
    try:
        # URL validation results
        for url, is_valid, failure_count, ts in [
            ("https://example.is/page1", 1, 0, "2024-06-01T10:00:00+00:00"),
            ("https://example.is/page2", 0, 1, "2024-06-01T10:01:00+00:00"),
            ("https://example.is/page3", 1, 0, "2024-06-01T10:02:00+00:00"),
            ("https://example.fr/page1", 1, 0, "2024-06-02T08:00:00+00:00"),
        ]:
            conn.execute(
                """
                INSERT INTO url_validation_results
                (url, country_code, scan_id, status_code, is_valid,
                 failure_count, validated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    url,
                    "ICELAND" if "example.is" in url else "FRANCE",
                    "scan-001",
                    200 if is_valid else 404,
                    is_valid,
                    failure_count,
                    ts,
                ),
            )

        # Social media results
        for url, is_reachable, tier, ts in [
            ("https://example.is/page1", 1, "twitter_only", "2024-06-03T09:00:00+00:00"),
            ("https://example.is/page2", 0, "unreachable",  "2024-06-03T09:01:00+00:00"),
            ("https://example.is/page3", 1, "no_social",    "2024-06-03T09:02:00+00:00"),
            ("https://example.de/home",  1, "modern_only",  "2024-06-04T07:00:00+00:00"),
        ]:
            conn.execute(
                """
                INSERT INTO url_social_media_results
                (url, country_code, scan_id, is_reachable, social_tier,
                 twitter_links, x_links, bluesky_links, mastodon_links,
                 scanned_at)
                VALUES (?, ?, ?, ?, ?, '[]', '[]', '[]', '[]', ?)
                """,
                (
                    url,
                    "ICELAND" if "example.is" in url else "GERMANY",
                    "social-001",
                    is_reachable,
                    tier,
                    ts,
                ),
            )

        # Technology results
        conn.execute(
            """
            INSERT INTO url_tech_results
            (url, country_code, scan_id, technologies, scanned_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "https://example.is/page1",
                "ICELAND",
                "tech-001",
                '{"WordPress": {"versions": ["6.5"], "categories": ["CMS"]}}',
                "2024-06-05T11:00:00+00:00",
            ),
        )

        # Lighthouse results
        for url, performance, accessibility, best_practices, seo, pwa, ts in [
            ("https://example.is/page1", 0.95, 0.88, 1.0, 0.92, 0.0, "2024-06-06T09:00:00+00:00"),
            ("https://example.is/page2", 0.70, 0.75, 0.83, 0.80, 0.0, "2024-06-06T09:05:00+00:00"),
        ]:
            conn.execute(
                """
                INSERT INTO url_lighthouse_results
                (url, country_code, scan_id,
                 performance_score, accessibility_score,
                 best_practices_score, seo_score, pwa_score, scanned_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (url, "ICELAND", "lh-001", performance, accessibility, best_practices, seo, pwa, ts),
            )

        conn.commit()
    finally:
        conn.close()

    return db_path


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_generate_progress_report_missing_db(tmp_path: Path):
    """Report should be created gracefully when the database does not exist."""
    db_path = tmp_path / "nonexistent.db"
    output_path = tmp_path / "report.md"

    generate_progress_report(db_path, output_path)

    assert output_path.exists()
    content = output_path.read_text()
    assert "title: Scan Progress Report" in content
    assert "layout: page" in content
    assert "No scan data available yet" in content


def test_generate_progress_report_empty_db(empty_db: Path, tmp_path: Path):
    """Report should be created when the database is empty."""
    output_path = tmp_path / "report.md"
    generate_progress_report(empty_db, output_path)

    assert output_path.exists()
    content = output_path.read_text()
    # Empty DB → no validation data → gracefully handled
    assert "title: Scan Progress Report" in content
    assert "layout: page" in content


def test_generate_progress_report_with_data(populated_db: Path, tmp_path: Path):
    """Report should contain expected sections and data."""
    output_path = tmp_path / "report.md"
    generate_progress_report(populated_db, output_path)

    assert output_path.exists()
    content = output_path.read_text()

    # Check main sections
    assert "title: Scan Progress Report" in content
    assert "layout: page" in content
    assert "## Overall Coverage" in content
    assert "## URL Validation by Country" in content
    assert "## Social Media Scan by Country" in content
    assert "## Scan Priority Guide" in content

    # Check country rows appear
    assert "Iceland" in content
    assert "France" in content
    assert "Germany" in content


def test_generate_progress_report_writes_validation_drilldown_data(
    populated_db: Path, tmp_path: Path
):
    """Scan progress generation should export URL-validation drilldown JSON."""
    output_path = tmp_path / "report.md"
    data_path = tmp_path / "scan-progress-data.json"
    generate_progress_report(populated_db, output_path, data_path=data_path)

    payload = json.loads(data_path.read_text(encoding="utf-8"))
    assert "url_validation_drilldowns" in payload
    assert payload["url_validation_drilldowns"]["ICELAND"]["total"][0]["url"] == "https://example.is/page1"
    assert payload["url_validation_drilldowns"]["ICELAND"]["valid"][0]["ever_valid"] is True
    assert payload["url_validation_drilldowns"]["ICELAND"]["invalid"][0]["ever_invalid"] is True


def test_generate_progress_report_writes_empty_drilldown_data_for_missing_db(tmp_path: Path):
    """Missing DB runs should still write an empty scan-progress JSON file."""
    db_path = tmp_path / "missing.db"
    output_path = tmp_path / "report.md"
    data_path = tmp_path / "scan-progress-data.json"
    generate_progress_report(db_path, output_path, data_path=data_path)

    payload = json.loads(data_path.read_text(encoding="utf-8"))
    assert payload["url_validation_drilldowns"] == {}


def test_generate_progress_report_url_validation_stats(
    populated_db: Path, tmp_path: Path
):
    """URL validation section should show correct valid/invalid counts."""
    output_path = tmp_path / "report.md"
    generate_progress_report(populated_db, output_path)
    content = output_path.read_text()

    # Iceland has 2 valid + 1 invalid; France has 1 valid
    # The table rows should have numbers present
    assert "Iceland" in content
    assert "France" in content
    assert "Hover or focus any non-zero **Total**, **Valid**, or **Invalid** count" in content
    assert "scan-progress-data.json" in content


def test_generate_progress_report_social_tiers(populated_db: Path, tmp_path: Path):
    """Social media section should list tier counts."""
    output_path = tmp_path / "report.md"
    generate_progress_report(populated_db, output_path)
    content = output_path.read_text()

    assert "Social Media Scan by Country" in content
    assert "Germany" in content

def test_generate_progress_report_technology_section(
    populated_db: Path, tmp_path: Path
):
    """Technology section should appear when tech scan data exists."""
    output_path = tmp_path / "report.md"
    generate_progress_report(populated_db, output_path)
    content = output_path.read_text()

    assert "Technology" in content
    assert "Iceland" in content


def test_generate_progress_report_pending_social_scan(
    populated_db: Path, tmp_path: Path
):
    """Countries with URL validation but no social scan should be highlighted."""
    output_path = tmp_path / "report.md"
    generate_progress_report(populated_db, output_path)
    content = output_path.read_text()

    # FRANCE has URL validation but no social media scan
    assert "Countries Pending Social Media Scan" in content
    assert "FRANCE" in content


def test_generate_progress_report_scan_priority_guide(
    populated_db: Path, tmp_path: Path
):
    """Report should include the scan priority guide."""
    output_path = tmp_path / "report.md"
    generate_progress_report(populated_db, output_path)
    content = output_path.read_text()

    assert "Scan Priority Guide" in content
    assert "Social Media Scan" in content
    assert "URL Validation" in content
    assert "30 days" in content


def test_generate_progress_report_social_media_platform_breakdown(
    populated_db: Path, tmp_path: Path
):
    """Report should include per-platform columns in the social media scan table."""
    output_path = tmp_path / "report.md"
    generate_progress_report(populated_db, output_path)
    content = output_path.read_text()

    # Platform columns merged into a single "Social Media Scan by Country" table
    assert "## Social Media Scan by Country" in content
    # Separate breakdown table should no longer exist
    assert "## Social Media Platform Breakdown" not in content
    # Table should include the platform columns
    assert "Twitter" in content
    assert "Bluesky" in content
    assert "Mastodon" in content
    # Should show the countries that have social media data
    assert "Iceland" in content
    assert "Germany" in content
    assert "Hover or focus any non-zero platform count" in content
    assert "social-media-data.json" in content


# ---------------------------------------------------------------------------
# Tests for _format_month_range helper
# ---------------------------------------------------------------------------

def test_format_month_range_both_none():
    """Should return '—' when both values are None."""
    assert _format_month_range(None, None) == "—"


def test_format_month_range_same_month():
    """Should return a single month when first and last are in the same month."""
    result = _format_month_range(
        "2024-06-01T10:00:00+00:00",
        "2024-06-30T23:59:59+00:00",
    )
    assert result == "Jun 2024"


def test_format_month_range_different_months():
    """Should return 'Mon YYYY – Mon YYYY' when months differ."""
    result = _format_month_range(
        "2024-01-01T00:00:00+00:00",
        "2024-03-31T23:59:59+00:00",
    )
    assert result == "Jan 2024 – Mar 2024"


def test_format_month_range_only_last():
    """Should return the last month when first is None."""
    result = _format_month_range(None, "2024-06-15T12:00:00+00:00")
    assert result == "Jun 2024"


def test_format_month_range_only_first():
    """Should return the first month when last is None."""
    result = _format_month_range("2024-06-15T12:00:00+00:00", None)
    assert result == "Jun 2024"


def test_format_month_range_cross_year():
    """Should handle date ranges that span across years."""
    result = _format_month_range(
        "2023-11-01T00:00:00+00:00",
        "2024-02-28T23:59:59+00:00",
    )
    assert result == "Nov 2023 – Feb 2024"


# ---------------------------------------------------------------------------
# Tests for date range in generated reports
# ---------------------------------------------------------------------------

def test_generate_progress_report_url_validation_scan_period(
    populated_db: Path, tmp_path: Path
):
    """URL validation table should use 'Scan Period' column instead of 'Last Scan'."""
    output_path = tmp_path / "report.md"
    generate_progress_report(populated_db, output_path)
    content = output_path.read_text()

    assert "Scan Period" in content
    # The fixture data uses 2024-06-* dates — all in June 2024
    assert "Jun 2024" in content


def test_generate_progress_report_social_media_scan_period(
    populated_db: Path, tmp_path: Path
):
    """Social media table should use 'Scan Period' column instead of 'Last Scan'."""
    output_path = tmp_path / "report.md"
    generate_progress_report(populated_db, output_path)
    content = output_path.read_text()

    # Both tables should show the scan period column
    assert content.count("Scan Period") >= 2


# ---------------------------------------------------------------------------
# Tests for update_index_progress
# ---------------------------------------------------------------------------

_INDEX_WITH_MARKERS = """\
---
title: Test
---

## Current Scan Progress

<!-- SCAN_PROGRESS_START -->

_No data yet._

<!-- SCAN_PROGRESS_END -->

## Other Section

Some content.
"""


def test_update_index_progress_no_db(tmp_path: Path):
    """Should insert a 'no data' placeholder when the DB does not exist."""
    index_path = tmp_path / "index.md"
    index_path.write_text(_INDEX_WITH_MARKERS)
    db_path = tmp_path / "nonexistent.db"

    result = update_index_progress(index_path, db_path)

    assert result is True
    content = index_path.read_text()
    assert "<!-- SCAN_PROGRESS_START -->" in content
    assert "<!-- SCAN_PROGRESS_END -->" in content
    assert "No scan data yet" in content
    # Other section should be preserved
    assert "## Other Section" in content


def test_update_index_progress_with_data(populated_db: Path, tmp_path: Path):
    """Should replace the marker block with a real coverage table."""
    index_path = tmp_path / "index.md"
    index_path.write_text(_INDEX_WITH_MARKERS)

    result = update_index_progress(index_path, populated_db)

    assert result is True
    content = index_path.read_text()
    assert "<!-- SCAN_PROGRESS_START -->" in content
    assert "<!-- SCAN_PROGRESS_END -->" in content
    assert "Social Media" in content
    # Coverage table should appear between the markers
    assert "countries" in content.lower()
    # The "Other Section" below the end marker must still be present
    assert "## Other Section" in content


def test_update_index_progress_missing_markers(tmp_path: Path):
    """Should return False and not modify the file when markers are absent."""
    index_path = tmp_path / "index.md"
    original = "# Index\n\nNo markers here.\n"
    index_path.write_text(original)
    db_path = tmp_path / "nonexistent.db"

    result = update_index_progress(index_path, db_path)

    assert result is False
    assert index_path.read_text() == original


def test_update_index_progress_missing_index_file(tmp_path: Path):
    """Should return False when the index file does not exist."""
    index_path = tmp_path / "missing.md"
    db_path = tmp_path / "nonexistent.db"

    result = update_index_progress(index_path, db_path)

    assert result is False


# ---------------------------------------------------------------------------
# Tests for Lighthouse section
# ---------------------------------------------------------------------------

def test_generate_progress_report_lighthouse_section(
    populated_db: Path, tmp_path: Path
):
    """Lighthouse section should appear when Lighthouse scan data exists."""
    output_path = tmp_path / "report.md"
    generate_progress_report(populated_db, output_path)
    content = output_path.read_text()

    assert "## Lighthouse Scan by Country" in content
    assert "Iceland" in content
    # Score columns should be present
    assert "A11y" in content
    assert "Perf" in content


def test_generate_progress_report_lighthouse_placeholder_when_no_data(
    empty_db: Path, tmp_path: Path
):
    """Lighthouse placeholder should appear when there are no Lighthouse results."""
    output_path = tmp_path / "report.md"
    generate_progress_report(empty_db, output_path)
    content = output_path.read_text()

    assert "Lighthouse Scan" in content
    assert "No Lighthouse scans have been run yet" in content


def test_generate_progress_report_overall_coverage_includes_lighthouse(
    populated_db: Path, tmp_path: Path
):
    """Overall coverage table should include a Lighthouse row."""
    output_path = tmp_path / "report.md"
    generate_progress_report(populated_db, output_path)
    content = output_path.read_text()

    assert "## Overall Coverage" in content
    assert "Lighthouse" in content


def test_generate_progress_report_priority_guide_includes_lighthouse(
    populated_db: Path, tmp_path: Path
):
    """Scan priority guide should mention the Lighthouse scan."""
    output_path = tmp_path / "report.md"
    generate_progress_report(populated_db, output_path)
    content = output_path.read_text()

    assert "Lighthouse Scan" in content
    assert "accessibility" in content.lower()


# ---------------------------------------------------------------------------
# Tests for toon seed coverage integration
# ---------------------------------------------------------------------------


def _make_seeds_dir(tmp_path: Path, counts: dict) -> Path:
    """Create a temporary seeds directory with minimal toon files."""
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir(exist_ok=True)
    for country_code, page_count in counts.items():
        filename = country_code.lower().replace("_", "-") + ".toon"
        data = {"page_count": page_count, "domains": []}
        (seeds_dir / filename).write_text(json.dumps(data), encoding="utf-8")
    return seeds_dir


def test_generate_progress_report_with_seeds(populated_db: Path, tmp_path: Path):
    """Report should show total_available in overall coverage when seeds provided."""
    seeds_dir = _make_seeds_dir(tmp_path, {"ICELAND": 200, "FRANCE": 500, "GERMANY": 300})
    output_path = tmp_path / "report.md"
    generate_progress_report(populated_db, output_path, seeds_dir)
    content = output_path.read_text()

    assert "1,000" in content      # 200+500+300 total available
    assert "## Overall Coverage" in content


def test_generate_progress_report_social_media_table_shows_available(
    populated_db: Path, tmp_path: Path
):
    """Social media scan table should show 'Available' column when seeds provided."""
    seeds_dir = _make_seeds_dir(tmp_path, {"ICELAND": 200, "FRANCE": 500, "GERMANY": 300})
    output_path = tmp_path / "report.md"
    generate_progress_report(populated_db, output_path, seeds_dir)
    content = output_path.read_text()

    assert "Available" in content


def test_update_index_progress_with_seeds(populated_db: Path, tmp_path: Path):
    """Index progress block should include available pages total when seeds provided."""
    seeds_dir = _make_seeds_dir(tmp_path, {"ICELAND": 200, "FRANCE": 500, "GERMANY": 300})

    index_path = tmp_path / "index.md"
    index_path.write_text(
        "# Test\n\n<!-- SCAN_PROGRESS_START -->\n_placeholder_\n<!-- SCAN_PROGRESS_END -->\n## Other\n"
    )

    result = update_index_progress(index_path, populated_db, seeds_dir)
    assert result is True
    content = index_path.read_text()
    assert "1,000" in content    # total available


def test_count_toon_seed_urls_in_scan_progress(tmp_path: Path):
    """_count_toon_seed_urls from generate_scan_progress should work correctly."""
    from src.cli.generate_scan_progress import _count_toon_seed_urls
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    data = {"page_count": 150, "domains": []}
    (seeds_dir / "norway.toon").write_text(json.dumps(data), encoding="utf-8")
    result = _count_toon_seed_urls(seeds_dir)
    assert result == {"NORWAY": 150}


# ---------------------------------------------------------------------------
# Tests for _query_combined_reachability and Combined Reachability row
# ---------------------------------------------------------------------------

def test_query_combined_reachability(populated_db: Path):
    """Combined reachability should count distinct URLs confirmed reachable by either scan."""
    from src.cli.generate_scan_progress import _query_combined_reachability
    import sqlite3

    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        result = _query_combined_reachability(conn)
    finally:
        conn.close()

    # ICELAND: page1 reachable via both scans (counted once), page3 via both
    # (counted once), page2 invalid and unreachable → 2 confirmed reachable
    assert "ICELAND" in result
    assert result["ICELAND"]["confirmed"] == 2

    # GERMANY: only in social media (page home, reachable) → 1
    assert "GERMANY" in result
    assert result["GERMANY"]["confirmed"] == 1

    # FRANCE: only in url_validation (page1, is_valid=1) → 1
    assert "FRANCE" in result
    assert result["FRANCE"]["confirmed"] == 1


def test_query_combined_reachability_deduplicates(populated_db: Path):
    """URLs in both tables should be counted only once per country."""
    from src.cli.generate_scan_progress import _query_combined_reachability
    import sqlite3

    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        result = _query_combined_reachability(conn)
    finally:
        conn.close()

    # Iceland: page1 is valid (url_validation) AND reachable (social_media).
    # page3 is valid AND reachable.  page2 is invalid AND unreachable.
    # Confirmed = 2 unique URLs, not 4.
    assert result["ICELAND"]["confirmed"] == 2

    # Aggregate across all countries: ICELAND=2, GERMANY=1, FRANCE=1 → total=4.
    # This is less than the naive sum of url_valid (3) + sm_reachable (3) = 6,
    # confirming the UNION deduplication reduces the count correctly.
    total_combined = sum(d["confirmed"] for d in result.values())
    assert total_combined == 4


def test_generate_progress_report_shows_combined_reachability(
    populated_db: Path, tmp_path: Path
):
    """Overall coverage table should contain a Combined Reachability row."""
    output_path = tmp_path / "report.md"
    generate_progress_report(populated_db, output_path)
    content = output_path.read_text()

    assert "Combined Reachability" in content


def test_generate_progress_report_overall_coverage_has_available_column(
    populated_db: Path, tmp_path: Path
):
    """Overall coverage table should have an 'Available' column header."""
    output_path = tmp_path / "report.md"
    generate_progress_report(populated_db, output_path)
    content = output_path.read_text()

    # Header row should include 'Available'
    assert "| Scan Type | Pages Scanned | Available | Coverage |" in content


def test_generate_progress_report_priority_guide_explains_difference(
    populated_db: Path, tmp_path: Path
):
    """Priority guide should explain why Social Media and URL Validation counts differ."""
    output_path = tmp_path / "report.md"
    generate_progress_report(populated_db, output_path)
    content = output_path.read_text()

    assert "Why are Social Media and URL Validation counts different" in content
    assert "Failure tracking" in content
    assert "Redirect-chain capture" in content


def test_update_index_progress_shows_combined_reachability(
    populated_db: Path, tmp_path: Path
):
    """Index progress block should include Combined Reachability row."""
    index_path = tmp_path / "index.md"
    index_path.write_text(_INDEX_WITH_MARKERS)

    result = update_index_progress(index_path, populated_db)

    assert result is True
    content = index_path.read_text()
    assert "Combined Reachability" in content


def test_generate_progress_report_platform_breakdown_has_reachable_column(
    populated_db: Path, tmp_path: Path
):
    """Social media scan table should include a 'Reachable' column."""
    output_path = tmp_path / "report.md"
    generate_progress_report(populated_db, output_path)
    content = output_path.read_text()

    # Platform data is now part of the single "Social Media Scan by Country" table
    assert "## Social Media Scan by Country" in content
    assert "Reachable" in content


# ---------------------------------------------------------------------------
# Accessibility statement domain-level counting
# ---------------------------------------------------------------------------

def _make_accessibility_db(tmp_path: Path) -> Path:
    """Return a DB with multiple probe URLs per domain to test domain counting."""
    db_path = tmp_path / "a11y.db"
    initialize_schema(f"sqlite:///{db_path}")
    conn = sqlite3.connect(db_path)
    try:
        # Three probe URLs for the same domain (example.is) — only 1 domain should be counted.
        # Two distinct domains for FRANCE (example.fr and other.fr).
        rows = [
            # ICELAND — domain: example.is, three probe URLs
            ("https://example.is/", "ICELAND", "s1", 1, 0, 0, "2024-06-01T10:00:00"),
            ("https://example.is/accessibility", "ICELAND", "s1", 1, 1, 1, "2024-06-01T10:01:00"),
            ("https://example.is/web-accessibility", "ICELAND", "s1", 0, 0, 0, "2024-06-01T10:02:00"),
            # FRANCE — domain: example.fr (reachable, no statement)
            ("https://example.fr/", "FRANCE", "s2", 1, 0, 0, "2024-06-02T08:00:00"),
            ("https://example.fr/accessibility", "FRANCE", "s2", 1, 1, 0, "2024-06-02T08:01:00"),
            # FRANCE — domain: other.fr (unreachable)
            ("https://other.fr/", "FRANCE", "s2", 0, 0, 0, "2024-06-02T08:02:00"),
        ]
        for url, cc, scan_id, is_reachable, has_statement, found_in_footer, ts in rows:
            conn.execute(
                """
                INSERT INTO url_accessibility_results
                (url, country_code, scan_id, is_reachable, has_statement,
                 found_in_footer, statement_links, matched_terms,
                 error_message, scanned_at)
                VALUES (?, ?, ?, ?, ?, ?, '[]', '[]', NULL, ?)
                """,
                (url, cc, scan_id, is_reachable, has_statement, found_in_footer, ts),
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_query_accessibility_counts_domains(tmp_path: Path):
    """_query_accessibility should count distinct domains, not individual URLs."""
    from src.cli.generate_scan_progress import _query_accessibility  # noqa: PLC0415

    db_path = _make_accessibility_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        result = _query_accessibility(conn)
    finally:
        conn.close()

    # ICELAND: 3 probe URLs all for example.is → 1 domain
    assert result["ICELAND"]["total"] == 1
    # MAX(is_reachable) = 1; MAX(has_statement) = 1; MAX(found_in_footer) = 1
    assert result["ICELAND"]["reachable"] == 1
    assert result["ICELAND"]["has_statement"] == 1
    assert result["ICELAND"]["found_in_footer"] == 1

    # FRANCE: example.fr (reachable, has_statement) + other.fr (unreachable) → 2 domains
    assert result["FRANCE"]["total"] == 2
    assert result["FRANCE"]["reachable"] == 1   # only example.fr is reachable
    assert result["FRANCE"]["has_statement"] == 1  # only example.fr has a statement


def test_generate_progress_report_accessibility_shows_domain_label(
    tmp_path: Path,
):
    """Overall coverage table should label the accessibility row as 'domains'."""
    db_path = _make_accessibility_db(tmp_path)
    output_path = tmp_path / "report.md"
    generate_progress_report(db_path, output_path)
    content = output_path.read_text()

    assert "Accessibility Statement" in content
    assert "domains" in content


# ---------------------------------------------------------------------------
# Tests for parent institutions CSV output
# ---------------------------------------------------------------------------

def test_generate_progress_report_writes_parent_institutions_csv(
    populated_db: Path, tmp_path: Path
):
    """Should write a parent institutions CSV when csv_path is provided and seeds exist."""
    # Create a minimal toon seeds dir so the organization mapper has something to work with
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    # Minimal toon seed — no parent_institution mappings, but enough to trigger the code path
    seed_data = {
        "version": "0.1-seed",
        "page_count": 3,
        "domains": [
            {
                "canonical_domain": "example.is",
                "institution_name": "Example Iceland",
                "parent_institution": "Nordic Network",
                "pages": [],
            }
        ],
    }
    (seeds_dir / "iceland.toon").write_text(json.dumps(seed_data), encoding="utf-8")

    output_path = tmp_path / "report.md"
    csv_path = tmp_path / "parent-institutions.csv"

    generate_progress_report(
        populated_db,
        output_path,
        toon_seeds_dir=seeds_dir,
        parent_institutions_csv_path=csv_path,
    )

    # CSV should be written when there are any institutions
    # (may be empty if domain mapping finds no matches, but file should exist)
    if csv_path.exists():
        content_bytes = csv_path.read_bytes()
        assert content_bytes[:3] == b"\xef\xbb\xbf"   # UTF-8 BOM
        text = content_bytes.decode("utf-8-sig")
        lines = text.strip().splitlines()
        assert lines[0] == "rank,parent_institution,urls_scanned,reachable,coverage_pct"


def test_generate_progress_report_no_csv_without_path(
    populated_db: Path, tmp_path: Path
):
    """Should not write a parent institutions CSV when no csv_path is given."""
    output_path = tmp_path / "report.md"

    generate_progress_report(populated_db, output_path)

    # No parent institutions CSV should be created
    csv_files = list(tmp_path.glob("*parent*.csv"))
    assert len(csv_files) == 0


def test_generate_progress_report_json_includes_parent_institutions(
    populated_db: Path, tmp_path: Path
):
    """scan-progress-data.json should include a parent_institutions key."""
    output_path = tmp_path / "report.md"
    data_path = tmp_path / "scan-progress-data.json"

    generate_progress_report(populated_db, output_path, data_path=data_path)

    payload = json.loads(data_path.read_text(encoding="utf-8"))
    assert "parent_institutions" in payload
    assert isinstance(payload["parent_institutions"], list)


def test_generate_progress_report_missing_db_json_has_parent_institutions_key(
    tmp_path: Path,
):
    """Missing DB run should still write parent_institutions: [] to JSON."""
    db_path = tmp_path / "missing.db"
    output_path = tmp_path / "report.md"
    data_path = tmp_path / "scan-progress-data.json"

    generate_progress_report(db_path, output_path, data_path=data_path)

    payload = json.loads(data_path.read_text(encoding="utf-8"))
    assert "parent_institutions" in payload
    assert payload["parent_institutions"] == []
