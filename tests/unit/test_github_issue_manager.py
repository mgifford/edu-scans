"""Unit tests for the GitHub issue manager service."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.services.github_issue_manager import (
    GH_CLI_CHECK_TIMEOUT,
    GH_CLI_COMMAND_TIMEOUT,
    GitHubIssueManager,
    _compute_eta,
)


# ---------------------------------------------------------------------------
# _check_gh_cli
# ---------------------------------------------------------------------------


def test_check_gh_cli_available():
    """Returns True when 'gh --version' exits with code 0."""
    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        manager = GitHubIssueManager()

    mock_run.assert_called_once_with(
        ["gh", "--version"],
        capture_output=True,
        text=True,
        timeout=GH_CLI_CHECK_TIMEOUT,
    )
    assert manager._has_gh_cli is True


def test_check_gh_cli_not_available_nonzero():
    """Returns False when 'gh --version' exits with non-zero code."""
    mock_result = MagicMock()
    mock_result.returncode = 1

    with patch("subprocess.run", return_value=mock_result):
        manager = GitHubIssueManager()

    assert manager._has_gh_cli is False


def test_check_gh_cli_not_found():
    """Returns False when the 'gh' binary is not installed (FileNotFoundError)."""
    with patch("subprocess.run", side_effect=FileNotFoundError):
        manager = GitHubIssueManager()

    assert manager._has_gh_cli is False


def test_check_gh_cli_timeout():
    """Returns False when the version check times out."""
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 5)):
        manager = GitHubIssueManager()

    assert manager._has_gh_cli is False


# ---------------------------------------------------------------------------
# _run_gh_command
# ---------------------------------------------------------------------------


def _make_manager_with_cli(available: bool = True) -> GitHubIssueManager:
    """Return a GitHubIssueManager bypassing the real _check_gh_cli."""
    check_result = MagicMock()
    check_result.returncode = 0 if available else 1
    with patch("subprocess.run", return_value=check_result):
        return GitHubIssueManager()


def test_run_gh_command_no_cli():
    """Returns (False, 'GitHub CLI not available') when CLI is absent."""
    manager = _make_manager_with_cli(available=False)
    success, output = manager._run_gh_command(["issue", "list"])
    assert success is False
    assert "not available" in output


def test_run_gh_command_success():
    """Returns (True, stdout) on a successful command."""
    manager = _make_manager_with_cli(available=True)

    cmd_result = MagicMock()
    cmd_result.returncode = 0
    cmd_result.stdout = "https://github.com/owner/repo/issues/42\n"

    with patch("subprocess.run", return_value=cmd_result):
        success, output = manager._run_gh_command(["issue", "create"])

    assert success is True
    assert output == "https://github.com/owner/repo/issues/42"


def test_run_gh_command_failure():
    """Returns (False, stdout) when command returns non-zero."""
    manager = _make_manager_with_cli(available=True)

    cmd_result = MagicMock()
    cmd_result.returncode = 1
    cmd_result.stdout = "error message"

    with patch("subprocess.run", return_value=cmd_result):
        success, output = manager._run_gh_command(["issue", "create"])

    assert success is False


def test_run_gh_command_timeout():
    """Returns (False, 'Command timed out') on TimeoutExpired."""
    manager = _make_manager_with_cli(available=True)

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["gh", "issue", "list"], GH_CLI_COMMAND_TIMEOUT)):
        success, output = manager._run_gh_command(["issue", "list"])

    assert success is False
    assert "timed out" in output


def test_run_gh_command_generic_exception():
    """Returns (False, str(e)) on unexpected exceptions."""
    manager = _make_manager_with_cli(available=True)

    with patch("subprocess.run", side_effect=RuntimeError("some error")):
        success, output = manager._run_gh_command(["issue", "list"])

    assert success is False
    assert "some error" in output


# ---------------------------------------------------------------------------
# create_validation_issue
# ---------------------------------------------------------------------------


def test_create_validation_issue_success():
    """Returns the parsed issue number on success."""
    manager = _make_manager_with_cli(available=True)

    cmd_result = MagicMock()
    cmd_result.returncode = 0
    cmd_result.stdout = "https://github.com/mgifford/eu-plus-government-scans/issues/123\n"

    with patch("subprocess.run", return_value=cmd_result):
        issue_number = manager.create_validation_issue("cycle-2024-01")

    assert issue_number == 123


def test_create_validation_issue_bad_url_format():
    """Returns None when stdout cannot be parsed as an issue URL."""
    manager = _make_manager_with_cli(available=True)

    cmd_result = MagicMock()
    cmd_result.returncode = 0
    cmd_result.stdout = "not-a-url\n"

    with patch("subprocess.run", return_value=cmd_result):
        issue_number = manager.create_validation_issue("cycle-2024-01")

    assert issue_number is None


def test_create_validation_issue_command_fails():
    """Returns None when the CLI command fails."""
    manager = _make_manager_with_cli(available=True)

    cmd_result = MagicMock()
    cmd_result.returncode = 1
    cmd_result.stdout = ""

    with patch("subprocess.run", return_value=cmd_result):
        issue_number = manager.create_validation_issue("cycle-2024-01")

    assert issue_number is None


def test_create_validation_issue_no_cli():
    """Returns None when the CLI is not available."""
    manager = _make_manager_with_cli(available=False)
    issue_number = manager.create_validation_issue("cycle-2024-01")
    assert issue_number is None


# ---------------------------------------------------------------------------
# update_issue_progress
# ---------------------------------------------------------------------------


def test_update_issue_progress_calls_gh():
    """update_issue_progress invokes 'gh issue edit' with the correct issue number."""
    manager = _make_manager_with_cli(available=True)

    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        return result

    with patch("subprocess.run", side_effect=_fake_run):
        manager.update_issue_progress(
            issue_number=42,
            cycle_id="cycle-1",
            total=10,
            completed=5,
            processing=1,
            pending=4,
            failed=0,
        )

    assert any("42" in str(c) for c in calls)
    assert any("edit" in c for c in calls[0])


def test_update_issue_progress_complete_status():
    """When all countries are done the status emoji becomes 🟢."""
    manager = _make_manager_with_cli(available=True)
    captured_body = []

    def _fake_run(cmd, **kwargs):
        # Capture the body argument
        if "--body" in cmd:
            idx = cmd.index("--body")
            captured_body.append(cmd[idx + 1])
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        return result

    with patch("subprocess.run", side_effect=_fake_run):
        manager.update_issue_progress(
            issue_number=42,
            cycle_id="cycle-1",
            total=10,
            completed=10,
            processing=0,
            pending=0,
            failed=0,
        )

    assert len(captured_body) == 1
    assert "🟢" in captured_body[0]


def test_update_issue_progress_zero_total():
    """With total=0 the progress percentage is 0% (no ZeroDivisionError)."""
    manager = _make_manager_with_cli(available=True)

    result = MagicMock()
    result.returncode = 0
    result.stdout = ""

    with patch("subprocess.run", return_value=result):
        # Should not raise
        manager.update_issue_progress(
            issue_number=1,
            cycle_id="c",
            total=0,
            completed=0,
            processing=0,
            pending=0,
            failed=0,
        )


# ---------------------------------------------------------------------------
# close_validation_issue
# ---------------------------------------------------------------------------


def test_close_validation_issue_calls_edit_then_close():
    """close_validation_issue first edits the body then closes the issue."""
    manager = _make_manager_with_cli(available=True)

    verbs_seen = []

    def _fake_run(cmd, **kwargs):
        verbs_seen.append(cmd[1])  # 'issue'
        verbs_seen.append(cmd[2])  # 'edit' or 'close'
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        return result

    with patch("subprocess.run", side_effect=_fake_run):
        manager.close_validation_issue(
            issue_number=99,
            cycle_id="cycle-x",
            total=5,
            completed=5,
            failed=0,
        )

    # Both 'edit' and 'close' should have been called
    assert "edit" in verbs_seen
    assert "close" in verbs_seen


# ---------------------------------------------------------------------------
# add_comment / reopen_issue
# ---------------------------------------------------------------------------


def test_add_comment_calls_gh():
    """add_comment calls 'gh issue comment'."""
    manager = _make_manager_with_cli(available=True)
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        return r

    with patch("subprocess.run", side_effect=_fake_run):
        manager.add_comment(7, "Hello from test!")

    assert any("comment" in c for c in calls[0])
    assert any("7" in str(c) for c in calls[0])


def test_reopen_issue_calls_gh():
    """reopen_issue calls 'gh issue reopen'."""
    manager = _make_manager_with_cli(available=True)
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        return r

    with patch("subprocess.run", side_effect=_fake_run):
        manager.reopen_issue(7)

    assert any("reopen" in c for c in calls[0])
    assert any("7" in str(c) for c in calls[0])


# ---------------------------------------------------------------------------
# find_open_validation_issue
# ---------------------------------------------------------------------------


def test_find_open_validation_issue_returns_number():
    """Returns the issue number when one is found."""
    manager = _make_manager_with_cli(available=True)

    cmd_result = MagicMock()
    cmd_result.returncode = 0
    cmd_result.stdout = "55\n"

    with patch("subprocess.run", return_value=cmd_result):
        number = manager.find_open_validation_issue()

    assert number == 55


def test_find_open_validation_issue_empty_output():
    """Returns None when command succeeds but output is empty."""
    manager = _make_manager_with_cli(available=True)

    cmd_result = MagicMock()
    cmd_result.returncode = 0
    cmd_result.stdout = ""

    with patch("subprocess.run", return_value=cmd_result):
        number = manager.find_open_validation_issue()

    assert number is None


def test_find_open_validation_issue_non_numeric_output():
    """Returns None when output cannot be parsed as an integer."""
    manager = _make_manager_with_cli(available=True)

    cmd_result = MagicMock()
    cmd_result.returncode = 0
    cmd_result.stdout = "null"

    with patch("subprocess.run", return_value=cmd_result):
        number = manager.find_open_validation_issue()

    assert number is None


def test_find_open_validation_issue_command_fails():
    """Returns None when the CLI command fails."""
    manager = _make_manager_with_cli(available=True)

    cmd_result = MagicMock()
    cmd_result.returncode = 1
    cmd_result.stdout = ""

    with patch("subprocess.run", return_value=cmd_result):
        number = manager.find_open_validation_issue()

    assert number is None


def test_find_open_validation_issue_no_cli():
    """Returns None when CLI is not available."""
    manager = _make_manager_with_cli(available=False)
    number = manager.find_open_validation_issue()
    assert number is None


# ---------------------------------------------------------------------------
# Custom repo argument
# ---------------------------------------------------------------------------


def test_custom_repo_is_stored():
    """The repo argument is stored on the instance."""
    check_result = MagicMock()
    check_result.returncode = 0
    with patch("subprocess.run", return_value=check_result):
        manager = GitHubIssueManager(repo="other/repo")
    assert manager.repo == "other/repo"


# ---------------------------------------------------------------------------
# _compute_eta
# ---------------------------------------------------------------------------


def test_compute_eta_returns_none_when_no_pending():
    """Returns None when there is nothing left to process."""
    assert _compute_eta(pending=0, batch_size=4, workflow_interval_hours=12.0) is None


def test_compute_eta_single_batch_remaining():
    """When only one batch remains the ETA is approximately now (no future runs needed)."""
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    result = _compute_eta(pending=3, batch_size=4, workflow_interval_hours=12.0)
    assert result is not None
    eta = datetime.strptime(result, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
    # ETA should be within a few seconds of now (0 future runs × 12 h = +0 h)
    diff = abs((eta - now).total_seconds())
    assert diff < 60, f"Expected ETA ≈ now, got {result}"


def test_compute_eta_multiple_batches():
    """With multiple batches pending the ETA is (batches_remaining - 1) × interval hours from now."""
    import math
    from datetime import timedelta

    pending = 10
    batch_size = 4
    interval = 12.0
    now = datetime.now(timezone.utc)

    result = _compute_eta(pending=pending, batch_size=batch_size, workflow_interval_hours=interval)
    assert result is not None
    eta = datetime.strptime(result, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)

    batches_remaining = math.ceil(pending / batch_size)  # 3
    expected_hours = (batches_remaining - 1) * interval  # 2 × 12 = 24
    expected_eta = now.replace(second=0, microsecond=0) + timedelta(hours=expected_hours)
    diff_minutes = abs((eta - expected_eta).total_seconds() / 60)
    assert diff_minutes < 2, f"ETA off by {diff_minutes:.1f} minutes"


def test_compute_eta_returns_utc_formatted_string():
    """The returned string matches the expected format."""
    result = _compute_eta(pending=5, batch_size=4, workflow_interval_hours=12.0)
    assert result is not None
    # Verify it parses back without error
    datetime.strptime(result, "%Y-%m-%d %H:%M UTC")
    assert result.endswith("UTC")


# ---------------------------------------------------------------------------
# update_issue_progress – ETA behaviour
# ---------------------------------------------------------------------------


def test_update_issue_progress_includes_eta_when_pending():
    """ETA line appears in the issue body when there are pending countries."""
    manager = _make_manager_with_cli(available=True)
    captured_body = []

    def _fake_run(cmd, **kwargs):
        if "--body" in cmd:
            captured_body.append(cmd[cmd.index("--body") + 1])
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        return result

    with patch("subprocess.run", side_effect=_fake_run):
        manager.update_issue_progress(
            issue_number=1,
            cycle_id="cycle-1",
            total=10,
            completed=2,
            processing=1,
            pending=7,
            failed=0,
            batch_size=4,
            workflow_interval_hours=12.0,
        )

    assert len(captured_body) == 1
    assert "Est. completion" in captured_body[0]


def test_update_issue_progress_no_eta_when_complete():
    """No ETA line appears when the cycle is complete."""
    manager = _make_manager_with_cli(available=True)
    captured_body = []

    def _fake_run(cmd, **kwargs):
        if "--body" in cmd:
            captured_body.append(cmd[cmd.index("--body") + 1])
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        return result

    with patch("subprocess.run", side_effect=_fake_run):
        manager.update_issue_progress(
            issue_number=1,
            cycle_id="cycle-1",
            total=10,
            completed=10,
            processing=0,
            pending=0,
            failed=0,
        )

    assert len(captured_body) == 1
    assert "Est. completion" not in captured_body[0]


# ---------------------------------------------------------------------------
# create_review_issue
# ---------------------------------------------------------------------------


def test_create_review_issue_success():
    """Returns the parsed issue number on success."""
    manager = _make_manager_with_cli(available=True)

    cmd_result = MagicMock()
    cmd_result.returncode = 0
    cmd_result.stdout = "https://github.com/mgifford/eu-plus-government-scans/issues/200\n"

    with patch("subprocess.run", return_value=cmd_result):
        issue_number = manager.create_review_issue(
            cycle_id="20260101-120000",
            total=10,
            completed=9,
            failed=1,
        )

    assert issue_number == 200


def test_create_review_issue_includes_tracking_ref():
    """Body contains a reference to the tracking issue when provided."""
    manager = _make_manager_with_cli(available=True)
    captured_body = []

    def _fake_run(cmd, **kwargs):
        if "--body" in cmd:
            captured_body.append(cmd[cmd.index("--body") + 1])
        result = MagicMock()
        result.returncode = 0
        result.stdout = "https://github.com/owner/repo/issues/77\n"
        return result

    with patch("subprocess.run", side_effect=_fake_run):
        manager.create_review_issue(
            cycle_id="20260101-120000",
            total=5,
            completed=5,
            failed=0,
            tracking_issue_number=55,
        )

    assert len(captured_body) == 1
    assert "#55" in captured_body[0]


def test_create_review_issue_no_tracking_ref_when_omitted():
    """Body does NOT contain a tracking-issue reference when none is passed."""
    manager = _make_manager_with_cli(available=True)
    captured_body = []

    def _fake_run(cmd, **kwargs):
        if "--body" in cmd:
            captured_body.append(cmd[cmd.index("--body") + 1])
        result = MagicMock()
        result.returncode = 0
        result.stdout = "https://github.com/owner/repo/issues/78\n"
        return result

    with patch("subprocess.run", side_effect=_fake_run):
        manager.create_review_issue(
            cycle_id="20260101-120000",
            total=5,
            completed=5,
            failed=0,
        )

    assert len(captured_body) == 1
    assert "issue #" not in captured_body[0].lower()


def test_create_review_issue_command_fails():
    """Returns None when the CLI command fails."""
    manager = _make_manager_with_cli(available=True)

    cmd_result = MagicMock()
    cmd_result.returncode = 1
    cmd_result.stdout = ""

    with patch("subprocess.run", return_value=cmd_result):
        issue_number = manager.create_review_issue(
            cycle_id="20260101-120000",
            total=5,
            completed=4,
            failed=1,
        )

    assert issue_number is None


def test_create_review_issue_no_cli():
    """Returns None when the CLI is not available."""
    manager = _make_manager_with_cli(available=False)
    issue_number = manager.create_review_issue(
        cycle_id="20260101-120000",
        total=5,
        completed=5,
        failed=0,
    )
    assert issue_number is None
