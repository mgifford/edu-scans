"""Tests for GitHub Pages deployment workflow safeguards."""

from pathlib import Path


def test_deploy_pages_workflow_validates_required_drilldown_json_files() -> None:
    """Deploy workflow should fail fast if required drilldown JSON files are missing."""
    workflow_path = Path(".github/workflows/deploy-pages.yml")
    content = workflow_path.read_text(encoding="utf-8")

    assert "Validate required drilldown JSON files" in content
    assert "REQUIRED_DRILLDOWN_JSON_FILES" in content
    assert "social-media-data.json" in content
    assert "technology-data.json" in content
    assert "accessibility-data.json" in content
    assert "third-party-tools-data.json" in content
    assert "scan-progress-data.json" in content
    assert "lighthouse-data.json" in content
    assert "docs/$file" in content
    assert "GitHub Pages build stopped" in content
    assert "if [ \"$missing\" -ne 0 ]; then" in content
    assert "exit 1" in content


def test_deploy_pages_workflow_hydrates_scan_progress_artifacts() -> None:
    """Deploy workflow should hydrate JSON files from scan-progress artifacts."""
    workflow_path = Path(".github/workflows/deploy-pages.yml")
    content = workflow_path.read_text(encoding="utf-8")

    assert "Download scan-progress artifact from triggering workflow run" in content
    assert "Find latest scan-progress artifact run ID" in content
    assert "Download latest scan-progress artifact" in content
    assert "pattern: scan-progress-report-*" in content
    assert "Hydrate drilldown JSON files for site build" in content
    assert "REQUIRED_DRILLDOWN_JSON_FILES" in content
    assert "/tmp/scan-progress-artifact/docs/$file" in content
    assert "/tmp/scan-progress-artifact/$file" in content
    assert "set -eo pipefail" in content
