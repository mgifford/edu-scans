"""Tests for the third-party JavaScript stats report generator."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from src.cli.generate_third_party_js_report import (
    _aggregate_script_counts,
    _build_stats_block,
    _query_by_country,
    _query_country_drilldowns,
    _query_script_rows,
    _query_summary,
    _sanitize_script_src,
    generate_third_party_js_report,
)
from src.storage.schema import initialize_schema


_STATS_MARKER_START = "<!-- THIRD_PARTY_JS_STATS_START -->"
_STATS_MARKER_END = "<!-- THIRD_PARTY_JS_STATS_END -->"

_PAGE_TEMPLATE = """\
---
title: Third-Party JavaScript
layout: page
---

# Third-Party JavaScript

<!-- THIRD_PARTY_JS_STATS_START -->

_No scan data yet._

<!-- THIRD_PARTY_JS_STATS_END -->

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
    """Return path to a database with sample third-party JS scan data."""
    db_path = tmp_path / "test.db"
    initialize_schema(f"sqlite:///{db_path}")

    conn = sqlite3.connect(db_path)
    try:
        rows = [
            (
                "https://example.is/page1",
                "ICELAND",
                "3pjs-ICELAND-001",
                1,
                json.dumps(
                    [
                        {
                            "src": "https://www.googletagmanager.com/gtm.js?id=GTM-AAA",
                            "host": "www.googletagmanager.com",
                            "service_name": "Google Tag Manager",
                            "version": "GTM-AAA",
                            "categories": ["Tag Manager"],
                        },
                        {
                            "src": "https://cdn.cookielaw.org/script.js",
                            "host": "cdn.cookielaw.org",
                            "service_name": "OneTrust",
                            "version": None,
                            "categories": ["Cookie Consent"],
                        },
                    ]
                ),
                None,
                "2024-06-01T10:00:00+00:00",
            ),
            (
                "https://example.is/page2",
                "ICELAND",
                "3pjs-ICELAND-001",
                1,
                "[]",
                None,
                "2024-06-01T10:01:00+00:00",
            ),
            (
                "https://example.fr/page1",
                "FRANCE",
                "3pjs-FRANCE-001",
                1,
                json.dumps(
                    [
                        {
                            "src": "https://www.googletagmanager.com/gtm.js?id=GTM-BBB",
                            "host": "www.googletagmanager.com",
                            "service_name": "Google Tag Manager",
                            "version": "GTM-BBB",
                            "categories": ["Tag Manager"],
                        }
                    ]
                ),
                None,
                "2024-06-02T08:00:00+00:00",
            ),
            (
                "https://example.fr/page2",
                "FRANCE",
                "3pjs-FRANCE-001",
                0,
                "[]",
                "Connection error",
                "2024-06-02T08:01:00+00:00",
            ),
        ]
        for row in rows:
            conn.execute(
                """
                INSERT INTO url_third_party_js_results
                (url, country_code, scan_id, is_reachable, scripts, error_message, scanned_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
        conn.commit()
    finally:
        conn.close()

    return db_path


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

    assert result["total_batches"] == 2
    assert result["total_scanned"] == 4
    assert result["total_reachable"] == 3
    assert result["urls_with_scripts"] == 2


def test_query_script_rows_populated_db(populated_db: Path) -> None:
    """Should return latest reachable rows for aggregation."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_script_rows(conn)
    finally:
        conn.close()

    assert len(rows) == 3
    urls = {row["url"] for row in rows}
    assert "https://example.fr/page2" not in urls


def test_query_by_country_populated_db(populated_db: Path) -> None:
    """Should return per-country rows sorted alphabetically."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_by_country(conn)
    finally:
        conn.close()

    assert [row["country_code"] for row in rows] == ["FRANCE", "ICELAND"]
    france = rows[0]
    assert france["total_scanned"] == 2
    assert france["reachable"] == 1


def test_query_country_drilldowns_populated_db(populated_db: Path) -> None:
    """Should expose country drilldowns for page and service evidence."""
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _query_country_drilldowns(conn)
    finally:
        conn.close()

    assert rows["ICELAND"]["scanned"][0]["page_url"] == "https://example.is/page1"
    assert rows["ICELAND"]["urls_with_scripts"][0]["service_names"] == [
        "Google Tag Manager",
        "OneTrust",
    ]
    assert rows["ICELAND"]["service_loads"][0]["service_name"] == "Google Tag Manager"


def test_aggregate_script_counts() -> None:
    """Should count known services and categories correctly."""
    rows = [
        {
            "url": "https://example.is/page1",
            "scripts": json.dumps(
                [
                    {"service_name": "Google Tag Manager", "categories": ["Tag Manager"]},
                    {"service_name": "OneTrust", "categories": ["Cookie Consent"]},
                ]
            ),
        },
        {
            "url": "https://example.fr/page1",
            "scripts": json.dumps(
                [
                    {"service_name": "Google Tag Manager", "categories": ["Tag Manager"]},
                    {"service_name": None, "categories": ["CDN"]},
                ]
            ),
        },
    ]

    service_counts, category_counts, identified_scripts = _aggregate_script_counts(rows)
    assert service_counts["Google Tag Manager"] == 2
    assert service_counts["OneTrust"] == 1
    assert category_counts["Tag Manager"] == 2
    assert category_counts["Cookie Consent"] == 1
    assert identified_scripts == 3


def test_build_stats_block_empty_summary() -> None:
    """Should return a placeholder block when no summary data is available."""
    block = _build_stats_block({}, {}, {}, 0, "2024-06-01 12:00 UTC")
    assert _STATS_MARKER_START in block
    assert _STATS_MARKER_END in block
    assert "No scan data yet" in block


def test_build_stats_block_with_data() -> None:
    """Should produce a block containing the key stat figures."""
    summary = {
        "total_batches": 10,
        "total_scanned": 500,
        "total_reachable": 450,
        "urls_with_scripts": 200,
        "last_scan": "2024-06-01T11:30:00+00:00",
    }
    block = _build_stats_block(
        summary=summary,
        service_counts=Counter({"Google Tag Manager": 120, "OneTrust": 50}),
        category_counts=Counter({"Tag Manager": 120, "Cookie Consent": 50}),
        identified_scripts=170,
        generated_at="2024-06-01 12:00 UTC",
        total_available=1000,
        by_country=[
            {
                "country_code": "ICELAND",
                "total_scanned": 100,
                "reachable": 95,
                "urls_with_scripts": 20,
                "last_scan": "2024-06-01T11:00:00+00:00",
            }
        ],
        identified_by_country={"ICELAND": 25},
        seed_counts={"ICELAND": 120},
    )

    assert "**500** of **1,000** available pages scanned" in block
    assert "**200** reachable pages loaded at least one third-party script" in block
    assert "Top Third-Party Services" in block
    assert "Google Tag Manager" in block
    assert "Third-Party JavaScript by Country" in block


def test_generate_third_party_js_report_with_data(
    populated_db: Path, tmp_path: Path
) -> None:
    """Should update the page and write the JSON data file."""
    page_path = tmp_path / "third-party-tools.md"
    page_path.write_text(_PAGE_TEMPLATE, encoding="utf-8")
    data_path = tmp_path / "third-party-tools-data.json"

    ok = generate_third_party_js_report(populated_db, page_path, data_path)

    assert ok is True
    page_content = page_path.read_text(encoding="utf-8")
    data = json.loads(data_path.read_text(encoding="utf-8"))

    assert "Top Third-Party Services" in page_content
    assert "Google Tag Manager" in page_content
    assert data["summary"]["total_scanned"] == 4
    assert data["summary"]["urls_with_scripts"] == 2
    assert data["top_services"][0]["name"] == "Google Tag Manager"
    assert data["country_drilldowns"]["ICELAND"]["service_loads"][0]["service_name"] == "Google Tag Manager"


def test_sanitize_script_src_removes_key_param() -> None:
    """Should strip the ``key`` query parameter from a Maps URL."""
    src = "https://maps.googleapis.com/maps/api/js?v=3&key=FAKE_KEY_FOR_TESTING_ONLY&ver=4.27.6"
    expected = "https://maps.googleapis.com/maps/api/js?v=3&ver=4.27.6"
    result = _sanitize_script_src(src)
    assert result == expected


def test_sanitize_script_src_removes_token_param() -> None:
    """Should strip the ``token`` query parameter."""
    src = "https://cdn.example.com/script.js?token=FAKE_TOKEN_FOR_TESTING&version=2"
    expected = "https://cdn.example.com/script.js?version=2"
    result = _sanitize_script_src(src)
    assert result == expected


def test_sanitize_script_src_no_query_unchanged() -> None:
    """Should return URLs without query strings unchanged."""
    src = "https://kit.fontawesome.com/f6f4ea8fb9.js"
    assert _sanitize_script_src(src) == src


def test_sanitize_script_src_empty_unchanged() -> None:
    """Should return empty string unchanged."""
    assert _sanitize_script_src("") == ""


def test_sanitize_script_src_no_sensitive_params_unchanged() -> None:
    """Should return URLs whose query params are not sensitive unchanged."""
    src = "https://www.googletagmanager.com/gtm.js?id=GTM-AAA"
    assert _sanitize_script_src(src) == src
