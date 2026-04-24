"""Handler for processing issue-triggered validation scans."""

from __future__ import annotations

import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.jobs.url_validation_scanner import UrlValidationScanner
from src.lib.country_utils import country_code_to_filename
from src.services.github_issue_manager import GitHubIssueManager


@dataclass
class TriggerConfig:
    """Configuration for a trigger type."""
    prefix: str
    is_periodic: bool  # If True, don't close issue after processing
    schedule: Optional[str] = None  # Human-readable schedule description
    cooldown_hours: Optional[int] = None  # Minimum hours between runs; None = always run
    day_of_week: Optional[int] = None  # 0=Monday … 6=Sunday; None = any day


# Default max runtime for a single issue-triggered validation run (45 minutes).
# The caller can override this via the max_seconds argument on
# process_trigger_issue().
DEFAULT_MAX_SECONDS = 45 * 60

# Safety buffer: stop processing with this many seconds to spare so the
# workflow has time to upload artifacts and post comments before the hard
# GitHub Actions timeout fires.  Shared between this module and the CLI.
SAFETY_BUFFER_SECONDS = 5 * 60

# Supported trigger prefixes
TRIGGER_CONFIGS = [
    TriggerConfig("SCAN:", is_periodic=False, cooldown_hours=None),
    TriggerConfig("QUARTERLY:", is_periodic=True, schedule="quarterly", cooldown_hours=85 * 24),
    TriggerConfig("MONTHLY:", is_periodic=True, schedule="monthly", cooldown_hours=28 * 24),
    TriggerConfig("WEEKLY:", is_periodic=True, schedule="weekly", cooldown_hours=6 * 24),
    TriggerConfig("MONDAYS:", is_periodic=True, schedule="every Monday", cooldown_hours=23, day_of_week=0),
    TriggerConfig("TUESDAYS:", is_periodic=True, schedule="every Tuesday", cooldown_hours=23, day_of_week=1),
    TriggerConfig("WEDNESDAYS:", is_periodic=True, schedule="every Wednesday", cooldown_hours=23, day_of_week=2),
    TriggerConfig("THURSDAYS:", is_periodic=True, schedule="every Thursday", cooldown_hours=23, day_of_week=3),
    TriggerConfig("FRIDAYS:", is_periodic=True, schedule="every Friday", cooldown_hours=23, day_of_week=4),
    TriggerConfig("SATURDAYS:", is_periodic=True, schedule="every Saturday", cooldown_hours=23, day_of_week=5),
    TriggerConfig("SUNDAYS:", is_periodic=True, schedule="every Sunday", cooldown_hours=23, day_of_week=6),
]


