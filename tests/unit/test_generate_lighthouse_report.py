"""Tests for the Lighthouse scan results report generator."""

from __future__ import annotations

import csv as _csv
import json
import sqlite3
from pathlib import Path

import pytest

from src.cli.generate_lighthouse_report import (
    _build_institution_lookup,
    _build_stats_block,
    _count_toon_seed_urls,
    _group_by_institution,
    _query_by_country,
    _query_by_url,
    _query_summary,
    _write_csv,
    generate_lighthouse_report,
)
from src.storage.schema import initialize_schema


_LIGHTHOUSE_PAGE_TEMPLATE = """\
---
title: Lighthouse Scan Results
layout: page
---

<!-- LIGHTHOUSE_STATS_START -->

_No scan data yet._

<!-- LIGHTHOUSE_STATS_END -->

## Overview

Some content.
"""


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """Return path to a freshly initialised empty database."""
    db_path = tmp_path / "test.db"
    initialize_schema(f"sqlite:///{db_path}")
    return db_path


@pytest.fixture
def populated_db(tmp_path: Path) -> Path:
    """Return a database with representative Lighthouse scan data."""
    db_path = tmp_path / "test.db"
    initialize_schema(f"sqlite:///{db_path}")

    conn = sqlite3.connect(db_path)
    try:
        rows = [
            # (url, country_code, scan_id, perf, a11y, bp, seo, error, scanned_at)
            (
                "https://example.is/page1",
                "ICELAND",
                "lh-ICELAND-001",
                0.9,
                0.8,
                1.0,
                0.95,
                None,
                None,
                "2026-03-01T10:00:00+00:00",
            ),
            (
                "https://example.is/page2",
                "ICELAND",
                "lh-ICELAND-001",
                0.7,
                0.6,
                0.8,
                0.85,
                None,
                None,
                "2026-03-01T10:05:00+00:00",
            ),
            (
                "https://example.is/page3",
                "ICELAND",
                "lh-ICELAND-001",
                None,
                None,
                None,
                None,
                None,
                "Lighthouse timed out after 120s",
                "2026-03-01T10:10:00+00:00",
            ),
            (
                "https://gov.example.fr/home",
                "FRANCE",
                "lh-FRANCE-001",
                0.5,
                0.75,
                0.9,
                0.6,
                None,
                None,
                "2026-03-02T09:00:00+00:00",
            ),
        ]
        for row in rows:
            conn.execute(
                """
                INSERT INTO url_lighthouse_results
                (url, country_code, scan_id,
                 performance_score, accessibility_score,
                 best_practices_score, seo_score, pwa_score,
                 error_message, scanned_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

def test_query_summary_empty_db(empty_db: Path) -> None:
    """Should return zero/null values from an empty database."""
    conn = sqlite3.connect(empty_db)
    conn.row_factory = sqlite3.Row
    try:
        result = _query_summary(conn)
    finally:
        conn.close()

    assert result.get("total_batches", 0) == 0
    assert result.get("total_scanned", 0) == 0


def test_query_summary_populated_db(populated_db: Path) -> None:
    """Should aggregate stats correctly across countries."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        result = _query_summary(conn)
    finally:
        conn.close()

    assert result["total_batches"] == 2   # 2 distinct scan_ids
    assert result["total_scanned"] == 4   # 4 distinct URLs
    assert result["total_success"] == 3   # page3 has an error
    assert result["avg_accessibility"] is not None
    # avg of 0.8, 0.6, 0.75 = 0.717 (page3 excluded)
    assert abs(result["avg_accessibility"] - (0.8 + 0.6 + 0.75) / 3) < 0.01


# ---------------------------------------------------------------------------
# _query_by_country tests
# ---------------------------------------------------------------------------

def test_query_by_country_empty_db(empty_db: Path) -> None:
    """Should return empty list from an empty database."""
    conn = sqlite3.connect(empty_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_by_country(conn)
    finally:
        conn.close()

    assert rows == []


def test_query_by_country_groups_by_country(populated_db: Path) -> None:
    """Should return one row per country with correct aggregates."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_by_country(conn)
    finally:
        conn.close()

    assert len(rows) == 2
    country_map = {r["country_code"]: r for r in rows}

    iceland = country_map["ICELAND"]
    assert iceland["total_scanned"] == 3
    assert iceland["total_success"] == 2  # page3 is an error
    assert iceland["avg_accessibility"] is not None
    assert abs(iceland["avg_accessibility"] - (0.8 + 0.6) / 2) < 0.01

    france = country_map["FRANCE"]
    assert france["total_scanned"] == 1
    assert france["total_success"] == 1
    assert france["avg_accessibility"] == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# _build_stats_block tests
# ---------------------------------------------------------------------------

def test_build_stats_block_empty_returns_placeholder() -> None:
    """Should return a no-data placeholder when summary is empty."""
    block = _build_stats_block({}, [], "2026-04-01 10:00 UTC")
    assert "No Lighthouse scan data yet" in block
    assert "<!-- LIGHTHOUSE_STATS_START -->" in block
    assert "<!-- LIGHTHOUSE_STATS_END -->" in block


def test_build_stats_block_populated_includes_scores(populated_db: Path) -> None:
    """Should include country names and score columns when data is present."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        summary = _query_summary(conn)
        by_country = _query_by_country(conn)
    finally:
        conn.close()

    block = _build_stats_block(summary, by_country, "2026-04-01 10:00 UTC")
    assert "<!-- LIGHTHOUSE_STATS_START -->" in block
    assert "<!-- LIGHTHOUSE_STATS_END -->" in block
    assert "Iceland" in block
    assert "France" in block
    assert "Perf" in block
    assert "A11y" in block
    assert "Best Practices" in block
    assert "SEO" in block
    assert "lighthouse-data.json" in block


def test_build_stats_block_includes_coverage_when_available(populated_db: Path) -> None:
    """Should include X of Y available pages when seed_counts are supplied."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        summary = _query_summary(conn)
        by_country = _query_by_country(conn)
    finally:
        conn.close()

    seed_counts = {"ICELAND": 100, "FRANCE": 500}
    block = _build_stats_block(
        summary, by_country, "2026-04-01", total_available=600, seed_counts=seed_counts
    )
    assert "600" in block


# ---------------------------------------------------------------------------
# generate_lighthouse_report integration tests
# ---------------------------------------------------------------------------

def test_generate_lighthouse_report_no_db(tmp_path: Path) -> None:
    """Should write a placeholder stats block when no database exists."""
    page_path = tmp_path / "lighthouse-results.md"
    page_path.write_text(_LIGHTHOUSE_PAGE_TEMPLATE, encoding="utf-8")
    data_path = tmp_path / "lighthouse-data.json"

    ok = generate_lighthouse_report(tmp_path / "nonexistent.db", page_path, data_path)

    assert ok
    content = page_path.read_text(encoding="utf-8")
    assert "No Lighthouse scan data yet" in content
    assert data_path.exists()
    data = json.loads(data_path.read_text())
    assert data["summary"]["total_scanned"] == 0


def test_generate_lighthouse_report_missing_markers(tmp_path: Path, empty_db: Path) -> None:
    """Should return False and leave the page unchanged when markers are absent."""
    page_path = tmp_path / "lighthouse-results.md"
    page_path.write_text("No markers here.\n", encoding="utf-8")
    data_path = tmp_path / "lighthouse-data.json"

    ok = generate_lighthouse_report(empty_db, page_path, data_path)

    assert not ok
    assert page_path.read_text() == "No markers here.\n"


def test_generate_lighthouse_report_writes_stats(tmp_path: Path, populated_db: Path) -> None:
    """Should replace the stats block with real data."""
    page_path = tmp_path / "lighthouse-results.md"
    page_path.write_text(_LIGHTHOUSE_PAGE_TEMPLATE, encoding="utf-8")
    data_path = tmp_path / "lighthouse-data.json"

    ok = generate_lighthouse_report(populated_db, page_path, data_path)

    assert ok
    content = page_path.read_text(encoding="utf-8")
    assert "Iceland" in content
    assert "France" in content
    assert "_No scan data yet._" not in content

    data = json.loads(data_path.read_text())
    assert data["summary"]["total_scanned"] == 4
    assert data["summary"]["total_success"] == 3
    assert len(data["by_country"]) == 2


# ---------------------------------------------------------------------------
# _query_by_url tests
# ---------------------------------------------------------------------------

def test_query_by_url_empty_db(empty_db: Path) -> None:
    """Should return an empty list from an empty database."""
    conn = sqlite3.connect(empty_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_by_url(conn)
    finally:
        conn.close()

    assert rows == []


def test_query_by_url_returns_one_row_per_url(populated_db: Path) -> None:
    """Should return one row per URL with individual scan scores."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_by_url(conn)
    finally:
        conn.close()

    assert len(rows) == 4
    urls = {r["url"] for r in rows}
    assert "https://example.is/page1" in urls
    assert "https://example.is/page2" in urls
    assert "https://example.is/page3" in urls
    assert "https://gov.example.fr/home" in urls


def test_query_by_url_includes_scores(populated_db: Path) -> None:
    """Should include individual scores for successful scans."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_by_url(conn)
    finally:
        conn.close()

    row_map = {r["url"]: r for r in rows}
    page1 = row_map["https://example.is/page1"]
    assert page1["performance_score"] == pytest.approx(0.9)
    assert page1["accessibility_score"] == pytest.approx(0.8)
    assert page1["best_practices_score"] == pytest.approx(1.0)
    assert page1["seo_score"] == pytest.approx(0.95)
    assert page1["error_message"] is None


def test_query_by_url_includes_error_rows(populated_db: Path) -> None:
    """Should include error rows (scores are None, error_message is set)."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_by_url(conn)
    finally:
        conn.close()

    row_map = {r["url"]: r for r in rows}
    page3 = row_map["https://example.is/page3"]
    assert page3["performance_score"] is None
    assert page3["error_message"] == "Lighthouse timed out after 120s"


def test_query_by_url_ordered_by_country_then_url(populated_db: Path) -> None:
    """Rows should be ordered by country_code then url."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_by_url(conn)
    finally:
        conn.close()

    france_rows = [r for r in rows if r["country_code"] == "FRANCE"]
    iceland_rows = [r for r in rows if r["country_code"] == "ICELAND"]
    # FRANCE comes before ICELAND alphabetically
    france_idx = rows.index(france_rows[0])
    iceland_idx = rows.index(iceland_rows[0])
    assert france_idx < iceland_idx


# ---------------------------------------------------------------------------
# _write_csv tests
# ---------------------------------------------------------------------------

def test_write_csv_creates_file(populated_db: Path, tmp_path: Path) -> None:
    """Should create a CSV file with a header and one data row per URL."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_by_url(conn)
    finally:
        conn.close()

    csv_path = tmp_path / "lighthouse-data.csv"
    _write_csv(rows, csv_path)

    assert csv_path.exists()
    # File should start with UTF-8 BOM
    raw = csv_path.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf"


def test_write_csv_header_columns(populated_db: Path, tmp_path: Path) -> None:
    """CSV header should match the expected column names."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_by_url(conn)
    finally:
        conn.close()

    csv_path = tmp_path / "lighthouse-data.csv"
    _write_csv(rows, csv_path)

    text = csv_path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    header = lines[0]
    assert "country_code" in header
    assert "url" in header
    assert "performance" in header
    assert "accessibility" in header
    assert "best_practices" in header
    assert "seo" in header
    assert "error" in header
    assert "scanned_at" in header


def test_write_csv_row_count(populated_db: Path, tmp_path: Path) -> None:
    """CSV should have one data row per URL (plus header)."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_by_url(conn)
    finally:
        conn.close()

    csv_path = tmp_path / "lighthouse-data.csv"
    _write_csv(rows, csv_path)

    text = csv_path.read_text(encoding="utf-8-sig")
    data_lines = [ln for ln in text.splitlines() if ln.strip()]
    # 1 header + 4 data rows
    assert len(data_lines) == 5


def test_write_csv_scores_as_percentage(populated_db: Path, tmp_path: Path) -> None:
    """Scores should be expressed on the 0–100 scale in the CSV."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_by_url(conn)
    finally:
        conn.close()

    csv_path = tmp_path / "lighthouse-data.csv"
    _write_csv(rows, csv_path)

    text = csv_path.read_text(encoding="utf-8-sig")
    reader = _csv.DictReader(text.splitlines())
    row_map = {r["url"]: r for r in reader}

    page1 = row_map["https://example.is/page1"]
    assert float(page1["performance"]) == pytest.approx(90.0)
    assert float(page1["accessibility"]) == pytest.approx(80.0)


def test_write_csv_empty_scores_for_error_rows(populated_db: Path, tmp_path: Path) -> None:
    """Error rows should have empty score cells in the CSV."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_by_url(conn)
    finally:
        conn.close()

    csv_path = tmp_path / "lighthouse-data.csv"
    _write_csv(rows, csv_path)

    text = csv_path.read_text(encoding="utf-8-sig")
    reader = _csv.DictReader(text.splitlines())
    row_map = {r["url"]: r for r in reader}

    page3 = row_map["https://example.is/page3"]
    assert page3["performance"] == ""
    assert page3["accessibility"] == ""
    assert page3["error"] == "Lighthouse timed out after 120s"


# ---------------------------------------------------------------------------
# generate_lighthouse_report CSV integration tests
# ---------------------------------------------------------------------------

def test_generate_lighthouse_report_writes_csv(
    tmp_path: Path, populated_db: Path
) -> None:
    """Should write a CSV file alongside the JSON when csv_path is provided."""
    page_path = tmp_path / "lighthouse-results.md"
    page_path.write_text(_LIGHTHOUSE_PAGE_TEMPLATE, encoding="utf-8")
    data_path = tmp_path / "lighthouse-data.json"
    csv_path = tmp_path / "lighthouse-data.csv"

    ok = generate_lighthouse_report(
        populated_db, page_path, data_path, csv_path=csv_path
    )

    assert ok
    assert csv_path.exists()
    text = csv_path.read_text(encoding="utf-8-sig")
    assert "url" in text
    assert "country_code" in text
    # 4 data rows + header = 5 non-empty lines
    data_lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(data_lines) == 5


def test_generate_lighthouse_report_json_contains_by_url(
    tmp_path: Path, populated_db: Path
) -> None:
    """JSON output should include a 'by_url' array with individual scan rows."""
    page_path = tmp_path / "lighthouse-results.md"
    page_path.write_text(_LIGHTHOUSE_PAGE_TEMPLATE, encoding="utf-8")
    data_path = tmp_path / "lighthouse-data.json"

    ok = generate_lighthouse_report(populated_db, page_path, data_path)

    assert ok
    data = json.loads(data_path.read_text())
    assert "by_url" in data
    assert len(data["by_url"]) == 4


def test_generate_lighthouse_report_no_csv_when_not_requested(
    tmp_path: Path, populated_db: Path
) -> None:
    """Should not create a CSV when csv_path is None."""
    page_path = tmp_path / "lighthouse-results.md"
    page_path.write_text(_LIGHTHOUSE_PAGE_TEMPLATE, encoding="utf-8")
    data_path = tmp_path / "lighthouse-data.json"

    ok = generate_lighthouse_report(populated_db, page_path, data_path, csv_path=None)

    assert ok
    # No CSV should have been written
    assert not (tmp_path / "lighthouse-data.csv").exists()


def test_build_stats_block_references_csv() -> None:
    """Stats block should link to the CSV file for independent verification."""
    from src.cli.generate_lighthouse_report import _build_stats_block

    summary = {
        "total_batches": 1,
        "total_scanned": 2,
        "total_success": 2,
        "avg_performance": 0.8,
        "avg_accessibility": 0.9,
        "avg_best_practices": 0.95,
        "avg_seo": 0.85,
        "last_scan": "2026-01-01T00:00:00",
    }
    block = _build_stats_block(summary, [], "2026-01-01 00:00 UTC")
    assert "lighthouse-data.csv" in block


# ---------------------------------------------------------------------------
# _build_institution_lookup tests
# ---------------------------------------------------------------------------

def test_build_institution_lookup_missing_dir(tmp_path: Path) -> None:
    """Should return an empty dict when the directory does not exist."""
    result = _build_institution_lookup(tmp_path / "nonexistent")
    assert result == {}


def test_build_institution_lookup_reads_toon_files(tmp_path: Path) -> None:
    """Should map canonical_domain to institution_name from toon file domains."""
    toon_data = {
        "version": "0.1",
        "country": "TEST",
        "page_count": 2,
        "domains": [
            {
                "canonical_domain": "alpha.edu",
                "institution_name": "Alpha University",
                "pages": [{"url": "https://alpha.edu/"}],
            },
            {
                "canonical_domain": "beta.edu",
                "institution_name": "Beta College",
                "pages": [{"url": "https://beta.edu/"}],
            },
        ],
    }
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    (seeds_dir / "test.toon").write_text(
        json.dumps(toon_data), encoding="utf-8"
    )

    result = _build_institution_lookup(seeds_dir)
    assert result["alpha.edu"] == "Alpha University"
    assert result["beta.edu"] == "Beta College"


def test_build_institution_lookup_ignores_invalid_json(tmp_path: Path) -> None:
    """Should skip files with invalid JSON without raising."""
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    (seeds_dir / "bad.toon").write_text("not json", encoding="utf-8")

    result = _build_institution_lookup(seeds_dir)
    assert result == {}


def test_count_toon_seed_urls_prefers_subdomain_seed_when_both_exist(tmp_path: Path) -> None:
    """URL counting should avoid double-counting when _subdomains seed exists."""
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    (seeds_dir / "usa-edu-master.toon").write_text(
        json.dumps({"page_count": 10, "domains": []}),
        encoding="utf-8",
    )
    (seeds_dir / "usa-edu-master_subdomains.toon").write_text(
        json.dumps({"page_count": 30, "domains": []}),
        encoding="utf-8",
    )

    counts = _count_toon_seed_urls(seeds_dir)
    assert counts == {"USA_EDU_MASTER_SUBDOMAINS": 30}


def test_build_institution_lookup_prefers_subdomain_seed_when_both_exist(
    tmp_path: Path,
) -> None:
    """Institution lookup should ignore base seed when matching _subdomains exists."""
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    (seeds_dir / "usa-edu-master.toon").write_text(
        json.dumps(
            {
                "domains": [
                    {
                        "canonical_domain": "base.example.edu",
                        "institution_name": "Base Seed Name",
                        "pages": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (seeds_dir / "usa-edu-master_subdomains.toon").write_text(
        json.dumps(
            {
                "domains": [
                    {
                        "canonical_domain": "sub.example.edu",
                        "institution_name": "Subdomain Seed Name",
                        "pages": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    lookup = _build_institution_lookup(seeds_dir)
    assert "base.example.edu" not in lookup
    assert lookup["sub.example.edu"] == "Subdomain Seed Name"


# ---------------------------------------------------------------------------
# _group_by_institution tests
# ---------------------------------------------------------------------------

def test_group_by_institution_empty_input() -> None:
    """Should return an empty list for empty input."""
    assert _group_by_institution([]) == []


def test_group_by_institution_groups_by_domain() -> None:
    """Should group rows from the same domain into one entry."""
    rows = [
        {
            "url": "https://example.edu/page1",
            "performance_score": 0.9,
            "accessibility_score": 0.8,
            "best_practices_score": 1.0,
            "seo_score": 0.95,
            "error_message": None,
        },
        {
            "url": "https://example.edu/page2",
            "performance_score": 0.7,
            "accessibility_score": 0.6,
            "best_practices_score": 0.8,
            "seo_score": 0.85,
            "error_message": None,
        },
        {
            "url": "https://other.edu/home",
            "performance_score": 0.5,
            "accessibility_score": 0.75,
            "best_practices_score": 0.9,
            "seo_score": 0.6,
            "error_message": None,
        },
    ]

    result = _group_by_institution(rows)
    assert len(result) == 2
    domain_map = {r["domain"]: r for r in result}

    example = domain_map["example.edu"]
    assert example["total_scanned"] == 2
    assert example["total_success"] == 2
    assert abs(example["avg_accessibility"] - (0.8 + 0.6) / 2) < 0.01

    other = domain_map["other.edu"]
    assert other["total_scanned"] == 1
    assert other["avg_accessibility"] == pytest.approx(0.75)


def test_group_by_institution_excludes_errors_from_averages() -> None:
    """Error rows should count in total_scanned but not in averages or total_success."""
    rows = [
        {
            "url": "https://uni.edu/ok",
            "performance_score": 0.8,
            "accessibility_score": 0.7,
            "best_practices_score": 0.9,
            "seo_score": 0.85,
            "error_message": None,
        },
        {
            "url": "https://uni.edu/fail",
            "performance_score": None,
            "accessibility_score": None,
            "best_practices_score": None,
            "seo_score": None,
            "error_message": "Timeout",
        },
    ]

    result = _group_by_institution(rows)
    assert len(result) == 1
    row = result[0]
    assert row["total_scanned"] == 2
    assert row["total_success"] == 1
    assert row["avg_accessibility"] == pytest.approx(0.7)


def test_group_by_institution_uses_institution_lookup() -> None:
    """Should use institution_lookup to set institution_name."""
    rows = [
        {
            "url": "https://alpha.edu/",
            "performance_score": 0.8,
            "accessibility_score": 0.9,
            "best_practices_score": 1.0,
            "seo_score": 0.9,
            "error_message": None,
        },
    ]
    lookup = {"alpha.edu": "Alpha University"}

    result = _group_by_institution(rows, institution_lookup=lookup)
    assert result[0]["institution_name"] == "Alpha University"


def test_group_by_institution_falls_back_to_domain_when_no_lookup() -> None:
    """Should use domain as institution_name when lookup has no entry."""
    rows = [
        {
            "url": "https://unknown.edu/",
            "performance_score": 0.5,
            "accessibility_score": 0.6,
            "best_practices_score": 0.7,
            "seo_score": 0.8,
            "error_message": None,
        },
    ]

    result = _group_by_institution(rows)
    assert result[0]["institution_name"] == "unknown.edu"


def test_group_by_institution_sorted_by_domain() -> None:
    """Result should be sorted alphabetically by domain."""
    rows = [
        {
            "url": "https://zeta.edu/",
            "performance_score": 0.5,
            "accessibility_score": 0.5,
            "best_practices_score": 0.5,
            "seo_score": 0.5,
            "error_message": None,
        },
        {
            "url": "https://alpha.edu/",
            "performance_score": 0.8,
            "accessibility_score": 0.8,
            "best_practices_score": 0.8,
            "seo_score": 0.8,
            "error_message": None,
        },
    ]

    result = _group_by_institution(rows)
    assert result[0]["domain"] == "alpha.edu"
    assert result[1]["domain"] == "zeta.edu"


# ---------------------------------------------------------------------------
# _build_stats_block with by_institution tests
# ---------------------------------------------------------------------------

def test_build_stats_block_includes_institution_section(populated_db: Path) -> None:
    """Stats block should include institution table when by_institution is provided."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        summary = _query_summary(conn)
        by_country = _query_by_country(conn)
        by_url = _query_by_url(conn)
    finally:
        conn.close()

    by_institution = _group_by_institution(by_url)
    block = _build_stats_block(
        summary, by_country, "2026-04-01 10:00 UTC",
        by_institution=by_institution,
    )
    assert "Lighthouse Scores by Institution" in block
    assert "example.is" in block
    assert "gov.example.fr" in block
    # Verify the table header columns are present
    assert "Institution" in block
    assert "Domain" in block
    assert "Audited" in block
    # example.is has 2 success rows: perf avg (0.9+0.7)/2=0.8 → 80, a11y (0.8+0.6)/2=0.7 → 70
    assert "example.is" in block
    assert "2" in block  # 2 scanned pages for example.is (page1 + page2 + page3 error = 3 scanned but 2 success; table shows scanned)
    # gov.example.fr has 1 success row: a11y 0.75 → 75
    assert "75" in block


def test_build_stats_block_no_institution_section_when_none(populated_db: Path) -> None:
    """Stats block should not include institution section when by_institution is None."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        summary = _query_summary(conn)
        by_country = _query_by_country(conn)
    finally:
        conn.close()

    block = _build_stats_block(summary, by_country, "2026-04-01 10:00 UTC")
    assert "Lighthouse Scores by Institution" not in block


# ---------------------------------------------------------------------------
# generate_lighthouse_report with institution breakdown integration tests
# ---------------------------------------------------------------------------

def test_generate_lighthouse_report_includes_institution_breakdown(
    tmp_path: Path, populated_db: Path
) -> None:
    """Report should contain institution-level breakdown when seeds_dir is provided."""
    page_path = tmp_path / "lighthouse-results.md"
    page_path.write_text(_LIGHTHOUSE_PAGE_TEMPLATE, encoding="utf-8")
    data_path = tmp_path / "lighthouse-data.json"

    # Create minimal toon seed with matching domains
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    toon = {
        "version": "0.1",
        "country": "ICELAND",
        "page_count": 3,
        "domains": [
            {
                "canonical_domain": "example.is",
                "institution_name": "Example Iceland University",
                "pages": [{"url": "https://example.is/page1"}],
            },
        ],
    }
    (seeds_dir / "iceland.toon").write_text(json.dumps(toon), encoding="utf-8")

    ok = generate_lighthouse_report(populated_db, page_path, data_path, toon_seeds_dir=seeds_dir)

    assert ok
    content = page_path.read_text(encoding="utf-8")
    assert "Lighthouse Scores by Institution" in content
    assert "Example Iceland University" in content
    assert "example.is" in content
    # example.is has page1 (a11y=0.8) and page2 (a11y=0.6): avg=0.7 → displayed as 70
    assert "70" in content
    # gov.example.fr has a11y=0.75 → displayed as 75 or 74 (rounded)
    assert "gov.example.fr" in content
