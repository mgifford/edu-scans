"""Lighthouse scanner job for processing TOON files."""

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
from src.services.lighthouse_scanner import LighthouseScanResult, LighthouseScanner
from src.storage.schema import initialize_schema


class LighthouseScannerJob:
    """Scanner job that runs Google Lighthouse audits from TOON file URLs."""

    def __init__(
        self,
        settings: Settings,
        lighthouse_path: str = "lighthouse",
        only_categories: list[str] | None = None,
        throttling_method: str | None = None,
    ):
        self.settings = settings
        self.scanner = LighthouseScanner(
            timeout_seconds=settings.crawl_timeout_seconds * 6,  # Lighthouse is slow
            lighthouse_path=lighthouse_path,
            only_categories=only_categories,
            throttling_method=throttling_method,
        )
        self.db_path = initialize_schema(settings.metadata_db_url)

    def _load_toon_file(self, toon_path: Path) -> dict:
        """Load and parse a TOON file."""
        with toon_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _extract_urls_from_toon(self, toon_data: dict) -> List[str]:
        """Extract all unique page URLs from TOON data structure.

        Deduplicates URLs that appear in multiple domain entries or
        multiple times in the same domain's pages array.
        """
        urls = []
        seen = set()
        for domain_entry in toon_data.get("domains", []):
            for page in domain_entry.get("pages", []):
                url = page.get("url")
                if url and url not in seen:
                    urls.append(url)
                    seen.add(url)
        return urls

    def _list_effective_toon_files(self, toon_seeds_dir: Path) -> list[Path]:
        """Return TOON files preferring ``*_subdomains.toon`` over base seeds."""
        all_toon_files = sorted(toon_seeds_dir.glob("*.toon"))
        stems_with_subdomains: set[str] = {
            f.stem[: -len("_subdomains")]
            for f in all_toon_files
            if f.stem.endswith("_subdomains")
        }
        return [
            f for f in all_toon_files
            if f.stem.endswith("_subdomains") or f.stem not in stems_with_subdomains
        ]

    def _get_last_scan_time_per_country(self) -> Dict[str, str]:
        """Return the latest ``scanned_at`` timestamp per country code.

        Used to sort countries by how recently they were scanned so that
        never-scanned or least-recently-scanned countries are prioritised at
        the start of each run.

        Returns:
            Mapping of country_code → ISO-8601 string of the most recent scan.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                SELECT country_code, MAX(scanned_at)
                FROM url_lighthouse_results
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
        """Return URLs already scanned by Lighthouse within the last N days.

        Only successful scans (no error_message) count as "recently scanned"
        so that failed URLs are always retried.

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
                FROM url_lighthouse_results
                WHERE country_code = ?
                  AND error_message IS NULL
                  AND scanned_at >= ?
                """,
                (country_code, cutoff),
            )
            return {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()

    def _build_scan_stats(
        self,
        scan_id: str,
        country_code: str,
        total_urls: int,
        urls_skipped: int,
        output_path: Path,
        scan_results: Dict[str, LighthouseScanResult] | None = None,
    ) -> Dict[str, Any]:
        """Build the scan statistics dictionary returned by :meth:`scan_country`.

        Extracts success/error counts and average scores from *scan_results*.
        When *scan_results* is ``None`` (all URLs were recently-scanned and
        skipped) the counts and averages default to zero / ``None``.
        """
        if scan_results is None:
            return {
                "scan_id": scan_id,
                "country_code": country_code,
                "total_urls": total_urls,
                "urls_scanned": 0,
                "urls_skipped_recently_scanned": urls_skipped,
                "is_complete": True,
                "success_count": 0,
                "error_count": 0,
                "avg_performance": None,
                "avg_accessibility": None,
                "avg_best_practices": None,
                "avg_seo": None,
                "output_path": str(output_path),
            }

        scanned_count = len(scan_results)
        is_complete = scanned_count == (total_urls - urls_skipped)
        success_count = sum(1 for r in scan_results.values() if not r.error_message)

        def _avg(attr: str) -> float | None:
            vals = [
                getattr(r, attr)
                for r in scan_results.values()
                if not r.error_message and getattr(r, attr) is not None
            ]
            return round(sum(vals) / len(vals), 3) if vals else None

        return {
            "scan_id": scan_id,
            "country_code": country_code,
            "total_urls": total_urls,
            "urls_scanned": scanned_count,
            "urls_skipped_recently_scanned": urls_skipped,
            "is_complete": is_complete,
            "success_count": success_count,
            "error_count": scanned_count - success_count,
            "avg_performance": _avg("performance_score"),
            "avg_accessibility": _avg("accessibility_score"),
            "avg_best_practices": _avg("best_practices_score"),
            "avg_seo": _avg("seo_score"),
            "output_path": str(output_path),
        }

    def _save_lighthouse_results(
        self,
        results: List[LighthouseScanResult],
        country_code: str,
        scan_id: str,
    ) -> None:
        """Persist Lighthouse scan results to the database."""
        conn = sqlite3.connect(self.db_path)
        try:
            for result in results:
                conn.execute(
                    """
                    INSERT INTO url_lighthouse_results
                    (url, country_code, scan_id,
                     performance_score, accessibility_score,
                     best_practices_score, seo_score, pwa_score,
                     error_message, scanned_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.url,
                        country_code,
                        scan_id,
                        result.performance_score,
                        result.accessibility_score,
                        result.best_practices_score,
                        result.seo_score,
                        result.pwa_score,
                        result.error_message,
                        result.scanned_at,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def _update_toon_with_lighthouse(
        self,
        toon_data: dict,
        scan_results: Dict[str, LighthouseScanResult],
    ) -> dict:
        """
        Annotate TOON pages with Lighthouse audit scores.

        Each page entry gains a ``lighthouse`` field (dict) with the five
        category scores and an optional ``lighthouse_error`` field when the
        audit failed for that URL.
        """
        for domain_entry in toon_data.get("domains", []):
            for page in domain_entry.get("pages", []):
                url = page.get("url")
                if url not in scan_results:
                    continue

                result = scan_results[url]
                if result.error_message:
                    page["lighthouse_error"] = result.error_message
                else:
                    page["lighthouse"] = {
                        "performance": result.performance_score,
                        "accessibility": result.accessibility_score,
                        "best_practices": result.best_practices_score,
                        "seo": result.seo_score,
                        "pwa": result.pwa_score,
                    }

        return toon_data

    async def scan_country(
        self,
        country_code: str,
        toon_path: Path,
        rate_limit_per_second: float = 0.2,
        max_runtime_seconds: Optional[float] = None,
        start_time: Optional[float] = None,
        skip_recently_scanned_days: int = 0,
        concurrency: int = 1,
        max_urls: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Run Lighthouse audits for all URLs in a country's TOON file.

        Results are persisted to the database incrementally as each URL is
        scanned, so partial results are preserved even if the job is stopped
        early due to a timeout.

        Args:
            country_code: Country code (e.g. FRANCE).
            toon_path: Path to the TOON seed file.
            rate_limit_per_second: Maximum Lighthouse runs per second.
            max_runtime_seconds: Shared runtime budget in seconds measured
                from *start_time*.  When the remaining budget drops below
                60 seconds scanning stops gracefully.  ``None`` = no limit.
            start_time: ``time.monotonic()`` value from the start of the
                overall job.  ``None`` means a fresh clock for this country.
            skip_recently_scanned_days: Skip URLs that were already
                successfully scanned within the last N days.  0 = always
                re-scan all URLs.
            concurrency: Maximum number of parallel Lighthouse processes.
                Defaults to 1 (sequential).
            max_urls: Maximum number of URLs to scan in a single run.  When
                provided the URL list is capped at this value (after
                skip_recently_scanned_days filtering) so each run completes
                in a predictable time.  ``None`` = no limit.

        Returns:
            Scan statistics dictionary.
        """
        scan_id = (
            f"lighthouse-{country_code}-"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S%f')}-"
            f"{uuid4().hex[:8]}"
        )

        print(f"Starting Lighthouse scan {scan_id} for {country_code}")
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
        if max_urls is not None and max_urls > 0 and len(urls) > max_urls:
            print(
                f"Limiting scan to {max_urls}/{len(urls)} URLs "
                f"(--max-urls cap applied)"
            )
            urls = urls[:max_urls]

        if not urls:
            print(f"All {len(all_urls)} URLs were recently scanned — nothing to do")
            output_path = (
                toon_path.parent / f"{toon_path.stem}_lighthouse{toon_path.suffix}"
            )
            return self._build_scan_stats(
                scan_id, country_code, len(all_urls), len(recently_scanned), output_path
            )

        _start = start_time if start_time is not None else time.monotonic()

        def _save_result(result: LighthouseScanResult) -> None:
            """Persist a single scan result immediately after it is computed."""
            self._save_lighthouse_results([result], country_code, scan_id)

        scan_results = await self.scanner.scan_urls_batch(
            urls,
            rate_limit_per_second=rate_limit_per_second,
            max_runtime_seconds=max_runtime_seconds,
            start_time=_start,
            on_result=_save_result,
            concurrency=concurrency,
        )

        updated_toon = self._update_toon_with_lighthouse(toon_data, scan_results)

        output_path = (
            toon_path.parent / f"{toon_path.stem}_lighthouse{toon_path.suffix}"
        )
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(updated_toon, f, indent=2, ensure_ascii=False)

        scanned_count = len(scan_results)
        is_complete = scanned_count == len(urls)
        if is_complete:
            print(f"Saved Lighthouse-annotated TOON to: {output_path}")
        else:
            print(
                f"Saved partial Lighthouse-annotated TOON to: {output_path} "
                f"({scanned_count}/{len(urls)} URLs scanned)"
            )

        stats = self._build_scan_stats(
            scan_id, country_code, len(all_urls), len(recently_scanned),
            output_path, scan_results
        )

        print(f"\nLighthouse scan {'complete' if is_complete else 'partial'}:")
        print(f"  Scanned:          {scanned_count}/{len(urls)}")
        if recently_scanned:
            print(f"  Skipped (recently scanned): {len(recently_scanned)}")
        print(f"  Success:          {stats['success_count']}")
        print(f"  Errors:           {stats['error_count']}")
        if stats["avg_accessibility"] is not None:
            print(f"  Avg accessibility: {stats['avg_accessibility'] * 100:.1f}")
        if stats["avg_performance"] is not None:
            print(f"  Avg performance:   {stats['avg_performance'] * 100:.1f}")

        return stats

    async def scan_all_countries(
        self,
        toon_seeds_dir: Path,
        rate_limit_per_second: float = 0.2,
        max_runtime_seconds: Optional[float] = None,
        skip_recently_scanned_days: int = 0,
        concurrency: int = 1,
        max_urls: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Run Lighthouse audits for all TOON files in a directory.

        Stops gracefully before *max_runtime_seconds* elapses so that
        partial results can be saved and the GitHub Actions job is not
        hard-cancelled.

        Args:
            toon_seeds_dir: Directory containing TOON seed files.
            rate_limit_per_second: Maximum Lighthouse runs per second.
            max_runtime_seconds: Shared runtime budget in seconds.  The job
                will not *start* a new country when fewer than 5 minutes
                remain.  ``None`` means no limit.
            skip_recently_scanned_days: Skip URLs already scanned within the
                last N days.  0 = always re-scan all URLs.  Countries not
                scanned recently are prioritised when this is set.
            concurrency: Maximum number of parallel Lighthouse processes per
                country.  Defaults to 1 (sequential).
            max_urls: Maximum number of URLs to scan per country per run.
                ``None`` = no limit.  See :meth:`scan_country`.

        Returns:
            List of scan statistics for each country processed.
        """
        all_stats = []

        # When skipping recently-scanned URLs, sort countries so those not
        # scanned recently (or never scanned) come first.
        toon_files = self._list_effective_toon_files(toon_seeds_dir)
        if skip_recently_scanned_days > 0:
            last_scan_times = self._get_last_scan_time_per_country()
            toon_files = sorted(
                toon_files,
                key=lambda p: (
                    last_scan_times.get(country_filename_to_code(p.stem), ""),
                    p.stem,
                ),
            )

        print(f"Found {len(toon_files)} TOON files to process")

        start_time = time.monotonic()
        _country_start_buffer = 5 * 60  # 5 minutes

        for toon_path in toon_files:
            country_code = country_filename_to_code(toon_path.stem)

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
                    concurrency=concurrency,
                    max_urls=max_urls,
                )
                all_stats.append(stats)
            except Exception as exc:
                print(f"Error scanning {toon_path}: {exc}")
                all_stats.append({"country_code": country_code, "error": str(exc)})

        return all_stats