class IssueTriggerHandler:
    """Handles processing of issue-triggered validation scans."""

    def __init__(
        self,
        scanner: UrlValidationScanner,
        issue_manager: GitHubIssueManager,
        db_path: Path,
    ):
        self.scanner = scanner
        self.issue_manager = issue_manager
        self.db_path = db_path
        self.toon_dir = Path("data/toon-seeds")

    # ------------------------------------------------------------------
    # Schedule / cooldown helpers
    # ------------------------------------------------------------------

    def is_due_for_run(
        self,
        issue_number: int,
        config: TriggerConfig,
        now: Optional[datetime] = None,
    ) -> bool:
        """
        Return True if this issue should be processed in the current run.

        Respects:
        - Day-of-week restriction (e.g. MONDAYS: only fires on Mondays).
        - Cooldown period based on the last *completed* run stored in the DB.

        Args:
            issue_number: GitHub issue number.
            config: The trigger configuration for this issue.
            now: Current datetime (injectable for testing; defaults to UTC now).
        """
        if now is None:
            now = datetime.now(timezone.utc)

        # Day-of-week guard: skip entirely if today doesn't match.
        if config.day_of_week is not None:
            if now.weekday() != config.day_of_week:
                return False

        # No cooldown configured -> always run (e.g. SCAN:).
        if config.cooldown_hours is None:
            return True

        last_completed = self._get_last_completed_run(issue_number)
        if last_completed is None:
            return True  # Never run before; proceed.

        elapsed_hours = (now - last_completed).total_seconds() / 3600
        return elapsed_hours >= config.cooldown_hours

    def _get_last_completed_run(self, issue_number: int) -> Optional[datetime]:
        """Return the completed_at timestamp of the most recent successful run."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                SELECT completed_at
                FROM issue_trigger_runs
                WHERE issue_number = ? AND status = 'completed'
                ORDER BY completed_at DESC
                LIMIT 1
                """,
                (issue_number,),
            )
            row = cursor.fetchone()
            if row and row[0]:
                return datetime.fromisoformat(row[0])
            return None
        finally:
            conn.close()

    def _record_run_start(self, issue_number: int, prefix: str) -> str:
        """Insert a 'running' row and return the started_at timestamp string."""
        started_at = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO issue_trigger_runs
                    (issue_number, trigger_prefix, started_at, status)
                VALUES (?, ?, ?, 'running')
                """,
                (issue_number, prefix, started_at),
            )
            conn.commit()
        finally:
            conn.close()
        return started_at

    def _record_run_complete(
        self, issue_number: int, started_at: str, status: str
    ):
        """Update the run row with completion details."""
        completed_at = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                UPDATE issue_trigger_runs
                SET completed_at = ?, status = ?
                WHERE issue_number = ? AND started_at = ?
                """,
                (completed_at, status, issue_number, started_at),
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Issue discovery
    # ------------------------------------------------------------------

    def find_trigger_issues(self) -> List[Dict[str, Any]]:
        """
        Find open issues with trigger prefixes in their titles.

        Returns:
            List of issue dictionaries with keys: number, title, body, trigger_config
        """
        try:
            result = subprocess.run(
                [
                    "gh", "issue", "list",
                    "--state", "open",
                    "--json", "number,title,body",
                    "--limit", "100",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                print(f"Warning: Could not list issues: {result.stderr}")
                return []

            import json
            issues = json.loads(result.stdout)

            trigger_issues = []
            for issue in issues:
                title = issue.get("title", "")
                for config in TRIGGER_CONFIGS:
                    if title.upper().startswith(config.prefix):
                        issue["trigger_config"] = config
                        trigger_issues.append(issue)
                        break

            return trigger_issues

        except Exception as e:
            print(f"Error finding trigger issues: {e}")
            return []

    # ------------------------------------------------------------------
    # Issue processing
    # ------------------------------------------------------------------

    async def process_trigger_issue(
        self,
        issue: Dict[str, Any],
        max_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Process a trigger issue by running validation and posting results.

        Args:
            issue: Issue dictionary with number, title, body, trigger_config.
            max_seconds: Optional upper bound on wall-clock seconds for this
                call.  When set, the URL validation loop will stop early to
                stay within budget (with a 5-minute safety margin).

        Returns:
            Dictionary with keys: success, closed, skipped, error (optional).
        """
        issue_number = issue["number"]
        title = issue["title"]
        config = issue["trigger_config"]

        print(f"Processing issue #{issue_number}: {title}")
        print(f"Trigger type: {config.prefix} ({'periodic' if config.is_periodic else 'one-time'})")
        if config.schedule:
            print(f"Schedule: {config.schedule}")
        print("")

        # Schedule / cooldown check -- skip rather than fail.
        if not self.is_due_for_run(issue_number, config):
            schedule_msg = config.schedule or config.prefix
            print(f"Skipping issue #{issue_number}: not yet due per {schedule_msg} schedule")
            return {"success": True, "closed": False, "skipped": True}

        # Dispatch based on title keywords.
        if "validate" in title.lower() and "url" in title.lower():
            return await self._process_url_validation(
                issue_number, config, max_seconds=max_seconds
            )
        else:
            print(f"Unknown trigger action in title: {title}")
            return {
                "success": False,
                "closed": False,
                "skipped": False,
                "error": "Unknown trigger action - title must contain 'validate url'",
            }

    async def _process_url_validation(
        self,
        issue_number: int,
        config: TriggerConfig,
        max_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Process URL validation for all countries."""
        import time

        if max_seconds is None:
            max_seconds = DEFAULT_MAX_SECONDS

        # Safety margin: stop scanning when less than the shared buffer remains.
        safety_buffer_seconds = SAFETY_BUFFER_SECONDS

        started_at = self._record_run_start(issue_number, config.prefix)
        run_start = time.monotonic()

        print("Starting URL validation for all countries...")
        print(f"Time budget: {max_seconds / 60:.1f} minutes")
        print("")

        countries = self._get_all_countries()
        print(f"Found {len(countries)} countries to validate")
        print("")

        all_stats = []
        stopped_early = False

        for idx, country_code in enumerate(countries, 1):
            # Time-budget check before each country.
            elapsed = time.monotonic() - run_start
            remaining = max_seconds - elapsed

            if remaining < safety_buffer_seconds:
                print(
                    f"Approaching time limit after {elapsed / 60:.1f} min "
                    f"-- stopping early ({idx - 1}/{len(countries)} countries done)"
                )
                stopped_early = True
                break

            try:
                toon_file = self.toon_dir / f"{country_code_to_filename(country_code)}.toon"

                if not toon_file.exists():
                    print(f"[{idx}/{len(countries)}] Skipping {country_code}: TOON file not found")
                    continue

                print(f"[{idx}/{len(countries)}] Processing {country_code}...")

                stats = await self.scanner.scan_country(
                    country_code,
                    toon_file,
                    rate_limit_per_second=2.0,
                )

                all_stats.append(stats)
                print(
                    f"  valid={stats['valid_urls']} invalid={stats['invalid_urls']} "
                    f"removed={stats['urls_removed']}"
                )
                print("")

            except Exception as e:
                print(f"  Error processing {country_code}: {e}")
                print("")

        # Generate and post report.
        report = self._generate_validation_report(all_stats, config, stopped_early=stopped_early)

        print(f"Posting validation report to issue #{issue_number}...")
        self.issue_manager.add_comment(issue_number, report)

        # Record completion in the DB.
        self._record_run_complete(issue_number, started_at, "completed")

        # Close the issue only for one-time scans that finished completely.
        if not config.is_periodic and not stopped_early:
            print(f"Closing issue #{issue_number} (one-time scan complete)")
            self._close_issue(issue_number)
            return {"success": True, "closed": True, "skipped": False}
        else:
            if stopped_early:
                print(
                    f"Issue #{issue_number} remains open (stopped early -- "
                    "remaining countries will be processed in next run)"
                )
            else:
                print(f"Issue #{issue_number} remains open (periodic scan)")
            return {"success": True, "closed": False, "skipped": False}

    def _get_all_countries(self) -> List[str]:
        """Get list of all countries from TOON files."""
        from src.lib.country_utils import country_filename_to_code

        countries = []
        if self.toon_dir.exists():
            for toon_file in sorted(self.toon_dir.glob("*.toon")):
                if "_validated" in toon_file.stem:
                    continue
                country_code = country_filename_to_code(toon_file.stem)
                countries.append(country_code)

        return countries

    def _generate_validation_report(
        self,
        all_stats: List[Dict[str, Any]],
        config: TriggerConfig,
        stopped_early: bool = False,
    ) -> str:
        """Generate a markdown report from validation statistics."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        total_countries = len(all_stats)
        total_urls = sum(s.get("total_urls", 0) for s in all_stats)
        total_validated = sum(s.get("urls_validated", 0) for s in all_stats)
        total_valid = sum(s.get("valid_urls", 0) for s in all_stats)
        total_invalid = sum(s.get("invalid_urls", 0) for s in all_stats)
        total_redirected = sum(s.get("redirected_urls", 0) for s in all_stats)
        total_removed = sum(s.get("urls_removed", 0) for s in all_stats)

        valid_pct = (total_valid / total_validated * 100) if total_validated > 0 else 0
        invalid_pct = (total_invalid / total_validated * 100) if total_validated > 0 else 0

        status_note = ""
        if stopped_early:
            status_note = (
                "\n> **Partial run** -- validation stopped early due to time limit. "
                "Remaining countries will be included in the next scheduled run.\n"
            )

        report = f"""## URL Validation Report

**Trigger:** {config.prefix} {f"({config.schedule})" if config.schedule else ""}
**Completed:** {timestamp}
**Countries Processed:** {total_countries}
{status_note}
### Summary

| Metric | Count |
|--------|-------|
| Total URLs | {total_urls:,} |
| Validated | {total_validated:,} |
| Valid | {total_valid:,} ({valid_pct:.1f}%) |
| Invalid | {total_invalid:,} ({invalid_pct:.1f}%) |
| Redirected | {total_redirected:,} |
| Removed (failed 2x) | {total_removed:,} |

### Country Details

| Country | Total | Valid | Invalid | Redirected | Removed |
|---------|-------|-------|---------|------------|---------|
"""

        for stats in all_stats:
            country = stats.get("country_code", "Unknown")
            total = stats.get("total_urls", 0)
            valid = stats.get("valid_urls", 0)
            invalid = stats.get("invalid_urls", 0)
            redirected = stats.get("redirected_urls", 0)
            removed = stats.get("urls_removed", 0)
            report += f"| {country} | {total} | {valid} | {invalid} | {redirected} | {removed} |\n"

        report += """
### Notes

- URLs are validated with a 20-second timeout
- Failed URLs are tracked across scans
- URLs are removed after failing twice
- Redirects are followed and URLs are updated
"""

        if config.is_periodic:
            report += (
                f"\n**Next Run:** This issue will remain open and validation "
                f"will run {config.schedule}.\n"
            )
        elif stopped_early:
            report += (
                "\n**Status:** Partial validation complete. "
                "Issue remains open for the next run.\n"
            )
        else:
            report += "\n**Status:** Validation complete. Issue will be closed.\n"

        return report

    def _close_issue(self, issue_number: int):
        """Close an issue after a one-time scan."""
        try:
            subprocess.run(
                [
                    "gh", "issue", "close", str(issue_number),
                    "--reason", "completed",
                    "--comment", "Validation complete. See report above.",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception as e:
            print(f"Warning: Could not close issue: {e}")
