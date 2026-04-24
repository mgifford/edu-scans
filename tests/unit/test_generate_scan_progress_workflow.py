"""Tests for Generate Scan Progress workflow artifact contents."""

from pathlib import Path

import yaml


def test_generate_scan_progress_workflow_uploads_scan_progress_data_json() -> None:
    """Workflow artifact should include scan-progress drilldown JSON."""
    workflow_path = Path(".github/workflows/generate-scan-progress.yml")
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    jobs = workflow.get("jobs", {})
    steps = jobs.get("generate-progress-report", {}).get("steps", [])
    upload_step = next(
        (step for step in steps if step.get("name") == "Upload progress report artifact"),
        None,
    )

    assert upload_step is not None, "Upload progress report artifact step is missing."

    upload_path = upload_step.get("with", {}).get("path", "")
    assert "docs/scan-progress-data.json" in upload_path
