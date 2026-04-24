"""Unit tests for the Google Lighthouse scanner service."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.services.lighthouse_scanner import (
    LighthouseScanResult,
    LighthouseScanner,
    _parse_lighthouse_output,
)


# ---------------------------------------------------------------------------
# _parse_lighthouse_output
# ---------------------------------------------------------------------------

def _make_lighthouse_json(
    performance: float | None = 0.95,
    accessibility: float | None = 0.87,
    best_practices: float | None = 1.0,
    seo: float | None = 0.92,
    pwa: float | None = 0.0,
) -> str:
    """Build a minimal Lighthouse JSON output string."""
    categories = {}
    if performance is not None:
        categories["performance"] = {"score": performance}
    if accessibility is not None:
        categories["accessibility"] = {"score": accessibility}
    if best_practices is not None:
        categories["best-practices"] = {"score": best_practices}
    if seo is not None:
        categories["seo"] = {"score": seo}
    if pwa is not None:
        categories["pwa"] = {"score": pwa}
    return json.dumps({"categories": categories})


def test_parse_lighthouse_output_all_scores():
    """All five category scores should be extracted correctly."""
    raw = _make_lighthouse_json(
        performance=0.95, accessibility=0.87, best_practices=1.0, seo=0.92, pwa=0.0
    )
    scores = _parse_lighthouse_output(raw)
    assert scores["performance"] == pytest.approx(0.95)
    assert scores["accessibility"] == pytest.approx(0.87)
    assert scores["best-practices"] == pytest.approx(1.0)
    assert scores["seo"] == pytest.approx(0.92)
    assert scores["pwa"] == pytest.approx(0.0)


def test_parse_lighthouse_output_missing_category():
    """A missing category key should return None for that score."""
    raw = json.dumps({"categories": {"performance": {"score": 0.80}}})
    scores = _parse_lighthouse_output(raw)
    assert scores["performance"] == pytest.approx(0.80)
    assert scores["accessibility"] is None
    assert scores["best-practices"] is None
    assert scores["seo"] is None
    assert scores["pwa"] is None


def test_parse_lighthouse_output_invalid_json():
    """Invalid JSON should raise ValueError."""
    with pytest.raises(ValueError, match="Invalid JSON"):
        _parse_lighthouse_output("not json at all")


def test_parse_lighthouse_output_no_categories():
    """JSON without 'categories' key should raise ValueError."""
    with pytest.raises(ValueError, match="no 'categories' key"):
        _parse_lighthouse_output(json.dumps({"audits": {}}))


# ---------------------------------------------------------------------------
# LighthouseScanner.scan_url
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scan_url_success():
    """Successful scan should return all category scores."""
    scanner = LighthouseScanner(timeout_seconds=60)
    raw = _make_lighthouse_json(
        performance=0.9, accessibility=0.85, best_practices=0.95, seo=0.88, pwa=0.3
    )

    with patch.object(scanner, "_run_lighthouse", return_value=raw):
        result = await scanner.scan_url("https://gov.example/")

    assert result.url == "https://gov.example/"
    assert result.performance_score == pytest.approx(0.9)
    assert result.accessibility_score == pytest.approx(0.85)
    assert result.best_practices_score == pytest.approx(0.95)
    assert result.seo_score == pytest.approx(0.88)
    assert result.pwa_score == pytest.approx(0.3)
    assert result.error_message is None
    assert result.scanned_at is not None


@pytest.mark.asyncio
async def test_scan_url_lighthouse_not_found():
    """FileNotFoundError should yield an informative error message."""
    scanner = LighthouseScanner()

    with patch.object(scanner, "_run_lighthouse", side_effect=FileNotFoundError()):
        result = await scanner.scan_url("https://gov.example/")

    assert result.performance_score is None
    assert result.error_message is not None
    assert "npm install -g lighthouse" in result.error_message


@pytest.mark.asyncio
async def test_scan_url_timeout():
    """TimeoutExpired should yield a timeout error message."""
    scanner = LighthouseScanner(timeout_seconds=30)

    with patch.object(
        scanner,
        "_run_lighthouse",
        side_effect=subprocess.TimeoutExpired(cmd=["lighthouse"], timeout=30),
    ):
        result = await scanner.scan_url("https://slow.gov/")

    assert result.performance_score is None
    assert result.error_message is not None
    assert "timed out" in result.error_message


@pytest.mark.asyncio
async def test_scan_url_non_zero_exit():
    """CalledProcessError should yield an error message with the exit code."""
    scanner = LighthouseScanner()

    with patch.object(
        scanner,
        "_run_lighthouse",
        side_effect=subprocess.CalledProcessError(
            returncode=1,
            cmd=["lighthouse"],
            output="",
            stderr="Chrome could not be launched",
        ),
    ):
        result = await scanner.scan_url("https://error.gov/")

    assert result.performance_score is None
    assert result.error_message is not None
    assert "1" in result.error_message


@pytest.mark.asyncio
async def test_scan_url_invalid_json_output():
    """Invalid JSON from Lighthouse should yield a parse error message."""
    scanner = LighthouseScanner()

    with patch.object(scanner, "_run_lighthouse", return_value="garbage output"):
        result = await scanner.scan_url("https://gov.example/")

    assert result.performance_score is None
    assert result.error_message is not None
    assert "Invalid JSON" in result.error_message


# ---------------------------------------------------------------------------
# LighthouseScanner.scan_urls_batch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scan_urls_batch_returns_all_results():
    """Batch scan should return a result for every provided URL."""
    scanner = LighthouseScanner()
    urls = ["https://gov1.example/", "https://gov2.example/"]
    raw = _make_lighthouse_json()

    with patch.object(scanner, "_run_lighthouse", return_value=raw):
        results = await scanner.scan_urls_batch(urls, rate_limit_per_second=0)

    assert len(results) == 2
    for url in urls:
        assert url in results
        assert results[url].error_message is None


@pytest.mark.asyncio
async def test_scan_urls_batch_on_result_callback():
    """on_result callback should be called once per URL."""
    scanner = LighthouseScanner()
    urls = ["https://gov1.example/", "https://gov2.example/"]
    raw = _make_lighthouse_json()
    collected: list[LighthouseScanResult] = []

    with patch.object(scanner, "_run_lighthouse", return_value=raw):
        await scanner.scan_urls_batch(
            urls,
            rate_limit_per_second=0,
            on_result=collected.append,
        )

    assert len(collected) == 2
    assert {r.url for r in collected} == set(urls)


@pytest.mark.asyncio
async def test_scan_urls_batch_stops_early_when_budget_exhausted():
    """Scanning should stop when the time budget is nearly used up."""
    import time as time_mod

    scanner = LighthouseScanner()
    urls = ["https://gov1.example/", "https://gov2.example/", "https://gov3.example/"]
    raw = _make_lighthouse_json()

    # Simulate budget almost exhausted (30 s left of 10000 s, safety buffer = 60 s)
    elapsed_start = time_mod.monotonic() - 9970

    with patch.object(scanner, "_run_lighthouse", return_value=raw):
        results = await scanner.scan_urls_batch(
            urls,
            rate_limit_per_second=0,
            max_runtime_seconds=10000,
            start_time=elapsed_start,
        )

    assert len(results) == 0


@pytest.mark.asyncio
async def test_scan_urls_batch_no_max_runtime_scans_all():
    """All URLs should be scanned when max_runtime_seconds is None."""
    scanner = LighthouseScanner()
    urls = ["https://gov1.example/", "https://gov2.example/", "https://gov3.example/"]
    raw = _make_lighthouse_json()

    with patch.object(scanner, "_run_lighthouse", return_value=raw):
        results = await scanner.scan_urls_batch(
            urls,
            rate_limit_per_second=0,
            max_runtime_seconds=None,
        )

    assert len(results) == 3


# ---------------------------------------------------------------------------
# LighthouseScanner._build_command
# ---------------------------------------------------------------------------

def test_build_command_includes_url():
    """The built command must include the target URL."""
    scanner = LighthouseScanner()
    cmd = scanner._build_command("https://example.gov/")
    assert any(arg == "https://example.gov/" for arg in cmd)


def test_build_command_json_output():
    """The built command must request JSON output to stdout."""
    scanner = LighthouseScanner()
    cmd = scanner._build_command("https://example.gov/")
    assert "--output=json" in cmd
    assert "--output-path=stdout" in cmd


def test_build_command_extra_args():
    """Extra args passed to the constructor should appear in the command."""
    scanner = LighthouseScanner(extra_args=["--only-categories=accessibility"])
    cmd = scanner._build_command("https://example.gov/")
    assert "--only-categories=accessibility" in cmd


def test_build_command_custom_chrome_flags():
    """Custom chrome-flags should be forwarded to the command."""
    scanner = LighthouseScanner(chrome_flags="--headless --disable-gpu")
    cmd = scanner._build_command("https://example.gov/")
    assert any("--headless --disable-gpu" in arg for arg in cmd)
