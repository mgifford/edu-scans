"""Technology scanner job for processing TOON files."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from src.lib.country_utils import country_filename_to_code
from src.lib.settings import Settings
from src.services.tech_detector import TechDetectionResult, TechDetector
from src.storage.schema import initialize_schema


class TechScanner:
    """Scanner for detecting technologies from TOON file URLs."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.detector = TechDetector(
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

    def _get_last_scan_time_per_country(self) -> Dict[str, str]:
        """Return the latest ``scanned_at`` timestamp per country code.

        Used to sort countries by how recently they were scanned so that
        never-scanned or least-recently-scanned countries are prioritised at
        the start of each run.  Countries absent from the result have never
        been scanned by this scanner.

        Returns:
            Mapping of country_code → ISO-8601 string of the most recent scan.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                SELECT country_code, MAX(scanned_at)
                FROM url_tech_results
                GROUP BY country_code
                """
            )
            return {
                row[0]: row[1]
                for row in cursor.fetchall()
                if row[1] is not None
            }
        finally:
            conn.close()

    def _get_recently_scanned_urls(
        self, country_code: str, within_days: int
    ) -> Set[str]:
        """
        Return URLs already scanned by the technology scanner within the
        last ``within_days`` days.

        This is used to skip URLs that were recently scanned so each run can
        focus on stale or previously-unscanned pages rather than repeating
        work done in an earlier run.

        Args:
            country_code: Country to look up.
            within_days: Consider results from the last N days.

        Returns:
            Set of URL strings that do not need re-scanning.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=within_days)
        ).isoformat()

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                SELECT DISTINCT url
                FROM url_tech_results
                WHERE country_code = ?
                  AND scanned_at >= ?
                """,
                (country_code, cutoff),
            )
            return {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()

    def _save_tech_results(
        self,
        results: List[TechDetectionResult],
        country_code: str,
        scan_id: str,
    ) -> None:
        """Persist technology detection results to the database."""
        conn = sqlite3.connect(self.db_path)
        try:
            for result in results:
                conn.execute(
                    """
                    INSERT INTO url_tech_results
                    (url, country_code, scan_id, technologies, error_message, scanned_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.url,
                        country_code,
                        scan_id,
                        json.dumps(result.technologies),
                        result.error_message,
                        result.scanned_at,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def _update_toon_with_tech(
        self,
        toon_data: dict,
        tech_results: Dict[str, TechDetectionResult],
    ) -> dict:
        """
        Annotate TOON pages with detected technologies.

        Each page entry gains a ``technologies`` field (dict) and an optional
        ``tech_error`` field when detection failed for that URL.
        """
        for domain_entry in toon_data.get("domains", []):
            for page in domain_entry.get("pages", []):
                url = page.get("url")
                if url not in tech_results:
                    continue

                result = tech_results[url]
                if result.error_message:
                    page["tech_error"] = result.error_message
                else:
                    page["technologies"] = result.technologies

        return toon_data

    async def scan_country(
        self,
        country_code: str,
        toon_path: Path,
        rate_limit_per_second: float = 2.0,
        max_runtime_seconds: Optional[float] = None,
        start_time: Optional[float] = None,
        skip_recently_scanned_days: int = 0,
    ) -> Dict[str, Any]:
        """
        Detect technologies for all URLs in a country's TOON file.

        Results are persisted to the database incrementally as each URL is
        scanned, so partial results are preserved even if the job is stopped
        early due to a timeout.

        Args:
            country_code: Country code (e.g. FRANCE).
            toon_path: Path to the TOON seed file.
            rate_limit_per_second: Maximum HTTP requests per second.
            max_runtime_seconds: Shared runtime budget in seconds measured
                from *start_time*.  When the remaining budget drops below
                60 seconds scanning stops gracefully.  ``None`` = no limit.
            start_time: ``time.monotonic()`` value from the start of the
                overall job.  ``None`` means a fresh clock for this country.
            skip_recently_scanned_days: Skip URLs that were already scanned
                by this scanner within the last N days.  0 = always re-scan.
                Setting this to 7 makes each run focus on stale/new URLs so
                the full domain list is covered progressively across runs.

        Returns:
            Scan statistics dictionary.
        """
        scan_id = (
            f"tech-{country_code}-"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S%f')}-"
            f"{uuid4().hex[:8]}"
        )

        print(f"Starting tech scan {scan_id} for {country_code}")
        print(f"Loading TOON file: {toon_path}")

        toon_data = self._load_toon_file(toon_path)
        all_urls = self._extract_urls_from_toon(toon_data)

        print(f"Found {len(all_urls)} URLs to scan")

        recently_scanned: Set[str] = set()
        if skip_recently_scanned_days > 0:
            recently_scanned = self._get_recently_scanned_urls(
                country_code, within_days=skip_recently_scanned_days
            )
            if recently_scanned:
                print(
                    f"Skipping {len(recently_scanned)} URLs already scanned "
                    f"within the last {skip_recently_scanned_days} day(s)"
                )

        urls = [u for u in all_urls if u not in recently_scanned]
        if not urls:
            print(f"All {len(all_urls)} URLs were recently scanned — nothing to do")
            return {
                "scan_id": scan_id,
                "country_code": country_code,
                "total_urls": len(all_urls),
                "urls_scanned": 0,
                "urls_skipped_recently_scanned": len(recently_scanned),
                "is_complete": True,
                "success_count": 0,
                "error_count": 0,
                "tech_detected_count": 0,
                "output_path": str(
                    toon_path.parent / f"{toon_path.stem}_tech{toon_path.suffix}"
                ),
            }

        # Use the caller's start_time so the budget is shared across countries.
        _start = start_time if start_time is not None else time.monotonic()

        def _save_result(result: TechDetectionResult) -> None:
            """Persist a single scan result immediately after it is computed."""
            self._save_tech_results([result], country_code, scan_id)

        tech_results = await self.detector.detect_urls_batch(
            urls,
            rate_limit_per_second=rate_limit_per_second,
            max_runtime_seconds=max_runtime_seconds,
            start_time=_start,
            on_result=_save_result,
        )

        # Note: each result was already written to the DB via _save_result;
        # no further bulk save is needed here.

        updated_toon = self._update_toon_with_tech(toon_data, tech_results)

        output_path = (
            toon_path.parent / f"{toon_path.stem}_tech{toon_path.suffix}"
        )
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(updated_toon, f, indent=2, ensure_ascii=False)

        scanned_count = len(tech_results)
        is_complete = scanned_count == len(urls)
        if is_complete:
            print(f"Saved tech-annotated TOON to: {output_path}")
        else:
            print(
                f"Saved partial tech-annotated TOON to: {output_path} "
                f"({scanned_count}/{len(urls)} URLs scanned)"
            )

        success_count = sum(
            1 for r in tech_results.values() if not r.error_message
        )
        error_count = scanned_count - success_count
        tech_detected_count = sum(
            1 for r in tech_results.values() if r.technologies
        )

        stats = {
            "scan_id": scan_id,
            "country_code": country_code,
            "total_urls": len(all_urls),
            "urls_scanned": scanned_count,
            "urls_skipped_recently_scanned": len(recently_scanned),
            "is_complete": is_complete,
            "success_count": success_count,
            "error_count": error_count,
            "tech_detected_count": tech_detected_count,
            "output_path": str(output_path),
        }

        print(f"\nTech scan {'complete' if is_complete else 'partial'}:")
        print(f"  Scanned:   {scanned_count}/{len(urls)}")
        if recently_scanned:
            print(f"  Skipped (recently scanned): {len(recently_scanned)}")
        print(f"  Success:   {success_count}")
        print(f"  Errors:    {error_count}")
        print(f"  With tech: {tech_detected_count}")

        return stats

    async def scan_all_countries(
        self,
        toon_seeds_dir: Path,
        rate_limit_per_second: float = 2.0,
        max_runtime_seconds: Optional[float] = None,
        skip_recently_scanned_days: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Scan all TOON files in a directory for technologies.

        Stops gracefully before *max_runtime_seconds* elapses so that partial
        results can be saved and the GitHub Actions job is not hard-cancelled.

        Args:
            toon_seeds_dir: Directory containing TOON seed files.
            rate_limit_per_second: Maximum requests per second per country.
            max_runtime_seconds: Shared runtime budget in seconds.  The job
                will not *start* a new country when fewer than 5 minutes remain,
                and will pass the remaining budget into each country scan so
                that even a large country stops gracefully mid-way if needed.
                ``None`` means no limit.
            skip_recently_scanned_days: Skip URLs already scanned within the
                last N days.  0 = always re-scan all URLs.  Setting this to 7
                means each run only scans URLs that haven't been seen recently,
                allowing the full list to be covered progressively across runs.

        Returns:
            List of scan statistics for each country.
        """
        all_stats = []

        # When skipping recently-scanned URLs, sort countries so those not
        # scanned recently (or never scanned) come first.  This prevents the
        # scanner from repeatedly revisiting alphabetically early countries
        # (Austria, Belgium, …) while later countries never get processed.
        if skip_recently_scanned_days > 0:
            last_scan_times = self._get_last_scan_time_per_country()
            toon_files = sorted(
                toon_seeds_dir.glob("*.toon"),
                key=lambda p: (
                    last_scan_times.get(country_filename_to_code(p.stem), ""),
                    p.stem,
                ),
            )
        else:
            toon_files = sorted(toon_seeds_dir.glob("*.toon"))

        print(f"Found {len(toon_files)} TOON files to process")

        start_time = time.monotonic()
        # Reserve this many seconds at the end so we don't attempt to start a
        # fresh country scan when there is not enough time left.
        _country_start_buffer = 5 * 60  # 5 minutes

        for toon_path in toon_files:
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
                    max_runtime_seconds=max_runtime_seconds,
                    start_time=start_time,
                    skip_recently_scanned_days=skip_recently_scanned_days,
                )
                all_stats.append(stats)
            except Exception as exc:
                print(f"Error scanning {toon_path}: {exc}")
                all_stats.append({"country_code": country_code, "error": str(exc)})

        return all_stats
