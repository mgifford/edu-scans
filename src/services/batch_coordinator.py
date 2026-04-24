"""Batch coordinator for managing URL validation cycles across countries."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from src.storage.schema import ValidationBatchState

# Cycle ID timestamp format (e.g., "20260226-223045")
CYCLE_ID_FORMAT = '%Y%m%d-%H%M%S'


@dataclass
class BatchConfig:
    """Configuration for batch processing."""
    batch_size: int = 4  # Number of countries per batch
    # Max runtime aligns with GitHub Actions timeout in validate-urls-batch.yml
    # CLI implementation uses 50 min to leave 10 min safety buffer
    max_runtime_minutes: int = 60  # GitHub Actions workflow timeout limit


class BatchCoordinator:
    """Coordinates batched URL validation across countries."""

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def get_or_create_cycle(self, github_issue_number: Optional[int] = None) -> str:
        """
        Get the current active cycle or create a new one.

        Args:
            github_issue_number: Optional GitHub issue number tracking this cycle

        Returns:
            Cycle ID (format: YYYYMMDD-HHMMSS)
        """
        conn = sqlite3.connect(self.db_path)
        try:
            # Check for an active cycle (has pending or processing countries)
            cursor = conn.execute(
                """
                SELECT DISTINCT cycle_id, github_issue_number
                FROM validation_batch_state
                WHERE status IN ('pending', 'processing')
                ORDER BY cycle_id DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()

            if row:
                cycle_id, existing_issue = row
                # Update issue number if provided and not already set
                if github_issue_number and not existing_issue:
                    conn.execute(
                        """
                        UPDATE validation_batch_state
                        SET github_issue_number = ?
                        WHERE cycle_id = ?
                        """,
                        (github_issue_number, cycle_id)
                    )
                    conn.commit()
                return cycle_id

            # Create new cycle
            cycle_id = datetime.now(timezone.utc).strftime(CYCLE_ID_FORMAT)

            # Initialize all countries as pending for this cycle
            # We'll get the list from available TOON files
            countries = self._get_available_countries()

            for country_code in countries:
                conn.execute(
                    """
                    INSERT INTO validation_batch_state
                    (cycle_id, country_code, status, github_issue_number)
                    VALUES (?, ?, 'pending', ?)
                    """,
                    (cycle_id, country_code, github_issue_number)
                )

            conn.commit()
            return cycle_id

        finally:
            conn.close()

    def _get_available_countries(self) -> List[str]:
        """Get list of countries from TOON files."""
        from src.lib.country_utils import country_filename_to_code

        toon_dir = Path("data/toon-seeds")
        countries = []

        if toon_dir.exists():
            for toon_file in sorted(toon_dir.glob("*.toon")):
                country_code = country_filename_to_code(toon_file.stem)
                countries.append(country_code)

        return countries

    def get_next_batch(self, cycle_id: str, batch_size: int) -> List[str]:
        """
        Get the next batch of countries to process.

        Args:
            cycle_id: The current cycle ID
            batch_size: Number of countries to return

        Returns:
            List of country codes to process
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                SELECT country_code
                FROM validation_batch_state
                WHERE cycle_id = ? AND status = 'pending'
                ORDER BY country_code
                LIMIT ?
                """,
                (cycle_id, batch_size)
            )
            return [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

    def mark_batch_processing(self, cycle_id: str, country_codes: List[str]):
        """Mark countries as currently being processed."""
        conn = sqlite3.connect(self.db_path)
        try:
            now = datetime.now(timezone.utc).isoformat()
            for country_code in country_codes:
                conn.execute(
                    """
                    UPDATE validation_batch_state
                    SET status = 'processing', started_at = ?
                    WHERE cycle_id = ? AND country_code = ?
                    """,
                    (now, cycle_id, country_code)
                )
            conn.commit()
        finally:
            conn.close()

    def mark_batch_completed(self, cycle_id: str, country_codes: List[str]):
        """Mark countries as successfully completed."""
        conn = sqlite3.connect(self.db_path)
        try:
            now = datetime.now(timezone.utc).isoformat()
            for country_code in country_codes:
                conn.execute(
                    """
                    UPDATE validation_batch_state
                    SET status = 'completed', completed_at = ?
                    WHERE cycle_id = ? AND country_code = ?
                    """,
                    (now, cycle_id, country_code)
                )
            conn.commit()
        finally:
            conn.close()

    def mark_batch_failed(self, cycle_id: str, country_code: str, error_message: str):
        """Mark a country as failed with error message."""
        conn = sqlite3.connect(self.db_path)
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                UPDATE validation_batch_state
                SET status = 'failed', completed_at = ?, error_message = ?
                WHERE cycle_id = ? AND country_code = ?
                """,
                (now, error_message, cycle_id, country_code)
            )
            conn.commit()
        finally:
            conn.close()

    def reset_failed_countries(self, cycle_id: str):
        """Reset all failed countries in a cycle back to pending so they can be retried."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                UPDATE validation_batch_state
                SET status = 'pending', started_at = NULL, completed_at = NULL, error_message = NULL
                WHERE cycle_id = ? AND status = 'failed'
                """,
                (cycle_id,)
            )
            conn.commit()
        finally:
            conn.close()

    def mark_batch_pending(self, cycle_id: str, country_code: str):
        """Mark a country as pending (e.g., when stopping early due to timeout)."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                UPDATE validation_batch_state
                SET status = 'pending', started_at = NULL
                WHERE cycle_id = ? AND country_code = ?
                """,
                (cycle_id, country_code)
            )
            conn.commit()
        finally:
            conn.close()

    def get_cycle_progress(self, cycle_id: str) -> dict:
        """
        Get progress statistics for a cycle.

        Returns:
            Dictionary with progress statistics
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) as processing,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    MAX(github_issue_number) as issue_number
                FROM validation_batch_state
                WHERE cycle_id = ?
                """,
                (cycle_id,)
            )
            row = cursor.fetchone()

            if not row:
                return {
                    "total": 0,
                    "completed": 0,
                    "processing": 0,
                    "pending": 0,
                    "failed": 0,
                    "is_complete": False,
                    "issue_number": None,
                }

            total, completed, processing, pending, failed, issue_number = row

            return {
                "cycle_id": cycle_id,
                "total": total or 0,
                "completed": completed or 0,
                "processing": processing or 0,
                "pending": pending or 0,
                "failed": failed or 0,
                "is_complete": (pending or 0) == 0 and (processing or 0) == 0,
                "issue_number": issue_number,
            }
        finally:
            conn.close()

    def get_cycle_details(self, cycle_id: str) -> List[ValidationBatchState]:
        """Get detailed state for all countries in a cycle."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                SELECT cycle_id, country_code, status, started_at, completed_at,
                       github_issue_number, error_message
                FROM validation_batch_state
                WHERE cycle_id = ?
                ORDER BY
                    CASE status
                        WHEN 'processing' THEN 1
                        WHEN 'pending' THEN 2
                        WHEN 'failed' THEN 3
                        WHEN 'completed' THEN 4
                    END,
                    country_code
                """,
                (cycle_id,)
            )

            results = []
            for row in cursor.fetchall():
                results.append(ValidationBatchState(
                    cycle_id=row[0],
                    country_code=row[1],
                    status=row[2],
                    started_at=row[3],
                    completed_at=row[4],
                    github_issue_number=row[5],
                    error_message=row[6],
                ))

            return results
        finally:
            conn.close()
