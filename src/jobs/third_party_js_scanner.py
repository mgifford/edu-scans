"""Third-party JavaScript scanner job for processing TOON files."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from src.lib.country_utils import country_filename_to_code
from src.lib.settings import Settings
from src.services.third_party_js_scanner import ThirdPartyJsScanResult, ThirdPartyJsScanner
from src.storage.schema import initialize_schema


class ThirdPartyJsScannerJob:
    """Scanner job for detecting third-party JavaScript from TOON file URLs."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.scanner = ThirdPartyJsScanner(
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

    def _save_results(
        self,
        results: List[ThirdPartyJsScanResult],
        country_code: str,
        scan_id: str,
    ) -> None:
        """Persist third-party JS scan results to the database."""
        conn = sqlite3.connect(self.db_path)
        try:
            for result in results:
                scripts_json = json.dumps(
                    [asdict(s) for s in result.scripts]
                )
                conn.execute(
                    """
                    INSERT INTO url_third_party_js_results
                    (url, country_code, scan_id, is_reachable,
                     scripts, error_message, scanned_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.url,
                        country_code,
                        scan_id,
                        1 if result.is_reachable else 0,
                        scripts_json,
                        result.error_message,
                        result.scanned_at,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def _update_toon_with_third_party_js(
        self,
        toon_data: dict,
        scan_results: Dict[str, ThirdPartyJsScanResult],
    ) -> dict:
        """
        Annotate TOON pages with detected third-party JS resources.

        Each page entry gains a ``third_party_js`` field (list of script
        dicts) and an optional ``third_party_js_error`` field when scanning
        failed for that URL.
        """
        for domain_entry in toon_data.get("domains", []):
            for page in domain_entry.get("pages", []):
                url = page.get("url")
                if url not in scan_results:
                    continue

                result = scan_results[url]
                if result.error_message and not result.is_reachable:
                    page["third_party_js_error"] = result.error_message
                else:
                    page["third_party_js"] = [asdict(s) for s in result.scripts]

        return toon_data

    async def scan_country(
        self,
        country_code: str,
        toon_path: Path,
        rate_limit_per_second: float = 2.0,
        max_runtime_seconds: Optional[float] = None,
        start_time: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Scan all URLs in a country's TOON file for third-party JavaScript.

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

        Returns:
            Scan statistics dictionary.
        """
        scan_id = (
            f"3pjs-{country_code}-"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S%f')}-"
            f"{uuid4().hex[:8]}"
        )

        print(f"Starting third-party JS scan {scan_id} for {country_code}")
        print(f"Loading TOON file: {toon_path}")

        toon_data = self._load_toon_file(toon_path)
        urls = self._extract_urls_from_toon(toon_data)

        print(f"Found {len(urls)} URLs to scan")

        _start = start_time if start_time is not None else time.monotonic()

        def _save_result(result: ThirdPartyJsScanResult) -> None:
            """Persist a single scan result immediately after it is computed."""
            self._save_results([result], country_code, scan_id)

        scan_results = await self.scanner.scan_urls_batch(
            urls,
            rate_limit_per_second=rate_limit_per_second,
            max_runtime_seconds=max_runtime_seconds,
            start_time=_start,
            on_result=_save_result,
        )

        updated_toon = self._update_toon_with_third_party_js(toon_data, scan_results)

        output_path = (
            toon_path.parent / f"{toon_path.stem}_3pjs{toon_path.suffix}"
        )
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(updated_toon, f, indent=2, ensure_ascii=False)

        scanned_count = len(scan_results)
        is_complete = scanned_count == len(urls)
        if is_complete:
            print(f"Saved third-party-JS-annotated TOON to: {output_path}")
        else:
            print(
                f"Saved partial third-party-JS-annotated TOON to: {output_path} "
                f"({scanned_count}/{len(urls)} URLs scanned)"
            )

        reachable_count = sum(1 for r in scan_results.values() if r.is_reachable)
        unreachable_count = scanned_count - reachable_count
        total_scripts = sum(r.third_party_count for r in scan_results.values())
        identified_services = sum(r.known_service_count for r in scan_results.values())
        urls_with_scripts = sum(1 for r in scan_results.values() if r.third_party_count > 0)

        # Aggregate unique services seen across all URLs
        service_counts: Dict[str, int] = {}
        for result in scan_results.values():
            for script in result.scripts:
                if script.service_name:
                    service_counts[script.service_name] = (
                        service_counts.get(script.service_name, 0) + 1
                    )

        stats = {
            "scan_id": scan_id,
            "country_code": country_code,
            "total_urls": len(urls),
            "urls_scanned": scanned_count,
            "is_complete": is_complete,
            "reachable_count": reachable_count,
            "unreachable_count": unreachable_count,
            "total_scripts": total_scripts,
            "identified_services": identified_services,
            "urls_with_scripts": urls_with_scripts,
            "service_counts": service_counts,
            "output_path": str(output_path),
        }

        print(f"\nThird-party JS scan {'complete' if is_complete else 'partial'}:")
        print(f"  Scanned:            {scanned_count}/{len(urls)}")
        print(f"  Reachable:          {reachable_count}")
        print(f"  Unreachable:        {unreachable_count}")
        print(f"  URLs with scripts:  {urls_with_scripts}")
        print(f"  Total scripts:      {total_scripts}")
        print(f"  Identified:         {identified_services}")
        if service_counts:
            print("  Top services:")
            for svc, cnt in sorted(service_counts.items(), key=lambda x: -x[1])[:10]:
                print(f"    {svc}: {cnt}")

        return stats

    async def scan_all_countries(
        self,
        toon_seeds_dir: Path,
        rate_limit_per_second: float = 2.0,
        max_runtime_seconds: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Scan all TOON files in a directory for third-party JavaScript.

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

        Returns:
            List of scan statistics for each country processed.
        """
        all_stats = []
        toon_files = sorted(toon_seeds_dir.glob("*.toon"))

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
                )
                all_stats.append(stats)
            except Exception as exc:
                print(f"Error scanning {toon_path}: {exc}")
                all_stats.append({"country_code": country_code, "error": str(exc)})

        return all_stats
