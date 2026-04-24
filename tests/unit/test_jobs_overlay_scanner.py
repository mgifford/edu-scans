"""Unit tests for the accessibility overlay scanner job."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.jobs.overlay_scanner import OverlayScannerJob
from src.lib.settings import Settings
from src.services.overlay_scanner import OverlayScanResult


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


def _make_job(settings: Settings) -> OverlayScannerJob:
    job = OverlayScannerJob(settings)
    job.scanner = MagicMock()
    return job


def _make_result(
    url: str,
    overlays: list[str] | None = None,
    error: str | None = None,
    reachable: bool = True,
) -> OverlayScanResult:
    overlays = overlays or []
    return OverlayScanResult(
        url=url,
        is_reachable=reachable,
        overlays=overlays,
        error_message=error,
        scanned_at="2024-01-01T00:00:00+00:00",
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
# _update_toon_with_overlays
# ---------------------------------------------------------------------------


def test_update_toon_adds_overlays(temp_settings):
    job = _make_job(temp_settings)
    toon_data = {
        "domains": [{"pages": [{"url": "https://gov.example/"}]}]
    }
    scan_results = {
        "https://gov.example/": _make_result(
            "https://gov.example/", overlays=["UserWay"]
        ),
    }
    updated = job._update_toon_with_overlays(toon_data, scan_results)
    page = updated["domains"][0]["pages"][0]
    assert "overlays" in page
    assert page["overlays"] == ["UserWay"]


def test_update_toon_no_overlays_empty_list(temp_settings):
    job = _make_job(temp_settings)
    toon_data = {"domains": [{"pages": [{"url": "https://gov.example/"}]}]}
    scan_results = {
        "https://gov.example/": _make_result("https://gov.example/"),
    }
    updated = job._update_toon_with_overlays(toon_data, scan_results)
    page = updated["domains"][0]["pages"][0]
    assert page["overlays"] == []
    assert "overlay_error" not in page


def test_update_toon_adds_error_field_when_unreachable(temp_settings):
    job = _make_job(temp_settings)
    toon_data = {"domains": [{"pages": [{"url": "https://fail.gov/"}]}]}
    scan_results = {
        "https://fail.gov/": _make_result(
            "https://fail.gov/", error="Timeout", reachable=False
        ),
    }
    updated = job._update_toon_with_overlays(toon_data, scan_results)
    page = updated["domains"][0]["pages"][0]
    assert page["overlay_error"] == "Timeout"
    assert "overlays" not in page


def test_update_toon_skips_missing_urls(temp_settings):
    job = _make_job(temp_settings)
    toon_data = {"domains": [{"pages": [{"url": "https://gov.example/"}]}]}
    updated = job._update_toon_with_overlays(toon_data, scan_results={})
    page = updated["domains"][0]["pages"][0]
    assert "overlays" not in page
    assert "overlay_error" not in page


# ---------------------------------------------------------------------------
# _save_results
# ---------------------------------------------------------------------------


def test_save_results_persists_to_db(temp_settings):
    job = _make_job(temp_settings)
    results = [_make_result("https://gov.example/", overlays=["UserWay"])]
    job._save_results(results, "TESTLAND", "scan-001")

    conn = sqlite3.connect(job.db_path)
    rows = conn.execute(
        "SELECT url, country_code, scan_id, is_reachable, overlays, overlay_count "
        "FROM url_overlay_results"
    ).fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0][0] == "https://gov.example/"
    assert rows[0][1] == "TESTLAND"
    assert rows[0][2] == "scan-001"
    assert rows[0][3] == 1  # is_reachable stored as 1
    assert json.loads(rows[0][4]) == ["UserWay"]
    assert rows[0][5] == 1  # overlay_count


def test_save_results_no_overlays(temp_settings):
    job = _make_job(temp_settings)
    result = _make_result("https://clean.gov/")
    job._save_results([result], "TESTLAND", "scan-002")

    conn = sqlite3.connect(job.db_path)
    row = conn.execute(
        "SELECT overlays, overlay_count FROM url_overlay_results WHERE url = ?",
        ("https://clean.gov/",),
    ).fetchone()
    conn.close()

    assert json.loads(row[0]) == []
    assert row[1] == 0


def test_save_results_error_entry(temp_settings):
    job = _make_job(temp_settings)
    result = _make_result("https://fail.gov/", error="Connection failed", reachable=False)
    job._save_results([result], "TESTLAND", "scan-003")

    conn = sqlite3.connect(job.db_path)
    row = conn.execute(
        "SELECT is_reachable, error_message FROM url_overlay_results WHERE url = ?",
        ("https://fail.gov/",),
    ).fetchone()
    conn.close()

    assert row[0] == 0  # is_reachable = False stored as 0
    assert row[1] == "Connection failed"


# ---------------------------------------------------------------------------
# scan_country
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_country_returns_stats(temp_settings, sample_toon):
    job = _make_job(temp_settings)

    mock_results = {
        "https://gov.example/": _make_result(
            "https://gov.example/", overlays=["UserWay"]
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
    assert stats["urls_with_overlays"] == 1
    assert stats["total_overlay_detections"] == 1
    assert stats["vendor_counts"] == {"UserWay": 1}


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
    job = _make_job(temp_settings)

    mock_results = {
        "https://gov.example/": _make_result("https://gov.example/"),
    }
    job.scanner.scan_urls_batch = AsyncMock(return_value=mock_results)

    stats = await job.scan_country("TESTLAND", sample_toon)

    assert stats["urls_scanned"] == 1
    assert stats["is_complete"] is False


@pytest.mark.asyncio
async def test_scan_country_unreachable_url(temp_settings, sample_toon):
    job = _make_job(temp_settings)

    mock_results = {
        "https://gov.example/": _make_result(
            "https://gov.example/", error="Timeout", reachable=False
        ),
        "https://gov.example/about": _make_result("https://gov.example/about"),
    }
    job.scanner.scan_urls_batch = AsyncMock(return_value=mock_results)

    stats = await job.scan_country("TESTLAND", sample_toon)

    assert stats["reachable_count"] == 1
    assert stats["unreachable_count"] == 1


@pytest.mark.asyncio
async def test_scan_country_writes_toon_output(temp_settings, sample_toon):
    job = _make_job(temp_settings)

    mock_results = {
        "https://gov.example/": _make_result(
            "https://gov.example/", overlays=["AudioEye"]
        ),
        "https://gov.example/about": _make_result("https://gov.example/about"),
    }
    job.scanner.scan_urls_batch = AsyncMock(return_value=mock_results)

    stats = await job.scan_country("TESTLAND", sample_toon)

    output_path = Path(stats["output_path"])
    assert output_path.exists()
    data = json.loads(output_path.read_text())
    page = data["domains"][0]["pages"][0]
    assert "overlays" in page
    assert page["overlays"] == ["AudioEye"]


@pytest.mark.asyncio
async def test_scan_country_aggregates_vendor_counts(temp_settings, sample_toon):
    """vendor_counts sums the same overlay seen across multiple URLs."""
    job = _make_job(temp_settings)

    mock_results = {
        "https://gov.example/": _make_result(
            "https://gov.example/", overlays=["UserWay"]
        ),
        "https://gov.example/about": _make_result(
            "https://gov.example/about", overlays=["UserWay"]
        ),
    }
    job.scanner.scan_urls_batch = AsyncMock(return_value=mock_results)

    stats = await job.scan_country("TESTLAND", sample_toon)
    assert stats["vendor_counts"]["UserWay"] == 2


@pytest.mark.asyncio
async def test_scan_country_passes_max_runtime(temp_settings, sample_toon):
    import time

    job = _make_job(temp_settings)
    job.scanner.scan_urls_batch = AsyncMock(return_value={})

    t0 = time.monotonic()
    await job.scan_country("TESTLAND", sample_toon, max_runtime_seconds=60.0, start_time=t0)

    _, kwargs = job.scanner.scan_urls_batch.call_args
    assert kwargs["max_runtime_seconds"] == 60.0
    assert kwargs["start_time"] == t0


# ---------------------------------------------------------------------------
# scan_all_countries
# ---------------------------------------------------------------------------


@pytest.fixture
def toon_seeds_dir(tmp_path):
    """Directory with two TOON seed files."""
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
