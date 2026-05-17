"""BDD traceability policy checks for behavior-changing pull requests."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
FEATURES_MAP_PATH = Path("FEATURES.md")
FEATURES_DIR = Path("tests/bdd/features")
STEPS_DIR = Path("tests/bdd/steps")
BEHAVIOR_PATH_PREFIXES = (
    "src/services/",
    "src/cli/",
    "src/jobs/",
    ".github/workflows/",
)
ALLOWED_TYPE_TAGS = {"@smoke", "@regression", "@workflow", "@docs-contract"}
SCENARIO_ID_PATTERN = re.compile(r"\[[A-Z]+-\d{3}\]")


def _run_git_diff(base_range: str) -> list[str]:
    result = subprocess.run(
        ["git", "--no-pager", "diff", "--name-only", base_range],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _get_changed_files() -> list[str]:
    explicit = os.getenv("BDD_CHANGED_FILES", "").strip()
    if explicit:
        return [line.strip() for line in explicit.splitlines() if line.strip()]

    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    base_ref = os.getenv("GITHUB_BASE_REF", "")

    if event_name == "pull_request" and base_ref:
        fetch_result = subprocess.run(
            ["git", "fetch", "origin", f"{base_ref}:refs/remotes/origin/{base_ref}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if fetch_result.returncode == 0:
            return _run_git_diff(f"origin/{base_ref}...HEAD")

    files = _run_git_diff("HEAD~1..HEAD")
    if not files:
        files = _run_git_diff("HEAD")

    status_result = subprocess.run(
        ["git", "--no-pager", "status", "--porcelain"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if status_result.returncode == 0:
        for line in status_result.stdout.splitlines():
            if len(line) < 4:
                continue
            path_segment = line[3:]
            if " -> " in path_segment:
                path_segment = path_segment.split(" -> ", maxsplit=1)[1]
            path_segment = path_segment.strip()
            if path_segment:
                candidate = REPO_ROOT / path_segment
                if candidate.is_dir():
                    for nested in candidate.rglob("*"):
                        if nested.is_file():
                            files.append(nested.relative_to(REPO_ROOT).as_posix())
                else:
                    files.append(path_segment)

    return sorted(set(files))


def _is_feature_file(file_path: str) -> bool:
    return file_path.startswith(f"{FEATURES_DIR.as_posix()}/") and file_path.endswith(".feature")


def _is_step_file(file_path: str) -> bool:
    return file_path.startswith(f"{STEPS_DIR.as_posix()}/") and file_path.endswith(".js")


def _is_behavior_impl_file(file_path: str) -> bool:
    return file_path.startswith(BEHAVIOR_PATH_PREFIXES)


def _validate_feature_catalog(feature_files: Iterable[Path]) -> list[str]:
    errors: list[str] = []
    for feature_file in feature_files:
        text = feature_file.read_text(encoding="utf-8")

        has_type_tag = any(tag in text for tag in ALLOWED_TYPE_TAGS)
        if not has_type_tag:
            errors.append(
                f"{feature_file}: missing at least one type tag from "
                f"{', '.join(sorted(ALLOWED_TYPE_TAGS))}"
            )

        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("Scenario:") and not SCENARIO_ID_PATTERN.search(stripped):
                errors.append(
                    f"{feature_file}: scenario is missing an ID like [VAL-001] -> {stripped}"
                )

    return errors


def _validate_behavior_traceability(
    behavior_impl_changed: bool,
    features_map_changed: bool,
    feature_files_changed: bool,
) -> list[str]:
    if not behavior_impl_changed:
        return []

    errors: list[str] = []
    if not features_map_changed:
        errors.append("Behavior code/workflow changed, but FEATURES.md was not updated.")
    if not feature_files_changed:
        errors.append(
            "Behavior code/workflow changed, but no Gherkin feature file was updated under tests/bdd/features/."
        )
    return errors


def _validate_feature_step_consistency(
    feature_files_changed: bool,
    step_files_changed: bool,
) -> list[str]:
    if feature_files_changed and not step_files_changed:
        return [
            "Feature files changed, but no step definitions changed under tests/bdd/steps/."
        ]
    return []


def main() -> int:
    changed_files = _get_changed_files()

    features_map_changed = FEATURES_MAP_PATH.as_posix() in changed_files
    feature_files_changed = any(_is_feature_file(file_path) for file_path in changed_files)
    step_files_changed = any(_is_step_file(file_path) for file_path in changed_files)
    behavior_impl_changed = any(_is_behavior_impl_file(file_path) for file_path in changed_files)

    errors: list[str] = []

    errors.extend(
        _validate_behavior_traceability(
            behavior_impl_changed=behavior_impl_changed,
            features_map_changed=features_map_changed,
            feature_files_changed=feature_files_changed,
        )
    )
    errors.extend(
        _validate_feature_step_consistency(
            feature_files_changed=feature_files_changed,
            step_files_changed=step_files_changed,
        )
    )

    feature_files = sorted(FEATURES_DIR.glob("*.feature"))
    errors.extend(_validate_feature_catalog(feature_files))

    if errors:
        print("BDD traceability check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("BDD traceability check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
