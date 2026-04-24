"""GitHub Issue manager for tracking validation cycles."""

from __future__ import annotations

import math
import os
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Optional

# Timeout constants for GitHub CLI operations
GH_CLI_CHECK_TIMEOUT = 5  # seconds for version check
GH_CLI_COMMAND_TIMEOUT = 30  # seconds for actual commands


def _compute_eta(
    pending: int,
    batch_size: int,
    workflow_interval_hours: float,
) -> Optional[str]:
    """Estimate when the remaining countries will be processed.

    The current workflow run handles the first batch immediately; every
    subsequent batch requires waiting for the next scheduled run.

    Args:
        pending: Number of countries still to be processed.
        batch_size: Countries processed per workflow run.
        workflow_interval_hours: Hours between scheduled workflow runs.

    Returns:
        ISO-style UTC datetime string (e.g. "2026-04-05 14:00 UTC"), or
        None when there is nothing left to process.
    """
    if pending <= 0:
        return None
    batches_remaining = math.ceil(pending / batch_size)
    # The current run covers the first batch, so only (batches_remaining - 1)
    # future intervals need to elapse before everything is processed.
    future_runs = max(batches_remaining - 1, 0)
    eta = datetime.now(timezone.utc) + timedelta(hours=future_runs * workflow_interval_hours)
    return eta.strftime("%Y-%m-%d %H:%M UTC")


