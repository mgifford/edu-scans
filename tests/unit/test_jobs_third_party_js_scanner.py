"""Unit tests for the third-party JS scanner job."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.jobs.third_party_js_scanner import ThirdPartyJsScannerJob
from src.lib.settings import Settings
from src.services.third_party_js_scanner import ThirdPartyJsScanResult, ThirdPartyScript


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


def _make_job(settings: Settings) -> ThirdPartyJsScannerJob:
    job = ThirdPartyJsScannerJob(settings)
    job.scanner = MagicMock()
    return job


def _make_result(
    url: str,
    scripts: list[ThirdPartyScript] | None = None,
    error: str | None = None,
    reachable: bool = True,
) -> ThirdPartyJsScanResult:
    scripts = scripts or []
    return ThirdPartyJsScanResult(
        url=url,
        is_reachable=reachable,
        scripts=scripts,
        error_message=error,
        scanned_at="2024-01-01T00:00:00+00:00",
    )


def _gtm_script() -> ThirdPartyScript:
    return ThirdPartyScript(
        src="https://www.googletagmanager.com/gtm.js",
        host="www.googletagmanager.com",
        service_name="Google Tag Manager",
        version=None,
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
# _update_toon_with_third_party_js
# ---------------------------------------------------------------------------


def test_update_toon_adds_scripts(temp_settings):
    job = _make_job(temp_settings)
    toon_data = {
        "domains": [{"pages": [{"url": "https://gov.example/"}]}]
    }
    scan_results = {
        "https://gov.example/": _make_result("https://gov.example/", scripts=[_gtm_script()]),
    }
    updated = job._update_toon_with_third_party_js(toon_data, scan_results)
    page = updated["domains"][0]["pages"][0]
    assert "third_party_js" in page
    assert len(page["third_party_js"]) == 1
    assert page["third_party_js"][0]["service_name"] == "Google Tag Manager"


def test_update_toon_no_scripts_field_empty_list(temp_settings):
    job = _make_job(temp_settings)
    toon_data = {"domains": [{"pages": [{"url": "https://gov.example/"}]}]}
    scan_results = {
        "https://gov.example/": _make_result("https://gov.example/", scripts=[]),
    }
    updated = job._update_toon_with_third_party_js(toon_data, scan_results)
    page = updated["domains"][0]["pages"][0]
    assert page["third_party_js"] == []
    assert "third_party_js_error" not in page


def test_update_toon_adds_error_field_when_unreachable(temp_settings):
    job = _make_job(temp_settings)
    toon_data = {"domains": [{"pages": [{"url": "https://fail.gov/"}]}]}
    scan_results = {
        "https://fail.gov/": _make_result(
            "https://fail.gov/", error="Timeout", reachable=False
        ),
    }
    updated = job._update_toon_with_third_party_js(toon_data, scan_results)
    page = updated["domains"][0]["pages"][0]
    assert page["third_party_js_error"] == "Timeout"
    assert "third_party_js" not in page


def test_update_toon_skips_missing_urls(temp_settings):
    job = _make_job(temp_settings)
    toon_data = {"domains": [{"pages": [{"url": "https://gov.example/"}]}]}
    updated = job._update_toon_with_third_party_js(toon_data, scan_results={})
    page = updated["domains"][0]["pages"][0]
    assert "third_party_js" not in page
    assert "third_party_js_error" not in page


# ---------------------------------------------------------------------------
# _save_results
# ---------------------------------------------------------------------------


def test_save_results_persists_to_db(temp_settings):
    job = _make_job(temp_settings)
    results = [_make_result("https://gov.example/", scripts=[_gtm_script()])]
    job._save_results(results, "TESTLAND", "scan-001")

    conn = sqlite3.connect(job.db_path)
    rows = conn.execute(
        "SELECT url, country_code, scan_id, is_reachable, scripts FROM url_third_party_js_results"
    ).fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0][0] == "https://gov.example/"
    assert rows[0][1] == "TESTLAND"
    assert rows[0][2] == "scan-001"
    assert rows[0][3] == 1  # is_reachable stored as 1

    scripts_data = json.loads(rows[0][4])
    assert len(scripts_data) == 1
    assert scripts_data[0]["service_name"] == "Google Tag Manager"


def test_save_results_error_entry(temp_settings):
    job = _make_job(temp_settings)
    result = _make_result("https://fail.gov/", error="Connection failed", reachable=False)
    job._save_results([result], "TESTLAND", "scan-002")

    conn = sqlite3.connect(job.db_path)
    row = conn.execute(
        "SELECT is_reachable, error_message FROM url_third_party_js_results WHERE url = ?",
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
            "https://gov.example/", scripts=[_gtm_script()]
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
    assert stats["total_scripts"] == 1
    assert stats["identified_services"] == 1
    assert stats["urls_with_scripts"] == 1
    assert stats["service_counts"] == {"Google Tag Manager": 1}


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

    # Only one URL scanned (budget exhausted)
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
        "https://gov.example/": _make_result("https://gov.example/", scripts=[_gtm_script()]),
        "https://gov.example/about": _make_result("https://gov.example/about"),
    }
    job.scanner.scan_urls_batch = AsyncMock(return_value=mock_results)

    stats = await job.scan_country("TESTLAND", sample_toon)

    output_path = Path(stats["output_path"])
    assert output_path.exists()
    data = json.loads(output_path.read_text())
    page = data["domains"][0]["pages"][0]
    assert "third_party_js" in page


@pytest.mark.asyncio
async def test_scan_country_aggregates_service_counts(temp_settings, sample_toon):
    """service_counts sums the same service seen across multiple URLs."""
    job = _make_job(temp_settings)

    mock_results = {
        "https://gov.example/": _make_result("https://gov.example/", scripts=[_gtm_script()]),
        "https://gov.example/about": _make_result(
            "https://gov.example/about", scripts=[_gtm_script()]
        ),
    }
    job.scanner.scan_urls_batch = AsyncMock(return_value=mock_results)

    stats = await job.scan_country("TESTLAND", sample_toon)
    assert stats["service_counts"]["Google Tag Manager"] == 2


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
