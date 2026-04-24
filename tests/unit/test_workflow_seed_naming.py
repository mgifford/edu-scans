"""Guardrails for workflow seed-path and seed-oriented wording."""

from pathlib import Path


WORKFLOW_DIR = Path(".github/workflows")


def test_workflows_do_not_use_legacy_country_seed_dir() -> None:
    """Workflows should not hardcode the removed countries seed directory."""
    offenders: list[str] = []

    for workflow_path in sorted(WORKFLOW_DIR.glob("*.yml")):
        content = workflow_path.read_text(encoding="utf-8")
        if "data/toon-seeds/countries" in content:
            offenders.append(str(workflow_path))

    assert not offenders, (
        "Legacy seed path 'data/toon-seeds/countries' is still referenced in: "
        + ", ".join(offenders)
    )


def test_scan_workflows_do_not_use_country_example_codes() -> None:
    """Dispatch prompts should avoid template-specific country examples."""
    scan_workflows = [
        "scan-accessibility.yml",
        "scan-social-media.yml",
        "scan-technology.yml",
        "scan-third-party-js.yml",
        "scan-lighthouse.yml",
        "scan-overlays.yml",
        "validate-urls.yml",
    ]

    offenders: list[str] = []

    for workflow_name in scan_workflows:
        workflow_path = WORKFLOW_DIR / workflow_name
        content = workflow_path.read_text(encoding="utf-8")
        if "ICELAND, FRANCE" in content:
            offenders.append(str(workflow_path))

    assert not offenders, (
        "Country template examples are still present in: " + ", ".join(offenders)
    )
