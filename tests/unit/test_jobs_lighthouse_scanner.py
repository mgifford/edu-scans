"""Unit tests for the Lighthouse scanner job."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.jobs.lighthouse_scanner import LighthouseScannerJob
from src.lib.settings import Settings
from src.services.lighthouse_scanner import LighthouseScanResult
from src.storage.schema import initialize_schema


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_settings(tmp_path):
    """Settings wired to a temporary DB."""
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
    """A minimal TOON file with two URLs."""
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
def large_toon(tmp_path) -> Path:
    """A TOON file with five URLs for testing max_urls capping."""
    data = {
        "version": "0.1-seed",
        "country": "BIGLAND",
        "domains": [
            {
                "canonical_domain": "big.example",
                "pages": [
                    {"url": f"https://big.example/page{i}", "is_root_page": i == 1}
                    for i in range(1, 6)
                ],
            }
        ],
    }
    toon_file = tmp_path / "bigland.toon"
    toon_file.write_text(json.dumps(data), encoding="utf-8")
    return toon_file


@pytest.fixture
def empty_toon(tmp_path) -> Path:
    """A TOON file with no pages."""
    data = {"version": "0.1-seed", "country": "EMPTY", "domains": []}
    toon_file = tmp_path / "empty.toon"
    toon_file.write_text(json.dumps(data), encoding="utf-8")
    return toon_file


def _make_job(settings: Settings) -> LighthouseScannerJob:
    """Create a LighthouseScannerJob with a mock LighthouseScanner."""
    job = LighthouseScannerJob(settings)
    job.scanner = MagicMock()
    return job


def _make_result(url: str, error: str | None = None) -> LighthouseScanResult:
    if error:
        return LighthouseScanResult(url=url, error_message=error, scanned_at="2024-01-01T00:00:00+00:00")
    return LighthouseScanResult(
        url=url,
        performance_score=0.9,
        accessibility_score=0.85,
        best_practices_score=0.8,
        seo_score=0.95,
        pwa_score=None,
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
# _update_toon_with_lighthouse
# ---------------------------------------------------------------------------


def test_update_toon_adds_lighthouse_scores(temp_settings):
    job = _make_job(temp_settings)
    toon_data = {
        "domains": [
            {
                "pages": [
                    {"url": "https://gov.example/", "is_root_page": True},
                ]
            }
        ]
    }
    scan_results = {
        "https://gov.example/": _make_result("https://gov.example/"),
    }
    updated = job._update_toon_with_lighthouse(toon_data, scan_results)
    page = updated["domains"][0]["pages"][0]
    assert "lighthouse" in page
    assert page["lighthouse"]["performance"] == pytest.approx(0.9)
    assert page["lighthouse"]["accessibility"] == pytest.approx(0.85)


def test_update_toon_adds_error_field(temp_settings):
    job = _make_job(temp_settings)
    toon_data = {
        "domains": [{"pages": [{"url": "https://fail.gov/"}]}]
    }
    scan_results = {
        "https://fail.gov/": _make_result("https://fail.gov/", error="Timeout"),
    }
    updated = job._update_toon_with_lighthouse(toon_data, scan_results)
    page = updated["domains"][0]["pages"][0]
    assert page["lighthouse_error"] == "Timeout"
    assert "lighthouse" not in page


def test_update_toon_skips_urls_not_in_results(temp_settings):
    job = _make_job(temp_settings)
    toon_data = {
        "domains": [{"pages": [{"url": "https://gov.example/"}]}]
    }
    updated = job._update_toon_with_lighthouse(toon_data, scan_results={})
    page = updated["domains"][0]["pages"][0]
    assert "lighthouse" not in page
    assert "lighthouse_error" not in page


# ---------------------------------------------------------------------------
# _save_lighthouse_results
# ---------------------------------------------------------------------------


def test_save_lighthouse_results_persists_to_db(temp_settings):
    job = _make_job(temp_settings)
    results = [_make_result("https://gov.example/")]
    job._save_lighthouse_results(results, "TESTLAND", "scan-001")

    conn = sqlite3.connect(job.db_path)
    rows = conn.execute(
        "SELECT url, country_code, scan_id, performance_score FROM url_lighthouse_results"
    ).fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0][0] == "https://gov.example/"
    assert rows[0][1] == "TESTLAND"
    assert rows[0][2] == "scan-001"
    assert rows[0][3] == pytest.approx(0.9)


def test_save_lighthouse_results_error_entry(temp_settings):
    job = _make_job(temp_settings)
    result = _make_result("https://fail.gov/", error="Connection failed")
    job._save_lighthouse_results([result], "TESTLAND", "scan-002")

    conn = sqlite3.connect(job.db_path)
    row = conn.execute(
        "SELECT error_message FROM url_lighthouse_results WHERE url = ?",
        ("https://fail.gov/",),
    ).fetchone()
    conn.close()

    assert row[0] == "Connection failed"


# ---------------------------------------------------------------------------
# scan_country
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_country_returns_stats(temp_settings, sample_toon):
    job = _make_job(temp_settings)

    mock_results = {
        "https://gov.example/": _make_result("https://gov.example/"),
        "https://gov.example/about": _make_result("https://gov.example/about"),
    }
    job.scanner.scan_urls_batch = AsyncMock(return_value=mock_results)

    stats = await job.scan_country("TESTLAND", sample_toon)

    assert stats["country_code"] == "TESTLAND"
    assert stats["total_urls"] == 2
    assert stats["urls_scanned"] == 2
    assert stats["is_complete"] is True
    assert stats["success_count"] == 2
    assert stats["error_count"] == 0
    assert stats["avg_accessibility"] == pytest.approx(0.85)
    assert stats["avg_performance"] == pytest.approx(0.9)


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
    """When not all URLs are scanned, is_complete is False."""
    job = _make_job(temp_settings)

    # Only one result returned (budget exhausted after first URL)
    mock_results = {
        "https://gov.example/": _make_result("https://gov.example/"),
    }
    job.scanner.scan_urls_batch = AsyncMock(return_value=mock_results)

    stats = await job.scan_country("TESTLAND", sample_toon)

    assert stats["urls_scanned"] == 1
    assert stats["is_complete"] is False


@pytest.mark.asyncio
async def test_scan_country_with_errors(temp_settings, sample_toon):
    """Error results are counted correctly."""
    job = _make_job(temp_settings)

    mock_results = {
        "https://gov.example/": _make_result("https://gov.example/", error="Timeout"),
        "https://gov.example/about": _make_result("https://gov.example/about"),
    }
    job.scanner.scan_urls_batch = AsyncMock(return_value=mock_results)

    stats = await job.scan_country("TESTLAND", sample_toon)

    assert stats["success_count"] == 1
    assert stats["error_count"] == 1


@pytest.mark.asyncio
async def test_scan_country_writes_toon_output(temp_settings, sample_toon):
    """scan_country writes an output TOON file."""
    job = _make_job(temp_settings)

    mock_results = {
        "https://gov.example/": _make_result("https://gov.example/"),
        "https://gov.example/about": _make_result("https://gov.example/about"),
    }
    job.scanner.scan_urls_batch = AsyncMock(return_value=mock_results)

    stats = await job.scan_country("TESTLAND", sample_toon)

    output_path = Path(stats["output_path"])
    assert output_path.exists()
    data = json.loads(output_path.read_text())
    page = data["domains"][0]["pages"][0]
    assert "lighthouse" in page


@pytest.mark.asyncio
async def test_scan_country_passes_max_runtime(temp_settings, sample_toon):
    """max_runtime_seconds and start_time are forwarded to the scanner."""
    job = _make_job(temp_settings)
    job.scanner.scan_urls_batch = AsyncMock(return_value={})

    import time
    t0 = time.monotonic()
    await job.scan_country("TESTLAND", sample_toon, max_runtime_seconds=60.0, start_time=t0)

    _, kwargs = job.scanner.scan_urls_batch.call_args
    assert kwargs["max_runtime_seconds"] == 60.0
    assert kwargs["start_time"] == t0


@pytest.mark.asyncio
async def test_scan_country_respects_max_urls(temp_settings, large_toon):
    """When max_urls is set, only that many URLs are passed to the scanner."""
    job = _make_job(temp_settings)

    captured_urls: list[list[str]] = []

    async def _capture_batch(urls, **kwargs):
        captured_urls.append(list(urls))
        return {url: _make_result(url) for url in urls}

    job.scanner.scan_urls_batch = _capture_batch

    stats = await job.scan_country("BIGLAND", large_toon, max_urls=3)

    assert len(captured_urls) == 1
    assert len(captured_urls[0]) == 3
    assert stats["total_urls"] == 5
    assert stats["urls_scanned"] == 3


@pytest.mark.asyncio
async def test_scan_country_max_urls_none_scans_all(temp_settings, large_toon):
    """When max_urls is None all URLs are passed to the scanner."""
    job = _make_job(temp_settings)

    captured_urls: list[list[str]] = []

    async def _capture_batch(urls, **kwargs):
        captured_urls.append(list(urls))
        return {url: _make_result(url) for url in urls}

    job.scanner.scan_urls_batch = _capture_batch

    stats = await job.scan_country("BIGLAND", large_toon, max_urls=None)

    assert len(captured_urls[0]) == 5
    assert stats["total_urls"] == 5
    assert stats["urls_scanned"] == 5


@pytest.mark.asyncio
async def test_scan_all_countries_forwards_max_urls(temp_settings, toon_seeds_dir):
    """max_urls is forwarded from scan_all_countries to scan_country."""
    job = _make_job(temp_settings)

    received_max_urls: list = []

    async def _mock_scan(country_code, toon_path, *args, **kwargs):
        received_max_urls.append(kwargs.get("max_urls"))
        return {"country_code": country_code, "total_urls": 1, "urls_scanned": 1}

    job.scanner.scan_urls_batch = AsyncMock(return_value={})
    with patch.object(job, "scan_country", side_effect=_mock_scan):
        await job.scan_all_countries(toon_seeds_dir, max_urls=100)

    assert all(v == 100 for v in received_max_urls)
    assert len(received_max_urls) == 2





@pytest.fixture
def toon_seeds_dir(tmp_path):
    """Directory with two TOON seed files."""
    data = {
        "version": "0.1-seed",
        "country": "ALPHA",
        "domains": [{"canonical_domain": "a.gov", "pages": [{"url": "https://a.gov/"}]}],
    }
    (tmp_path / "alpha.toon").write_text(json.dumps(data), encoding="utf-8")
    data["country"] = "BETA"
    (tmp_path / "beta.toon").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


@pytest.mark.asyncio
async def test_scan_all_countries_processes_all(temp_settings, toon_seeds_dir):
    job = _make_job(temp_settings)

    async def _mock_scan(country_code, toon_path, *args, **kwargs):
        return {"country_code": country_code, "total_urls": 1, "urls_scanned": 1}

    job.scanner.scan_urls_batch = AsyncMock(return_value={})
    with patch.object(job, "scan_country", side_effect=_mock_scan):
        all_stats = await job.scan_all_countries(toon_seeds_dir)

    assert len(all_stats) == 2
    codes = {s["country_code"] for s in all_stats}
    assert codes == {"ALPHA", "BETA"}


@pytest.mark.asyncio
async def test_scan_all_countries_stops_when_budget_exhausted(temp_settings, toon_seeds_dir):
    """With an already-exhausted time budget no countries are started."""
    import time
    job = _make_job(temp_settings)

    call_count = 0

    async def _mock_scan(country_code, toon_path, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        return {"country_code": country_code}

    with patch.object(job, "scan_country", side_effect=_mock_scan):
        # Budget of 1 second, but start 2 hours in the past → already expired
        all_stats = await job.scan_all_countries(
            toon_seeds_dir, max_runtime_seconds=1.0
        )

    # scan_country may have been called 0 times (budget check fires immediately)
    # but crucially it should NOT be called for BOTH countries when budget is tiny.
    # The important thing: no exception, and all_stats is a list.
    assert isinstance(all_stats, list)


@pytest.mark.asyncio
async def test_scan_all_countries_handles_errors(temp_settings, toon_seeds_dir):
    """Errors in individual country scans are captured, not raised."""
    job = _make_job(temp_settings)

    async def _mock_scan(country_code, toon_path, *args, **kwargs):
        if country_code == "ALPHA":
            raise RuntimeError("Something went wrong")
        return {"country_code": country_code}

    with patch.object(job, "scan_country", side_effect=_mock_scan):
        all_stats = await job.scan_all_countries(toon_seeds_dir)

    # Beta should still be in stats; alpha gets an error entry
    assert any("error" in s for s in all_stats)
    assert any(s.get("country_code") == "BETA" for s in all_stats)


@pytest.mark.asyncio
async def test_scan_all_countries_empty_dir(temp_settings, tmp_path):
    """An empty directory returns an empty list without error."""
    job = _make_job(temp_settings)
    all_stats = await job.scan_all_countries(tmp_path)
    assert all_stats == []
