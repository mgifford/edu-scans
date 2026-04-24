"""URL validation scanner job for processing TOON files."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from src.lib.country_utils import country_filename_to_code
from src.lib.settings import Settings
from src.services.url_validator import UrlValidator, ValidationResult
from src.storage.schema import initialize_schema


@dataclass(slots=True)
class ScanSession:
    """Tracks state for a single validation scan session."""
    scan_id: str
    country_code: str
    failed_urls: Set[str]
    processed_urls: Set[str]


class UrlValidationScanner:
    """Scanner for validating URLs from TOON files."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.validator = UrlValidator(
            timeout_seconds=settings.crawl_timeout_seconds,
        )
        self.db_path = initialize_schema(settings.metadata_db_url)

    def _load_toon_file(self, toon_path: Path) -> dict:
        """Load and parse a TOON file."""
        with toon_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _extract_urls_from_toon(self, toon_data: dict) -> List[str]:
        """Extract all page URLs from TOON data structure."""
        urls = []
        for domain_entry in toon_data.get("domains", []):
            for page in domain_entry.get("pages", []):
                url = page.get("url")
                if url:
                    urls.append(url)
        return urls

    def _get_previous_failures(self, country_code: str) -> Dict[str, int]:
        """
        Get failure counts for URLs from previous scans.

        Returns:
            Dictionary mapping URL to failure count
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                SELECT url, MAX(failure_count) as max_failures
                FROM url_validation_results
                WHERE country_code = ?
                GROUP BY url
                """,
                (country_code,)
            )
            return {row[0]: row[1] for row in cursor.fetchall()}
        finally:
            conn.close()

    def _get_recently_confirmed_urls(
        self, country_code: str, within_days: int = 30
    ) -> Set[str]:
        """
        Return URLs already confirmed reachable by *any* scan within the last
        ``within_days`` days.

        Checks two sources:
        * ``url_social_media_results`` — URLs fetched by the social media
          scanner that were reachable (is_reachable = 1).
        * ``url_validation_results`` — URLs previously validated as valid
          (is_valid = 1).

        This prevents redundant re-validation of pages that were already
        confirmed working by a more-comprehensive scan (e.g. social media
        scanning, which downloads and parses the full page).

        Args:
            country_code: Country to look up.
            within_days: Consider results from the last N days (default 30).

        Returns:
            Set of URL strings that do not need re-validation.
        """
        from datetime import timedelta

        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=within_days)
        ).isoformat()

        conn = sqlite3.connect(self.db_path)
        try:
            confirmed: Set[str] = set()

            # URLs confirmed reachable by the social media scanner
            for table, ts_col, condition in [
                (
                    "url_social_media_results",
                    "scanned_at",
                    "is_reachable = 1",
                ),
                (
                    "url_validation_results",
                    "validated_at",
                    "is_valid = 1",
                ),
            ]:
                cursor = conn.execute(
                    f"""
                    SELECT DISTINCT url
                    FROM {table}
                    WHERE country_code = ?
                      AND {condition}
                      AND {ts_col} >= ?
                    """,
                    (country_code, cutoff),
                )
                confirmed.update(row[0] for row in cursor.fetchall())

            return confirmed
        finally:
            conn.close()

    def _save_validation_results(
        self,
        results: List[ValidationResult],
        country_code: str,
        scan_id: str,
        previous_failures: Dict[str, int],
    ):
        """Save validation results to database."""
        conn = sqlite3.connect(self.db_path)
        try:
            for result in results:
                # Calculate new failure count
                prev_failures = previous_failures.get(result.url, 0)
                new_failure_count = prev_failures + 1 if not result.is_valid else 0

                # Build redirect chain as JSON string
                redirect_chain_json = None
                if result.redirect_chain:
                    redirect_chain_json = json.dumps(result.redirect_chain)

                conn.execute(
                    """
                    INSERT INTO url_validation_results
                    (url, country_code, scan_id, status_code, error_message,
                     redirected_to, redirect_chain, is_valid, failure_count, validated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.url,
                        country_code,
                        scan_id,
                        result.status_code,
                        result.error_message,
                        result.redirected_to,
                        redirect_chain_json,
                        1 if result.is_valid else 0,
                        new_failure_count,
                        result.validated_at,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def _update_toon_with_validation(
        self,
        toon_data: dict,
        validation_results: Dict[str, ValidationResult],
        urls_to_remove: Set[str],
    ) -> dict:
        """
        Update TOON data with validation results and remove failed URLs.

        Args:
            toon_data: Original TOON data
            validation_results: Validation results by URL
            urls_to_remove: URLs that failed twice and should be removed

        Returns:
            Updated TOON data
        """
        updated_domains = []

        for domain_entry in toon_data.get("domains", []):
            updated_pages = []

            for page in domain_entry.get("pages", []):
                url = page.get("url")

                # Skip URLs that should be removed (failed twice)
                if url in urls_to_remove:
                    continue

                # Add validation metadata
                if url in validation_results:
                    result = validation_results[url]
                    page["validation_status"] = "valid" if result.is_valid else "invalid"

                    if result.status_code is not None:
                        page["status_code"] = result.status_code

                    if result.error_message:
                        page["error_message"] = result.error_message

                    if result.redirected_to:
                        page["redirected_to"] = result.redirected_to
                        # Update the URL to the redirect target for future scans
                        page["original_url"] = url
                        page["url"] = result.redirected_to

                updated_pages.append(page)

            # Only keep domain if it has pages left
            if updated_pages:
                domain_entry["pages"] = updated_pages
                updated_domains.append(domain_entry)

        # Update domain and page counts
        toon_data["domains"] = updated_domains
        toon_data["domain_count"] = len(updated_domains)
        toon_data["page_count"] = sum(len(d.get("pages", [])) for d in updated_domains)

        return toon_data

    async def scan_country(
        self,
        country_code: str,
        toon_path: Path,
        rate_limit_per_second: float = 2.0,
        skip_recently_validated_days: int = 0,
        max_runtime_seconds: Optional[float] = None,
        start_time: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Scan all URLs in a country's TOON file.

        Args:
            country_code: ISO country code
            toon_path: Path to TOON file
            rate_limit_per_second: Max requests per second
            skip_recently_validated_days: Skip URLs confirmed reachable by
                *any* scanner within this many days (0 = always re-validate).
                Passing a positive value avoids redundant HTTP requests when
                the social-media or tech scanner has already fetched the page
                recently.
            max_runtime_seconds: Shared runtime budget in seconds measured
                from *start_time*.  When the remaining budget drops below
                60 seconds validation stops gracefully.  ``None`` = no limit.
            start_time: ``time.monotonic()`` value from the start of the
                overall job.  ``None`` means a fresh clock for this country.

        Returns:
            Scan statistics and results
        """
        scan_id = f"{country_code}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S%f')}-{uuid4().hex[:8]}"

        # Use the caller's start_time so the budget is shared across countries.
        _start = start_time if start_time is not None else time.monotonic()

        print(f"Starting scan {scan_id} for {country_code}")
        print(f"Loading TOON file: {toon_path}")

        # Load TOON data
        toon_data = self._load_toon_file(toon_path)
        urls = self._extract_urls_from_toon(toon_data)

        print(f"Found {len(urls)} URLs to validate")

        # Get previous failure counts
        previous_failures = self._get_previous_failures(country_code)

        # Filter out URLs that already failed twice (skip them)
        urls_to_skip = {url for url, count in previous_failures.items() if count >= 2}

        # Optionally skip URLs already confirmed valid by any recent scan.
        recently_confirmed: Set[str] = set()
        if skip_recently_validated_days > 0:
            recently_confirmed = self._get_recently_confirmed_urls(
                country_code, within_days=skip_recently_validated_days
            )
            if recently_confirmed:
                print(
                    f"Skipping {len(recently_confirmed)} URLs already confirmed "
                    f"reachable within the last {skip_recently_validated_days} day(s)"
                )

        urls_to_validate = [
            url for url in urls
            if url not in urls_to_skip and url not in recently_confirmed
        ]

        print(f"Skipping {len(urls_to_skip)} URLs that previously failed twice")
        print(f"Validating {len(urls_to_validate)} URLs")

        # Build an incremental save callback so partial results are persisted
        # even if the job is stopped early due to a timeout.

        def _save_result(result: ValidationResult) -> None:
            """Persist a single validation result immediately after it is computed."""
            self._save_validation_results([result], country_code, scan_id, previous_failures)

        # Validate URLs
        validation_results = await self.validator.validate_urls_batch(
            urls_to_validate,
            rate_limit_per_second=rate_limit_per_second,
            max_runtime_seconds=max_runtime_seconds,
            start_time=_start,
            on_result=_save_result,
        )

        # Identify newly failed URLs (failed twice total)
        newly_failed_twice = set()
        for url, result in validation_results.items():
            if not result.is_valid:
                prev_count = previous_failures.get(url, 0)
                if prev_count + 1 >= 2:
                    newly_failed_twice.add(url)

        # Combine with already failed URLs
        urls_to_remove = urls_to_skip | newly_failed_twice

        # Update TOON file with validation results
        updated_toon = self._update_toon_with_validation(
            toon_data,
            validation_results,
            urls_to_remove,
        )

        # Save updated TOON file
        output_path = toon_path.parent / f"{toon_path.stem}_validated{toon_path.suffix}"
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(updated_toon, f, indent=2, ensure_ascii=False)

        scanned_count = len(validation_results)
        is_complete = scanned_count == len(urls_to_validate)
        if is_complete:
            print(f"Saved validated TOON to: {output_path}")
        else:
            print(
                f"Saved partial validated TOON to: {output_path} "
                f"({scanned_count}/{len(urls_to_validate)} URLs validated)"
            )

        # Calculate statistics
        valid_count = sum(1 for r in validation_results.values() if r.is_valid)
        invalid_count = len(validation_results) - valid_count
        redirect_count = sum(1 for r in validation_results.values() if r.redirected_to)

        stats = {
            "scan_id": scan_id,
            "country_code": country_code,
            "total_urls": len(urls),
            "urls_validated": len(validation_results),
            "urls_skipped": len(urls_to_skip),
            "urls_skipped_recently_confirmed": len(recently_confirmed),
            "is_complete": is_complete,
            "valid_urls": valid_count,
            "invalid_urls": invalid_count,
            "redirected_urls": redirect_count,
            "urls_removed": len(urls_to_remove),
            "output_path": str(output_path),
        }

        print(f"\nValidation {'complete' if is_complete else 'partial'}:")
        print(f"  Validated:   {scanned_count}/{len(urls_to_validate)}")
        print(f"  Valid:       {valid_count}")
        print(f"  Invalid:     {invalid_count}")
        print(f"  Redirected:  {redirect_count}")
        print(f"  Removed (failed 2×): {len(urls_to_remove)}")
        if recently_confirmed:
            print(f"  Skipped (recently confirmed): {len(recently_confirmed)}")

        return stats

    async def scan_all_countries(
        self,
        toon_seeds_dir: Path,
        rate_limit_per_second: float = 2.0,
        skip_recently_validated_days: int = 0,
        max_runtime_seconds: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Scan all TOON files in a directory.

        Stops gracefully before *max_runtime_seconds* elapses so that partial
        results can be saved and the GitHub Actions job is not hard-cancelled.

        Args:
            toon_seeds_dir: Directory containing TOON files.
            rate_limit_per_second: Max requests per second per country.
            skip_recently_validated_days: Skip URLs confirmed reachable by any
                scanner within this many days (0 = always re-validate).
            max_runtime_seconds: Shared runtime budget in seconds.  The job
                will not *start* a new country when fewer than 5 minutes remain,
                and will pass the remaining budget into each country scan so
                that even a large country stops gracefully mid-way if needed.
                ``None`` means no limit.

        Returns:
            List of scan statistics for each country
        """
        all_stats = []

        # Find all .toon files
        toon_files = list(toon_seeds_dir.glob("*.toon"))

        print(f"Found {len(toon_files)} TOON files to process")

        start_time = time.monotonic()
        # Reserve this many seconds at the end so we don't attempt to start a
        # fresh country scan when there is not enough time left.
        _country_start_buffer = 5 * 60  # 5 minutes

        for toon_path in sorted(toon_files):
            # Extract country code from filename using utility function
            country_code = country_filename_to_code(toon_path.stem)

            # Check whether enough time remains to begin a new country.
            if max_runtime_seconds is not None:
                elapsed = time.monotonic() - start_time
                remaining = max_runtime_seconds - elapsed
                if remaining < _country_start_buffer:
                    print(
                        f"⏱️  Time budget near limit "
                        f"({elapsed / 60:.1f}m elapsed, "
                        f"{remaining / 60:.1f}m remaining) "
                        f"— skipping remaining countries starting with {country_code}"
                    )
                    break

            try:
                stats = await self.scan_country(
                    country_code,
                    toon_path,
                    rate_limit_per_second,
                    skip_recently_validated_days=skip_recently_validated_days,
                    max_runtime_seconds=max_runtime_seconds,
                    start_time=start_time,
                )
                all_stats.append(stats)
            except Exception as e:
                print(f"Error scanning {toon_path}: {e}")
                all_stats.append({
                    "country_code": country_code,
                    "error": str(e),
                })

        return all_stats
