"""Tests for the technology scan stats report generator."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.cli.generate_technology_report import (
    _aggregate_tech_counts,
    _build_stats_block,
    _query_by_country,
    _query_country_drilldowns,
    _query_summary,
    _query_tech_rows,
    generate_technology_report,
)
from src.storage.schema import initialize_schema


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

_STATS_MARKER_START = "<!-- TECH_STATS_START -->"
_STATS_MARKER_END = "<!-- TECH_STATS_END -->"

_TECH_PAGE_TEMPLATE = """\
---
title: Technology Scanning
layout: page
---

# Technology Scanning

## Current Stats

<!-- TECH_STATS_START -->

_No scan data yet._

<!-- TECH_STATS_END -->

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
    """Return path to a database with sample technology scan data."""
    db_path = tmp_path / "test.db"
    initialize_schema(f"sqlite:///{db_path}")

    conn = sqlite3.connect(db_path)
    try:
        rows = [
            # (url, country_code, scan_id, technologies, error_message, scanned_at)
            (
                "https://example.is/page1",
                "ICELAND",
                "tech-ICELAND-20240601-001",
                json.dumps({
                    "Nginx": {"versions": ["1.24"], "categories": ["Web servers"]},
                    "WordPress": {"versions": ["6.2"], "categories": ["CMS", "Blogs"]},
                }),
                None,
                "2024-06-01T10:00:00+00:00",
            ),
            (
                "https://example.is/page2",
                "ICELAND",
                "tech-ICELAND-20240601-001",
                json.dumps({
                    "Nginx": {"versions": [], "categories": ["Web servers"]},
                }),
                None,
                "2024-06-01T10:01:00+00:00",
            ),
            (
                "https://example.is/page3",
                "ICELAND",
                "tech-ICELAND-20240601-001",
                "{}",
                None,
                "2024-06-01T10:02:00+00:00",
            ),
            (
                "https://example.is/page4",
                "ICELAND",
                "tech-ICELAND-20240601-001",
                "{}",
                "Connection error: timed out",
                "2024-06-01T10:03:00+00:00",
            ),
            (
                "https://example.fr/page1",
                "FRANCE",
                "tech-FRANCE-20240602-001",
                json.dumps({
                    "Apache": {"versions": ["2.4"], "categories": ["Web servers"]},
                    "Drupal": {"versions": ["10"], "categories": ["CMS"]},
                    "PHP": {"versions": ["8.1"], "categories": ["Programming languages"]},
                }),
                None,
                "2024-06-02T08:00:00+00:00",
            ),
            (
                "https://example.fr/page2",
                "FRANCE",
                "tech-FRANCE-20240602-001",
                json.dumps({
                    "Apache": {"versions": [], "categories": ["Web servers"]},
                    "PHP": {"versions": [], "categories": ["Programming languages"]},
                }),
                None,
                "2024-06-02T08:01:00+00:00",
            ),
        ]
        for row in rows:
            conn.execute(
                """
                INSERT INTO url_tech_results
                (url, country_code, scan_id, technologies, error_message, scanned_at)
                VALUES (?, ?, ?, ?, ?, ?)
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

    assert result["total_batches"] == 2    # 2 distinct scan_ids
    assert result["total_scanned"] == 6    # 6 distinct URLs
    # page4 has an error_message so it doesn't count as detected
    assert result["total_detected"] == 5   # 5 successful scans


# ---------------------------------------------------------------------------
# _query_tech_rows tests
# ---------------------------------------------------------------------------

def test_query_tech_rows_empty_db(empty_db: Path):
    """Should return empty list from an empty database."""
    conn = sqlite3.connect(empty_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_tech_rows(conn)
    finally:
        conn.close()

    assert rows == []


def test_query_tech_rows_populated_db(populated_db: Path):
    """Should return only rows with non-empty technologies and no error."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_tech_rows(conn)
    finally:
        conn.close()

    # page3 has '{}' technologies, page4 has error — both excluded
    urls = {r["url"] for r in rows}
    assert "https://example.is/page3" not in urls
    assert "https://example.is/page4" not in urls
    # pages with technologies should be included
    assert "https://example.is/page1" in urls
    assert "https://example.fr/page1" in urls


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
    assert iceland["total_scanned"] == 4    # 4 Iceland URLs
    # page4 has error_message → not detected
    assert iceland["total_detected"] == 3


def test_query_country_drilldowns_populated_db(populated_db: Path):
    """Should expose scanned and detected page evidence by country."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_country_drilldowns(conn)
    finally:
        conn.close()

    assert rows["ICELAND"]["scanned"][0]["page_url"] == "https://example.is/page1"
    assert rows["ICELAND"]["detected"][0]["technology_names"] == ["Nginx", "WordPress"]
    assert rows["ICELAND"]["detected"][-1]["technology_names"] == []


# ---------------------------------------------------------------------------
# _aggregate_tech_counts tests
# ---------------------------------------------------------------------------

def test_aggregate_tech_counts_empty():
    """Should return empty counters for empty input."""
    tech_counts, cat_counts, tech_cats = _aggregate_tech_counts([])
    assert len(tech_counts) == 0
    assert len(cat_counts) == 0
    assert len(tech_cats) == 0


def test_aggregate_tech_counts_basic():
    """Should count technologies and categories correctly."""
    rows = [
        {
            "url": "https://example.is/page1",
            "technologies": json.dumps({
                "Nginx": {"versions": ["1.24"], "categories": ["Web servers"]},
                "WordPress": {"versions": ["6.2"], "categories": ["CMS", "Blogs"]},
            }),
        },
        {
            "url": "https://example.is/page2",
            "technologies": json.dumps({
                "Nginx": {"versions": [], "categories": ["Web servers"]},
            }),
        },
        {
            "url": "https://example.fr/page1",
            "technologies": json.dumps({
                "Apache": {"versions": [], "categories": ["Web servers"]},
            }),
        },
    ]
    tech_counts, cat_counts, tech_cats = _aggregate_tech_counts(rows)

    assert tech_counts["Nginx"] == 2         # appears on 2 URLs
    assert tech_counts["WordPress"] == 1     # appears on 1 URL
    assert tech_counts["Apache"] == 1        # appears on 1 URL

    assert cat_counts["Web servers"] == 3    # Nginx×2 + Apache×1
    assert cat_counts["CMS"] == 1
    assert cat_counts["Blogs"] == 1

    assert tech_cats["WordPress"] == ["Blogs", "CMS"]  # sorted alphabetically
    assert tech_cats["Nginx"] == ["Web servers"]


def test_aggregate_tech_counts_no_double_counting():
    """URL appearing multiple times should be counted only once."""
    rows = [
        {
            "url": "https://example.is/page1",
            "technologies": json.dumps({
                "Nginx": {"versions": [], "categories": ["Web servers"]},
            }),
        },
        # same URL again — must not increment the count
        {
            "url": "https://example.is/page1",
            "technologies": json.dumps({
                "Nginx": {"versions": [], "categories": ["Web servers"]},
                "WordPress": {"versions": [], "categories": ["CMS"]},
            }),
        },
    ]
    tech_counts, cat_counts, _ = _aggregate_tech_counts(rows)

    assert tech_counts["Nginx"] == 1   # counted only once
    assert "WordPress" not in tech_counts   # from second occurrence, skipped


def test_aggregate_tech_counts_invalid_json():
    """Should skip rows with invalid JSON gracefully."""
    rows = [
        {"url": "https://example.is/page1", "technologies": "not-valid-json"},
        {
            "url": "https://example.is/page2",
            "technologies": json.dumps({
                "Nginx": {"versions": [], "categories": ["Web servers"]},
            }),
        },
    ]
    tech_counts, _, _ = _aggregate_tech_counts(rows)

    assert "Nginx" in tech_counts
    assert tech_counts["Nginx"] == 1


# ---------------------------------------------------------------------------
# _build_stats_block tests
# ---------------------------------------------------------------------------

def test_build_stats_block_empty_summary():
    """Should return a placeholder block when no summary data is available."""
    from collections import Counter
    block = _build_stats_block({}, Counter(), Counter(), {}, "2024-06-01 12:00 UTC")
    assert _STATS_MARKER_START in block
    assert _STATS_MARKER_END in block
    assert "No scan data yet" in block


def test_build_stats_block_with_data():
    """Should produce a block containing the key stat figures."""
    from collections import Counter
    summary = {
        "total_batches": 10,
        "total_scanned": 500,
        "total_detected": 400,
        "last_scan": "2024-06-01T12:00:00",
    }
    tech_counts = Counter({"Nginx": 200, "WordPress": 150, "Apache": 100})
    cat_counts = Counter({"Web servers": 300, "CMS": 150})
    tech_cats = {
        "Nginx": ["Web servers"],
        "WordPress": ["Blogs", "CMS"],
        "Apache": ["Web servers"],
    }
    block = _build_stats_block(
        summary, tech_counts, cat_counts, tech_cats, "2024-06-01 12:00 UTC"
    )
    assert _STATS_MARKER_START in block
    assert _STATS_MARKER_END in block
    assert "10" in block          # batches
    assert "500" in block         # scanned
    assert "400" in block         # detected
    assert "Nginx" in block
    assert "WordPress" in block
    assert "Web servers" in block
    assert "technology-data.json" in block


def test_build_stats_block_with_total_available():
    """Stats block should include coverage line when total_available > 0."""
    from collections import Counter
    summary = {
        "total_batches": 5,
        "total_scanned": 100,
        "total_detected": 80,
        "last_scan": "2024-06-01T12:00:00",
    }
    block = _build_stats_block(
        summary, Counter(), Counter(), {}, "2024-06-01 12:00 UTC", total_available=1000
    )
    assert "100" in block          # scanned
    assert "1,000" in block        # available
    assert "10.0%" in block        # 100/1000 coverage


# ---------------------------------------------------------------------------
# generate_technology_report tests
# ---------------------------------------------------------------------------

def test_generate_technology_report_missing_db(tmp_path: Path):
    """Should write an empty-data JSON file and a placeholder stats block."""
    page_path = tmp_path / "technology-scanning.md"
    page_path.write_text(_TECH_PAGE_TEMPLATE)
    data_path = tmp_path / "technology-data.json"
    db_path = tmp_path / "nonexistent.db"

    result = generate_technology_report(db_path, page_path, data_path)

    assert result is True
    assert data_path.exists()
    data = json.loads(data_path.read_text())
    assert data["summary"]["total_scanned"] == 0

    content = page_path.read_text()
    assert _STATS_MARKER_START in content
    assert _STATS_MARKER_END in content
    assert "No scan data yet" in content
    assert "## Overview" in content  # rest of page preserved


def test_generate_technology_report_with_data(populated_db: Path, tmp_path: Path):
    """Should inject real stats and write accurate JSON data."""
    page_path = tmp_path / "technology-scanning.md"
    page_path.write_text(_TECH_PAGE_TEMPLATE)
    data_path = tmp_path / "technology-data.json"

    result = generate_technology_report(populated_db, page_path, data_path)

    assert result is True

    # Check JSON data file
    assert data_path.exists()
    data = json.loads(data_path.read_text())
    assert data["summary"]["total_batches"] == 2
    assert data["summary"]["total_scanned"] == 6
    assert data["summary"]["total_detected"] == 5
    assert len(data["by_country"]) == 2
    assert len(data["top_technologies"]) > 0
    assert len(data["top_categories"]) > 0

    # Check Markdown page was updated
    content = page_path.read_text()
    assert _STATS_MARKER_START in content
    assert _STATS_MARKER_END in content
    assert "Nginx" in content
    assert "technology-data.json" in content
    # Rest of the page must still be present
    assert "## Overview" in content


def test_generate_technology_report_missing_markers(populated_db: Path, tmp_path: Path):
    """Should return False without modifying the page when markers are absent."""
    page_path = tmp_path / "technology-scanning.md"
    original = "# Technology Scanning\n\nNo markers here.\n"
    page_path.write_text(original)
    data_path = tmp_path / "technology-data.json"

    result = generate_technology_report(populated_db, page_path, data_path)

    assert result is False
    assert page_path.read_text() == original
    # JSON data file is still written even when the page update fails
    assert data_path.exists()


def test_generate_technology_report_missing_page(populated_db: Path, tmp_path: Path):
    """Should return False when the technology-scanning.md page does not exist."""
    page_path = tmp_path / "nonexistent.md"
    data_path = tmp_path / "technology-data.json"

    result = generate_technology_report(populated_db, page_path, data_path)

    assert result is False
    # JSON data file is still written
    assert data_path.exists()


def test_generate_technology_report_json_structure(populated_db: Path, tmp_path: Path):
    """JSON data file should have the expected top-level keys."""
    page_path = tmp_path / "technology-scanning.md"
    page_path.write_text(_TECH_PAGE_TEMPLATE)
    data_path = tmp_path / "technology-data.json"

    generate_technology_report(populated_db, page_path, data_path)

    data = json.loads(data_path.read_text())
    assert "generated_at" in data
    assert "summary" in data
    assert "top_technologies" in data
    assert "top_categories" in data
    assert "by_country" in data
    assert "country_drilldowns" in data

    summary = data["summary"]
    for key in ("total_batches", "total_scanned", "total_detected",
                "total_available", "unique_technologies", "unique_categories"):
        assert key in summary, f"Missing key: {key}"
    assert data["country_drilldowns"]["ICELAND"]["detected"][0]["page_url"] == "https://example.is/page1"


def test_generate_technology_report_preserves_page_structure(
    populated_db: Path, tmp_path: Path
):
    """Content outside the markers must be preserved after an update."""
    page_path = tmp_path / "technology-scanning.md"
    page_path.write_text(_TECH_PAGE_TEMPLATE)
    data_path = tmp_path / "technology-data.json"

    generate_technology_report(populated_db, page_path, data_path)

    content = page_path.read_text()
    # Front matter and heading
    assert "title: Technology Scanning" in content
    assert "# Technology Scanning" in content
    # Section after the markers
    assert "## Overview" in content
    assert "Some content." in content


def test_generate_technology_report_json_includes_total_available(
    populated_db: Path, tmp_path: Path
):
    """JSON data file should include total_available when seeds_dir is provided."""
    # Create a minimal toon seed directory with one file
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    seed_data = {"version": "0.1-seed", "country": "Iceland", "page_count": 50, "domains": []}
    (seeds_dir / "iceland.toon").write_text(json.dumps(seed_data), encoding="utf-8")

    page_path = tmp_path / "technology-scanning.md"
    page_path.write_text(_TECH_PAGE_TEMPLATE)
    data_path = tmp_path / "technology-data.json"

    generate_technology_report(populated_db, page_path, data_path, seeds_dir)

    data = json.loads(data_path.read_text())
    assert data["summary"]["total_available"] == 50


# ---------------------------------------------------------------------------
# Tests for duplicate URL handling
# ---------------------------------------------------------------------------

@pytest.fixture
def duplicate_scan_db(tmp_path: Path) -> Path:
    """DB where the same URL appears in two different scan batches."""
    db_path = tmp_path / "test.db"
    initialize_schema(f"sqlite:///{db_path}")
    conn = sqlite3.connect(db_path)
    try:
        rows = [
            (
                "https://example.is/page1",
                "ICELAND",
                "tech-ICELAND-scan-001",
                json.dumps({"Nginx": {"versions": [], "categories": ["Web servers"]}}),
                None,
                "2024-06-01T10:00:00+00:00",
            ),
            # Same URL in a second batch with a later timestamp
            (
                "https://example.is/page1",
                "ICELAND",
                "tech-ICELAND-scan-002",
                json.dumps({"Nginx": {"versions": ["1.24"], "categories": ["Web servers"]}}),
                None,
                "2024-06-02T10:00:00+00:00",
            ),
            (
                "https://example.is/page2",
                "ICELAND",
                "tech-ICELAND-scan-001",
                json.dumps({"WordPress": {"versions": ["6.2"], "categories": ["CMS"]}}),
                None,
                "2024-06-01T10:01:00+00:00",
            ),
        ]
        for row in rows:
            conn.execute(
                """
                INSERT INTO url_tech_results
                (url, country_code, scan_id, technologies, error_message, scanned_at)
                VALUES (?, ?, ?, ?, ?, ?)
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

    assert result["total_batches"] == 2       # 2 distinct scan_ids
    assert result["total_scanned"] == 2       # only 2 distinct URLs
    assert result["total_detected"] == 2      # both URLs detected successfully


def test_query_tech_rows_no_double_counting(duplicate_scan_db: Path):
    """_query_tech_rows should return at most one row per URL."""
    conn = sqlite3.connect(duplicate_scan_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_tech_rows(conn)
    finally:
        conn.close()

    urls = [r["url"] for r in rows]
    # page1 should appear only once (the latest scan)
    assert urls.count("https://example.is/page1") == 1
    assert len(urls) == 2   # page1 and page2


# ---------------------------------------------------------------------------
# Tests for _count_toon_seed_urls
# ---------------------------------------------------------------------------

def test_count_toon_seed_urls_missing_dir(tmp_path: Path):
    """Should return empty dict when the directory does not exist."""
    from src.cli.generate_technology_report import _count_toon_seed_urls
    result = _count_toon_seed_urls(tmp_path / "nonexistent")
    assert result == {}


def test_count_toon_seed_urls_empty_dir(tmp_path: Path):
    """Should return empty dict when the directory contains no .toon files."""
    from src.cli.generate_technology_report import _count_toon_seed_urls
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    result = _count_toon_seed_urls(seeds_dir)
    assert result == {}


def test_count_toon_seed_urls_reads_page_count(tmp_path: Path):
    """Should correctly read page_count from toon seed files."""
    from src.cli.generate_technology_report import _count_toon_seed_urls
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    for name, count in [("iceland", 139), ("norway", 239)]:
        data = {"page_count": count, "domains": []}
        (seeds_dir / f"{name}.toon").write_text(json.dumps(data), encoding="utf-8")
    result = _count_toon_seed_urls(seeds_dir)
    assert result == {"ICELAND": 139, "NORWAY": 239}


# ---------------------------------------------------------------------------
# CSV output tests
# ---------------------------------------------------------------------------

def test_generate_technology_report_writes_csv(populated_db: Path, tmp_path: Path):
    """Should write a CSV file when csv_path is provided."""
    page_path = tmp_path / "technology-scanning.md"
    page_path.write_text(_TECH_PAGE_TEMPLATE)
    data_path = tmp_path / "technology-data.json"
    csv_path = tmp_path / "technology-data.csv"

    result = generate_technology_report(populated_db, page_path, data_path, csv_path=csv_path)

    assert result is True
    assert csv_path.exists()

    content = csv_path.read_bytes()
    # Should have UTF-8 BOM
    assert content[:3] == b"\xef\xbb\xbf"

    text = content.decode("utf-8-sig")
    lines = text.strip().splitlines()
    # Header row
    assert lines[0] == "rank,technology,pages,categories"
    # At least one data row (Nginx appears on 2 Iceland pages)
    assert len(lines) > 1
    # Check that Nginx is present and has rank 1 or similar
    techs = {line.split(",")[1] for line in lines[1:]}
    assert "Nginx" in techs
    assert "WordPress" in techs
    assert "Drupal" in techs


def test_generate_technology_report_no_csv_without_path(populated_db: Path, tmp_path: Path):
    """Should not write a CSV file when csv_path is None."""
    page_path = tmp_path / "technology-scanning.md"
    page_path.write_text(_TECH_PAGE_TEMPLATE)
    data_path = tmp_path / "technology-data.json"

    generate_technology_report(populated_db, page_path, data_path)

    # No CSV should be created in the directory
    csv_files = list(tmp_path.glob("*.csv"))
    assert len(csv_files) == 0


def test_build_stats_block_includes_csv_link():
    """Stats block should contain a link to the CSV download."""
    from collections import Counter
    summary = {
        "total_batches": 5,
        "total_scanned": 100,
        "total_detected": 80,
        "last_scan": "2024-06-01T12:00:00",
    }
    block = _build_stats_block(summary, Counter({"Nginx": 50}), Counter(), {}, "2024-06-01 12:00 UTC")
    assert "technology-data.csv" in block
    assert "technology-data.json" in block
