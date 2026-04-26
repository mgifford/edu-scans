"""Tests for the accessibility report generator."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.cli.generate_accessibility_report import (
    _build_stats_block,
    _query_by_country,
    _query_country_detail,
    _query_summary,
    generate_accessibility_report,
)
from src.storage.schema import initialize_schema


_ACCESSIBILITY_PAGE_TEMPLATE = """\
---
title: Accessibility Statement Scanning
layout: page
---

# Accessibility Statement Scanning

<!-- ACCESSIBILITY_STATS_START -->

_No scan data yet._

<!-- ACCESSIBILITY_STATS_END -->
"""


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """Return path to a freshly initialized empty database."""
    db_path = tmp_path / "test.db"
    initialize_schema(f"sqlite:///{db_path}")
    return db_path


@pytest.fixture
def populated_db(tmp_path: Path) -> Path:
    """Return a database with representative accessibility scan data."""
    db_path = tmp_path / "test.db"
    initialize_schema(f"sqlite:///{db_path}")

    conn = sqlite3.connect(db_path)
    try:
        rows = [
            (
                "https://example.se/home",
                "SWEDEN",
                "scan-se-001",
                1,
                1,
                1,
                '["https://example.se/accessibility"]',
                '["tillganglighetsredogorelse"]',
                "",
                "2026-04-01T10:00:00+00:00",
            ),
            (
                "https://example.se/about",
                "SWEDEN",
                "scan-se-001",
                1,
                0,
                0,
                "[]",
                "[]",
                "",
                "2026-04-01T10:05:00+00:00",
            ),
            (
                "https://example.se/down",
                "SWEDEN",
                "scan-se-001",
                0,
                0,
                0,
                "[]",
                "[]",
                "Timeout",
                "2026-04-01T10:07:00+00:00",
            ),
            (
                "https://gov.example.fi/start",
                "FINLAND",
                "scan-fi-001",
                1,
                1,
                0,
                '["https://gov.example.fi/accessibility"]',
                '["saavutettavuusseloste"]',
                "",
                "2026-04-02T09:00:00+00:00",
            ),
            (
                "https://gov.example.fi/start",
                "FINLAND",
                "scan-fi-002",
                1,
                1,
                1,
                '["https://gov.example.fi/accessibility", "https://gov.example.fi/a11y"]',
                '["saavutettavuusseloste", "accessibility statement"]',
                "",
                "2026-04-03T09:00:00+00:00",
            ),
            (
                "https://gov.example.fi/contact",
                "FINLAND",
                "scan-fi-001",
                1,
                0,
                0,
                "[]",
                "[]",
                "",
                "2026-04-02T09:05:00+00:00",
            ),
        ]
        for row in rows:
            conn.execute(
                """
                INSERT INTO url_accessibility_results
                (url, country_code, scan_id, is_reachable, has_statement,
                 found_in_footer, statement_links, matched_terms,
                 error_message, scanned_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
        conn.commit()
    finally:
        conn.close()

    return db_path


def test_query_country_detail_empty_db(empty_db: Path) -> None:
    """Country detail should be empty when there are no scan rows."""
    conn = sqlite3.connect(empty_db)
    conn.row_factory = sqlite3.Row
    try:
        result = _query_country_detail(conn)
    finally:
        conn.close()

    assert result == {}


def test_query_country_detail_groups_pages_and_domains(populated_db: Path) -> None:
    """Country detail should expose page evidence and domain rollups."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        result = _query_country_detail(conn)
    finally:
        conn.close()

    sweden = result["SWEDEN"]
    assert sweden["pages_with_statement"][0]["url"] == "https://example.se/home"
    assert sweden["pages_without_statement"][0]["url"] == "https://example.se/about"
    assert sweden["unreachable_pages"][0]["error_message"] == "Timeout"
    assert sweden["domains"] == [
        {
            "domain": "example.se",
            "total_pages": 3,
            "reachable_pages": 2,
            "has_statement_pages": 1,
            "no_statement_pages": 1,
            "found_in_footer_pages": 1,
            "unreachable_pages": 1,
        }
    ]


def test_query_country_detail_merges_duplicate_page_rows(populated_db: Path) -> None:
    """Multiple scan rows for one page should merge into one evidence record."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        result = _query_country_detail(conn)
    finally:
        conn.close()

    finland = result["FINLAND"]["pages_with_statement"]
    assert len(finland) == 1
    assert finland[0]["found_in_footer"] is True
    assert finland[0]["statement_links"] == [
        "https://gov.example.fi/accessibility",
        "https://gov.example.fi/a11y",
    ]
    assert finland[0]["matched_terms"] == [
        "saavutettavuusseloste",
        "accessibility statement",
    ]


def test_build_stats_block_mentions_country_evidence(populated_db: Path) -> None:
    """Stats block should explain the JSON evidence and table drilldowns."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        summary = _query_summary(conn)
        by_country = _query_by_country(conn)
    finally:
        conn.close()

    block = _build_stats_block(summary, "2026-04-07 12:00 UTC", by_country=by_country)

    assert "page-level evidence" in block
    assert "per-domain summary" in block
    assert "accessibility-data.json" in block
    assert "Hover or focus any non-zero count" in block
    assert "Full machine-readable data is available" in block


def test_generate_accessibility_report_writes_country_detail(
    populated_db: Path,
    tmp_path: Path,
) -> None:
    """Generated JSON should include per-country page and domain evidence."""
    page_path = tmp_path / "accessibility-statements.md"
    page_path.write_text(_ACCESSIBILITY_PAGE_TEMPLATE, encoding="utf-8")
    data_path = tmp_path / "accessibility-data.json"

    result = generate_accessibility_report(populated_db, page_path, data_path)

    assert result is True
    data = json.loads(data_path.read_text(encoding="utf-8"))
    assert data["country_detail"]["SWEDEN"]["pages_with_statement"][0]["domain"] == "example.se"
    assert data["country_detail"]["SWEDEN"]["pages_without_statement"][0]["url"] == "https://example.se/about"
    assert data["country_detail"]["FINLAND"]["domains"][0]["has_statement_pages"] == 1

    content = page_path.read_text(encoding="utf-8")
    assert "page-level evidence" in content
    assert "Hover or focus any non-zero count" in content


def test_query_summary_counts_domains_not_urls(populated_db: Path) -> None:
    """_query_summary should count distinct domains, not individual URLs."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        result = _query_summary(conn)
    finally:
        conn.close()

    # populated_db has 3 URLs under example.se and 2 distinct URLs under
    # gov.example.fi → 2 distinct domains total (not 5 URLs)
    assert result["total_scanned"] == 2
    # example.se has has_statement=True; gov.example.fi also has has_statement=True
    assert result["total_has_statement"] == 2
    # both domains have at least one reachable URL
    assert result["total_reachable"] == 2


def test_query_by_country_counts_domains_not_urls(populated_db: Path) -> None:
    """_query_by_country should report domain counts, not URL counts."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_by_country(conn)
    finally:
        conn.close()

    by_cc = {r["country_code"]: r for r in rows}

    # Sweden: 3 URLs all under example.se → 1 domain
    assert by_cc["SWEDEN"]["total_scanned"] == 1
    # MAX(is_reachable) across example.se URLs: max(1, 1, 0) = 1
    assert by_cc["SWEDEN"]["reachable"] == 1
    # MAX(has_statement) across example.se URLs: max(1, 0, 0) = 1
    assert by_cc["SWEDEN"]["has_statement"] == 1

    # Finland: gov.example.fi/start and gov.example.fi/contact → 1 domain
    assert by_cc["FINLAND"]["total_scanned"] == 1
    assert by_cc["FINLAND"]["reachable"] == 1
    assert by_cc["FINLAND"]["has_statement"] == 1


def test_build_stats_block_uses_domain_language(populated_db: Path) -> None:
    """Stats block should use 'domains' rather than 'pages' for scan counts."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        summary = _query_summary(conn)
        by_country = _query_by_country(conn)
    finally:
        conn.close()

    block = _build_stats_block(summary, "2026-04-07 12:00 UTC", by_country=by_country)

    assert "domains scanned" in block
    assert "reachable domains" in block.lower() or "domains were reachable" in block
