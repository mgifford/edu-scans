"""Unit tests for the accessibility scanner job."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from datetime import datetime, timezone

from src.jobs.accessibility_scanner import AccessibilityScannerJob
from src.lib.settings import Settings
from src.services.accessibility_scanner import AccessibilityScanResult
from src.storage.schema import initialize_schema


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_settings(tmp_path):
    db_path = tmp_path / "test.db"
    return Settings(
        scheduler_cadence="monthly",
        crawl_rate_limit_per_host=0.5,
        crawl_timeout_seconds=2,
        toon_output_dir=tmp_path / "toon-cache",
        metadata_db_url=f"sqlite:///{db_path}",
    )


@pytest.fixture
def sample_toon(tmp_path) -> Path:
    data = {
        "version": "0.1-seed",
        "country": "TESTLAND",
        "domains": [
            {
                "canonical_domain": "gov.example",
                "pages": [
                    {"url": "https://gov.example/", "is_root_page": True},
                    {"url": "https://gov.example/about", "is_root_page": False},
                ],
            }
        ],
    }
    toon_file = tmp_path / "testland.toon"
    toon_file.write_text(json.dumps(data), encoding="utf-8")
    return toon_file


@pytest.fixture
def empty_toon(tmp_path) -> Path:
    data = {"version": "0.1-seed", "country": "EMPTY", "domains": []}
    toon_file = tmp_path / "empty.toon"
    toon_file.write_text(json.dumps(data), encoding="utf-8")
    return toon_file


def _make_job(settings: Settings) -> AccessibilityScannerJob:
    job = AccessibilityScannerJob(settings)
    job.scanner = MagicMock()
    return job


def _make_result(
    url: str,
    has_statement: bool = False,
    found_in_footer: bool = False,
    is_reachable: bool = True,
    error: str | None = None,
) -> AccessibilityScanResult:
    now = datetime.now(timezone.utc).isoformat()
    return AccessibilityScanResult(
        url=url,
        is_reachable=is_reachable,
        has_statement=has_statement,
        found_in_footer=found_in_footer,
        statement_links=["/accessibility"] if has_statement else [],
        matched_terms=["accessibility"] if has_statement else [],
        error_message=error,
        scanned_at=now,
    )


# ---------------------------------------------------------------------------
# _load_toon_file / _extract_urls_from_toon
# ---------------------------------------------------------------------------


def test_load_toon_file(temp_settings, sample_toon):
    job = _make_job(temp_settings)
    data = job._load_toon_file(sample_toon)
    assert data["country"] == "TESTLAND"


def test_extract_urls_from_toon(temp_settings, sample_toon):
    job = _make_job(temp_settings)
    data = job._load_toon_file(sample_toon)
    urls = job._extract_urls_from_toon(data)
    assert urls == ["https://gov.example/", "https://gov.example/about"]


def test_extract_urls_empty_toon(temp_settings, empty_toon):
    job = _make_job(temp_settings)
    data = job._load_toon_file(empty_toon)
    assert job._extract_urls_from_toon(data) == []


# ---------------------------------------------------------------------------
# _update_toon_with_accessibility
# ---------------------------------------------------------------------------


def test_update_toon_adds_accessibility_data(temp_settings):
    job = _make_job(temp_settings)
    toon_data = {"domains": [{"pages": [{"url": "https://gov.example/"}]}]}
    scan_results = {
        "https://gov.example/": _make_result(
            "https://gov.example/", has_statement=True, found_in_footer=True
        ),
    }
    updated = job._update_toon_with_accessibility(toon_data, scan_results)
    page = updated["domains"][0]["pages"][0]
    assert "accessibility" in page
    assert page["accessibility"]["has_statement"] is True
    assert page["accessibility"]["found_in_footer"] is True
    assert page["accessibility"]["statement_links"] == ["/accessibility"]


def test_update_toon_adds_error_field(temp_settings):
    job = _make_job(temp_settings)
    toon_data = {"domains": [{"pages": [{"url": "https://fail.gov/"}]}]}
    scan_results = {
        "https://fail.gov/": _make_result(
            "https://fail.gov/", is_reachable=False, error="Timeout"
        ),
    }
    updated = job._update_toon_with_accessibility(toon_data, scan_results)
    page = updated["domains"][0]["pages"][0]
    assert page["accessibility_error"] == "Timeout"
    assert "accessibility" not in page


def test_update_toon_skips_missing_urls(temp_settings):
    job = _make_job(temp_settings)
    toon_data = {"domains": [{"pages": [{"url": "https://gov.example/"}]}]}
    updated = job._update_toon_with_accessibility(toon_data, scan_results={})
    page = updated["domains"][0]["pages"][0]
    assert "accessibility" not in page
    assert "accessibility_error" not in page


def test_update_toon_reachable_with_error_adds_accessibility(temp_settings):
    """A reachable URL with an error_message still gets an accessibility dict."""
    job = _make_job(temp_settings)
    toon_data = {"domains": [{"pages": [{"url": "https://gov.example/"}]}]}
    # is_reachable=True but has an error_message -> not an error entry
    result = _make_result("https://gov.example/", has_statement=False, is_reachable=True, error="Minor parse error")
    scan_results = {"https://gov.example/": result}
    updated = job._update_toon_with_accessibility(toon_data, scan_results)
    page = updated["domains"][0]["pages"][0]
    assert "accessibility" in page


# ---------------------------------------------------------------------------
# _save_accessibility_results
# ---------------------------------------------------------------------------


def test_save_accessibility_results_persists_to_db(temp_settings):
    job = _make_job(temp_settings)
    results = [
        _make_result("https://gov.example/", has_statement=True, found_in_footer=True)
    ]
    job._save_accessibility_results(results, "TESTLAND", "scan-001")

    conn = sqlite3.connect(job.db_path)
    row = conn.execute(
        """
        SELECT url, country_code, scan_id, is_reachable,
               has_statement, found_in_footer, statement_links, matched_terms
        FROM url_accessibility_results
        """
    ).fetchone()
    conn.close()

    assert row[0] == "https://gov.example/"
    assert row[1] == "TESTLAND"
    assert row[2] == "scan-001"
    assert row[3] == 1  # is_reachable = True
    assert row[4] == 1  # has_statement = True
    assert row[5] == 1  # found_in_footer = True
    assert json.loads(row[6]) == ["/accessibility"]
    assert json.loads(row[7]) == ["accessibility"]


def test_save_accessibility_results_unreachable(temp_settings):
    job = _make_job(temp_settings)
    result = _make_result("https://fail.gov/", is_reachable=False, error="Refused")
    job._save_accessibility_results([result], "TESTLAND", "scan-002")

    conn = sqlite3.connect(job.db_path)
    row = conn.execute(
        "SELECT is_reachable, error_message FROM url_accessibility_results WHERE url = ?",
        ("https://fail.gov/",),
    ).fetchone()
    conn.close()

    assert row[0] == 0
    assert row[1] == "Refused"


def test_save_accessibility_results_multiple(temp_settings):
    job = _make_job(temp_settings)
    results = [
        _make_result("https://a.gov/"),
        _make_result("https://b.gov/", has_statement=True),
    ]
    job._save_accessibility_results(results, "MULTI", "scan-003")

    conn = sqlite3.connect(job.db_path)
    count = conn.execute("SELECT COUNT(*) FROM url_accessibility_results").fetchone()[0]
    conn.close()

    assert count == 2


# ---------------------------------------------------------------------------
# _get_last_scan_time_per_country
# ---------------------------------------------------------------------------


def test_get_last_scan_time_per_country_empty_db(temp_settings):
    job = _make_job(temp_settings)
    result = job._get_last_scan_time_per_country()
    assert result == {}


def test_get_last_scan_time_per_country_with_data(temp_settings):
    job = _make_job(temp_settings)
    results = [_make_result("https://gov.example/")]
    job._save_accessibility_results(results, "TESTLAND", "scan-001")

    times = job._get_last_scan_time_per_country()
    assert "TESTLAND" in times


# ---------------------------------------------------------------------------
# _get_recently_scanned_urls
# ---------------------------------------------------------------------------


def test_get_recently_scanned_urls_empty_db(temp_settings):
    job = _make_job(temp_settings)
    urls = job._get_recently_scanned_urls("TESTLAND", within_days=7)
    assert urls == set()


def test_get_recently_scanned_urls_returns_recent_url(temp_settings):
    job = _make_job(temp_settings)
    results = [_make_result("https://gov.example/")]
    job._save_accessibility_results(results, "TESTLAND", "scan-001")

    urls = job._get_recently_scanned_urls("TESTLAND", within_days=7)
    assert urls == {"https://gov.example/"}


# ---------------------------------------------------------------------------
# scan_country
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_country_returns_stats(temp_settings, sample_toon):
    job = _make_job(temp_settings)

    mock_results = {
        "https://gov.example/": _make_result(
            "https://gov.example/", has_statement=True, found_in_footer=True
        ),
        "https://gov.example/about": _make_result("https://gov.example/about"),
    }
    job.scanner.scan_urls_batch = AsyncMock(return_value=mock_results)

    stats = await job.scan_country("TESTLAND", sample_toon)

    assert stats["country_code"] == "TESTLAND"
    assert stats["total_urls"] == 2
    assert stats["urls_scanned"] == 2
    assert stats["is_complete"] is True
    assert stats["reachable_count"] == 2
    assert stats["unreachable_count"] == 0
    assert stats["has_statement_count"] == 1
    assert stats["found_in_footer_count"] == 1


@pytest.mark.asyncio
async def test_scan_country_empty_toon(temp_settings, empty_toon):
    job = _make_job(temp_settings)
    job.scanner.scan_urls_batch = AsyncMock(return_value={})

    stats = await job.scan_country("EMPTY", empty_toon)

    assert stats["total_urls"] == 0
    assert stats["urls_scanned"] == 0
    assert stats["is_complete"] is True


@pytest.mark.asyncio
async def test_scan_country_partial_results(temp_settings, sample_toon):
    """When only some URLs are scanned, is_complete is False."""
    job = _make_job(temp_settings)

    mock_results = {
        "https://gov.example/": _make_result("https://gov.example/"),
    }
    job.scanner.scan_urls_batch = AsyncMock(return_value=mock_results)

    stats = await job.scan_country("TESTLAND", sample_toon)

    assert stats["urls_scanned"] == 1
    assert stats["is_complete"] is False


@pytest.mark.asyncio
async def test_scan_country_writes_toon_output(temp_settings, sample_toon):
    job = _make_job(temp_settings)

    mock_results = {
        "https://gov.example/": _make_result(
            "https://gov.example/", has_statement=True, found_in_footer=True
        ),
        "https://gov.example/about": _make_result("https://gov.example/about"),
    }
    job.scanner.scan_urls_batch = AsyncMock(return_value=mock_results)

    stats = await job.scan_country("TESTLAND", sample_toon)

    output_path = Path(stats["output_path"])
    assert output_path.exists()
    assert "_accessibility" in output_path.name

    data = json.loads(output_path.read_text())
    page = data["domains"][0]["pages"][0]
    assert "accessibility" in page


@pytest.mark.asyncio
async def test_scan_country_skips_recently_scanned_all(temp_settings, sample_toon):
    """When all URLs were recently scanned, no HTTP requests are made."""
    job = _make_job(temp_settings)

    # Pre-populate the DB so both URLs are "recently scanned"
    results = [
        _make_result("https://gov.example/"),
        _make_result("https://gov.example/about"),
    ]
    job._save_accessibility_results(results, "TESTLAND", "prev-scan")

    job.scanner.scan_urls_batch = AsyncMock(return_value={})

    stats = await job.scan_country("TESTLAND", sample_toon, skip_recently_scanned_days=7)

    # scan_urls_batch should not have been called
    job.scanner.scan_urls_batch.assert_not_called()
    assert stats["urls_skipped_recently_scanned"] == 2
    assert stats["urls_scanned"] == 0


@pytest.mark.asyncio
async def test_scan_country_skips_recently_scanned_partial(temp_settings, sample_toon):
    """Only the non-recently-scanned URL is passed to the scanner."""
    job = _make_job(temp_settings)

    # Mark only the first URL as recently scanned
    job._save_accessibility_results(
        [_make_result("https://gov.example/")], "TESTLAND", "prev-scan"
    )

    mock_results = {
        "https://gov.example/about": _make_result("https://gov.example/about"),
    }
    job.scanner.scan_urls_batch = AsyncMock(return_value=mock_results)

    stats = await job.scan_country("TESTLAND", sample_toon, skip_recently_scanned_days=7)

    assert stats["urls_skipped_recently_scanned"] == 1
    assert stats["urls_scanned"] == 1

    # Verify only the second URL was scanned
    call_args = job.scanner.scan_urls_batch.call_args
    scanned_urls = call_args[0][0]
    assert scanned_urls == ["https://gov.example/about"]


@pytest.mark.asyncio
async def test_scan_country_passes_max_runtime(temp_settings, sample_toon):
    job = _make_job(temp_settings)
    job.scanner.scan_urls_batch = AsyncMock(return_value={})

    t0 = time.monotonic()
    await job.scan_country("TESTLAND", sample_toon, max_runtime_seconds=60.0, start_time=t0)

    _, kwargs = job.scanner.scan_urls_batch.call_args
    assert kwargs["max_runtime_seconds"] == 60.0
    assert kwargs["start_time"] == t0


@pytest.mark.asyncio
async def test_scan_country_incremental_save(temp_settings, sample_toon):
    """on_result callback persists results to DB as they are returned."""
    job = _make_job(temp_settings)

    captured_callbacks: list = []

    async def _mock_batch(urls, *, rate_limit_per_second=2.0, on_result=None, **kwargs):
        results = {}
        for url in urls:
            r = _make_result(url)
            if on_result:
                on_result(r)
                captured_callbacks.append(r)
            results[url] = r
        return results

    job.scanner.scan_urls_batch = _mock_batch

    await job.scan_country("TESTLAND", sample_toon)

    # Both URLs should have been saved
    conn = sqlite3.connect(job.db_path)
    count = conn.execute("SELECT COUNT(*) FROM url_accessibility_results").fetchone()[0]
    conn.close()
    assert count >= 2


# ---------------------------------------------------------------------------
# scan_all_countries
# ---------------------------------------------------------------------------


@pytest.fixture
def toon_seeds_dir(tmp_path):
    page = {"url": "https://a.gov/"}
    for stem in ("alpha", "beta"):
        data = {
            "country": stem.upper(),
            "domains": [{"canonical_domain": f"{stem}.gov", "pages": [page]}],
        }
        (tmp_path / f"{stem}.toon").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


@pytest.mark.asyncio
async def test_scan_all_countries_processes_all(temp_settings, toon_seeds_dir):
    job = _make_job(temp_settings)

    async def _mock_scan(country_code, toon_path, *args, **kwargs):
        return {"country_code": country_code}

    with patch.object(job, "scan_country", side_effect=_mock_scan):
        all_stats = await job.scan_all_countries(toon_seeds_dir)

    assert len(all_stats) == 2
    codes = {s["country_code"] for s in all_stats}
    assert codes == {"ALPHA", "BETA"}


@pytest.mark.asyncio
async def test_scan_all_countries_handles_errors(temp_settings, toon_seeds_dir):
    job = _make_job(temp_settings)

    async def _mock_scan(country_code, toon_path, *args, **kwargs):
        if country_code == "ALPHA":
            raise RuntimeError("Boom")
        return {"country_code": country_code}

    with patch.object(job, "scan_country", side_effect=_mock_scan):
        all_stats = await job.scan_all_countries(toon_seeds_dir)

    assert any("error" in s for s in all_stats)
    assert any(s.get("country_code") == "BETA" for s in all_stats)


@pytest.mark.asyncio
async def test_scan_all_countries_empty_dir(temp_settings, tmp_path):
    job = _make_job(temp_settings)
    all_stats = await job.scan_all_countries(tmp_path)
    assert all_stats == []


@pytest.mark.asyncio
async def test_scan_all_countries_sorts_by_last_scan_when_skip_recent(
    temp_settings, toon_seeds_dir
):
    """When skip_recently_scanned_days>0 countries are sorted by last scan time."""
    job = _make_job(temp_settings)

    scan_order = []

    async def _mock_scan(country_code, toon_path, *args, **kwargs):
        scan_order.append(country_code)
        return {"country_code": country_code}

    # Pre-scan BETA so ALPHA (never scanned) should come first
    job._save_accessibility_results(
        [_make_result("https://a.gov/")], "BETA", "prev-scan"
    )

    with patch.object(job, "scan_country", side_effect=_mock_scan):
        await job.scan_all_countries(toon_seeds_dir, skip_recently_scanned_days=1)

    # ALPHA (never scanned) must come before BETA (recently scanned)
    assert scan_order.index("ALPHA") < scan_order.index("BETA")