class GitHubIssueManager:
    """Manages GitHub issues for validation cycle tracking."""

    def __init__(self, repo: str = "mgifford/eu-plus-government-scans"):
        self.repo = repo
        self._has_gh_cli = self._check_gh_cli()

    def _check_gh_cli(self) -> bool:
        """Check if GitHub CLI is available."""
        try:
            result = subprocess.run(
                ["gh", "--version"],
                capture_output=True,
                text=True,
                timeout=GH_CLI_CHECK_TIMEOUT
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _run_gh_command(self, args: list[str]) -> tuple[bool, str]:
        """
        Run a GitHub CLI command.

        Returns:
            Tuple of (success, output)
        """
        if not self._has_gh_cli:
            return False, "GitHub CLI not available"

        try:
            result = subprocess.run(
                ["gh"] + args,
                capture_output=True,
                text=True,
                timeout=GH_CLI_COMMAND_TIMEOUT,
                env={**os.environ, "GH_REPO": self.repo}
            )
            return result.returncode == 0, result.stdout.strip()
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)

    def create_validation_issue(self, cycle_id: str) -> Optional[int]:
        """
        Create a GitHub issue to track a validation cycle.

        Args:
            cycle_id: The cycle ID

        Returns:
            Issue number if created successfully, None otherwise
        """
        title = f"URL Validation Cycle: {cycle_id}"
        body = f"""This issue tracks the automated URL validation cycle `{cycle_id}`.

## Progress

Batch validation is in progress. This issue will be automatically updated with progress.

**Status:** 🟡 In Progress

This issue will be automatically closed when all countries have been validated.

---
*This issue is managed by the automated URL validation workflow.*
"""

        success, output = self._run_gh_command([
            "issue", "create",
            "--title", title,
            "--body", body,
            "--label", "url-validation",
            "--label", "automated"
        ])

        if success:
            # Parse issue number from output (format: "URL")
            # Example: https://github.com/owner/repo/issues/123
            try:
                issue_number = int(output.split("/")[-1])
                return issue_number
            except (ValueError, IndexError):
                return None

        return None

    def update_issue_progress(
        self,
        issue_number: int,
        cycle_id: str,
        total: int,
        completed: int,
        processing: int,
        pending: int,
        failed: int,
        batch_size: int = 4,
        workflow_interval_hours: float = 12.0,
    ):
        """
        Update issue with current progress.

        Args:
            issue_number: GitHub issue number
            cycle_id: Cycle ID
            total: Total countries
            completed: Completed countries
            processing: Currently processing countries
            pending: Pending countries
            failed: Failed countries
            batch_size: Countries processed per workflow run (for ETA).
            workflow_interval_hours: Hours between scheduled runs (for ETA).
        """
        progress_pct = (completed / total * 100) if total > 0 else 0

        # Create progress bar
        bar_length = 20
        filled = int(bar_length * completed / total) if total > 0 else 0
        bar = "█" * filled + "░" * (bar_length - filled)

        is_complete = pending == 0 and processing == 0
        status_emoji = "🟢" if is_complete else "🟡"

        eta_line = ""
        if not is_complete:
            eta = _compute_eta(pending, batch_size, workflow_interval_hours)
            if eta:
                eta_line = f"\n- 🕐 Est. completion: {eta}"

        body = f"""This issue tracks the automated URL validation cycle `{cycle_id}`.

## Progress

**Status:** {status_emoji} {"Complete" if is_complete else "In Progress"}

{bar} {progress_pct:.1f}%

- ✅ Completed: {completed}/{total}
- 🔄 Processing: {processing}
- ⏳ Pending: {pending}
- ❌ Failed: {failed}{eta_line}

### Details

The validation workflow runs every {workflow_interval_hours:.0f} hours and processes countries in batches to avoid GitHub Actions timeouts.

---
*Last updated: Automatically by URL validation workflow*
*This issue is managed by automated workflow and will close when complete.*
"""

        self._run_gh_command([
            "issue", "edit", str(issue_number),
            "--body", body
        ])

    def close_validation_issue(
        self,
        issue_number: int,
        cycle_id: str,
        total: int,
        completed: int,
        failed: int,
    ):
        """
        Close a validation cycle issue.

        Args:
            issue_number: GitHub issue number
            cycle_id: Cycle ID
            total: Total countries
            completed: Successfully completed countries
            failed: Failed countries
        """
        body = f"""This validation cycle `{cycle_id}` has completed.

## Final Results

**Status:** 🟢 Complete

- ✅ Successfully validated: {completed}/{total} countries
- ❌ Failed: {failed} countries

All countries have been processed. The validation cycle is complete.

---
*Closed automatically by URL validation workflow*
"""

        self._run_gh_command([
            "issue", "edit", str(issue_number),
            "--body", body
        ])

        self._run_gh_command([
            "issue", "close", str(issue_number),
            "--reason", "completed"
        ])

    def add_comment(self, issue_number: int, comment: str):
        """Add a comment to an issue."""
        self._run_gh_command([
            "issue", "comment", str(issue_number),
            "--body", comment
        ])

    def reopen_issue(self, issue_number: int):
        """Reopen a closed issue."""
        self._run_gh_command([
            "issue", "reopen", str(issue_number)
        ])

    def find_open_validation_issue(self) -> Optional[int]:
        """
        Find an open validation issue.

        Returns:
            Issue number if found, None otherwise
        """
        success, output = self._run_gh_command([
            "issue", "list",
            "--label", "url-validation",
            "--state", "open",
            "--limit", "1",
            "--json", "number",
            "--jq", ".[0].number"
        ])

        if success and output:
            try:
                return int(output)
            except ValueError:
                return None

        return None

    def create_review_issue(
        self,
        cycle_id: str,
        total: int,
        completed: int,
        failed: int,
        tracking_issue_number: Optional[int] = None,
    ) -> Optional[int]:
        """
        Create a GitHub issue prompting human review of validation findings.

        This issue is opened automatically when a validation cycle completes
        so that maintainers can triage removed URLs, failures, and redirects.

        Args:
            cycle_id: The completed cycle ID.
            total: Total countries in the cycle.
            completed: Number of successfully validated countries.
            failed: Number of failed countries.
            tracking_issue_number: Optional tracking issue number for cross-reference.

        Returns:
            New issue number if created successfully, None otherwise.
        """
        title = f"Review validation findings: {cycle_id}"

        tracking_ref = ""
        if tracking_issue_number:
            tracking_ref = (
                f"\n\nThis validation was tracked in issue #{tracking_issue_number}."
            )

        body = f"""The URL validation cycle `{cycle_id}` has completed.
Please review the findings.

## Summary

- ✅ Successfully validated: {completed}/{total} countries
- ❌ Failed: {failed} countries{tracking_ref}

## Review Checklist

- [ ] Check for domains with a high URL failure rate
- [ ] Review removed URLs for false positives
- [ ] Verify that failed countries can be retried (use `--reset-failed`)
- [ ] Update TOON seed files if permanent changes are needed

---
*This issue was automatically created by the URL validation workflow.*
"""

        success, output = self._run_gh_command([
            "issue", "create",
            "--title", title,
            "--body", body,
            "--label", "automated",
        ])

        if success:
            try:
                return int(output.split("/")[-1])
            except (ValueError, IndexError):
                return None

        return None
