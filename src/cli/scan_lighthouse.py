"""CLI entry point for Google Lighthouse scanner."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from src.jobs.lighthouse_scanner import LighthouseScannerJob
from src.lib.country_utils import country_code_to_filename
from src.lib.settings import load_settings


def main():
    """Main CLI entry point for Lighthouse scanning."""
    parser = argparse.ArgumentParser(
        description=(
            "Run Google Lighthouse audits on government websites via TOON files. "
            "Requires 'lighthouse' CLI (npm install -g lighthouse) and Chrome/Chromium."
        )
    )
    parser.add_argument(
        "--country",
        help="Specific country code to scan (e.g., ICELAND, FRANCE)",
        type=str,
    )
    parser.add_argument(
        "--toon-dir",
        help="Directory containing TOON files",
        type=Path,
        default=Path("data/toon-seeds"),
    )
    parser.add_argument(
        "--rate-limit",
        help="Maximum Lighthouse runs per second (default: 0.2 = one every 5 s)",
        type=float,
        default=0.2,
    )
    parser.add_argument(
        "--all",
        help="Scan all countries",
        action="store_true",
    )
    parser.add_argument(
        "--max-runtime",
        help=(
            "Maximum runtime in minutes before stopping gracefully. "
            "0 = no limit (default).  For --all mode in GitHub Actions set "
            "this to ~10 minutes less than the workflow timeout-minutes value "
            "so the job can finish cleanly and upload its artifacts."
        ),
        type=int,
        default=0,
        dest="max_runtime",
    )
    parser.add_argument(
        "--lighthouse-path",
        help="Path to the lighthouse binary (default: 'lighthouse' from PATH)",
        type=str,
        default="lighthouse",
    )
    parser.add_argument(
        "--concurrency",
        help=(
            "Maximum number of Lighthouse processes to run in parallel "
            "(default: 1 = sequential).  Values > 1 improve throughput on "
            "multi-core CI runners."
        ),
        type=int,
        default=1,
    )
    parser.add_argument(
        "--skip-recently-scanned-days",
        help=(
            "Skip URLs that were successfully scanned within the last N days "
            "(default: 0 = always re-scan).  Set to 30 for a monthly refresh "
            "cycle.  Countries not scanned recently are prioritised."
        ),
        type=int,
        default=0,
        dest="skip_recently_scanned_days",
    )
    parser.add_argument(
        "--only-categories",
        help=(
            "Comma-separated list of Lighthouse categories to run "
            "(e.g. 'performance,accessibility,best-practices,seo'). "
            "Omitting 'pwa' saves time on government sites.  "
            "Default: run all categories."
        ),
        type=str,
        default=None,
        dest="only_categories",
    )
    parser.add_argument(
        "--throttling-method",
        help=(
            "Lighthouse throttling method.  Use 'provided' to skip simulated "
            "slow-network throttling (faster for server-to-server audits). "
            "Default: lighthouse's own default (devtools)."
        ),
        type=str,
        default=None,
        dest="throttling_method",
    )

    args = parser.parse_args()

    if not args.all and not args.country:
        print("Error: Must specify either --country or --all")
        parser.print_help()
        sys.exit(1)

    if not args.toon_dir.exists():
        print(f"Error: TOON directory not found: {args.toon_dir}")
        sys.exit(1)

    only_categories = (
        [c.strip() for c in args.only_categories.split(",") if c.strip()]
        if args.only_categories
        else None
    )

    settings = load_settings()
    job = LighthouseScannerJob(
        settings,
        lighthouse_path=args.lighthouse_path,
        only_categories=only_categories,
        throttling_method=args.throttling_method,
    )

    max_runtime_seconds = args.max_runtime * 60 if args.max_runtime > 0 else None

    try:
        if args.all:
            if max_runtime_seconds is not None:
                print(
                    f"Running Lighthouse scans for all countries "
                    f"(max runtime: {args.max_runtime} minutes)..."
                )
            else:
                print("Running Lighthouse scans for all countries...")
            all_stats = asyncio.run(
                job.scan_all_countries(
                    args.toon_dir,
                    rate_limit_per_second=args.rate_limit,
                    max_runtime_seconds=max_runtime_seconds,
                    skip_recently_scanned_days=args.skip_recently_scanned_days,
                    concurrency=args.concurrency,
                )
            )

            print("\n" + "=" * 80)
            print("LIGHTHOUSE SCAN SUMMARY")
            print("=" * 80)
            for country_stats in all_stats:
                if "error" in country_stats:
                    print(
                        f"{country_stats['country_code']}: "
                        f"ERROR - {country_stats['error']}"
                    )
                else:
                    complete_flag = "" if country_stats.get("is_complete", True) else " (partial)"
                    avg_a11y = country_stats.get("avg_accessibility")
                    a11y_str = (
                        f", avg accessibility={avg_a11y * 100:.1f}"
                        if avg_a11y is not None
                        else ""
                    )
                    print(
                        f"{country_stats['country_code']}{complete_flag}: "
                        f"{country_stats['success_count']} scanned, "
                        f"{country_stats['error_count']} errors"
                        f"{a11y_str}"
                    )
        else:
            country_code = args.country.upper()
            toon_file = args.toon_dir / f"{country_code_to_filename(country_code)}.toon"

            if not toon_file.exists():
                print(f"Error: TOON file not found: {toon_file}")
                sys.exit(1)

            print(f"Running Lighthouse scan for {country_code}...")
            stats = asyncio.run(
                job.scan_country(
                    country_code,
                    toon_file,
                    rate_limit_per_second=args.rate_limit,
                    max_runtime_seconds=max_runtime_seconds,
                    skip_recently_scanned_days=args.skip_recently_scanned_days,
                    concurrency=args.concurrency,
                )
            )

            print("\n" + "=" * 80)
            print("LIGHTHOUSE SCAN COMPLETE")
            print("=" * 80)
            print(f"Scan ID:              {stats['scan_id']}")
            print(f"Total URLs:           {stats['total_urls']}")
            print(f"Scanned:              {stats['urls_scanned']}")
            print(f"Complete:             {'Yes' if stats.get('is_complete', True) else 'No (stopped early)'}")
            print(f"Success:              {stats['success_count']}")
            print(f"Errors:               {stats['error_count']}")
            if stats.get("avg_performance") is not None:
                print(f"Avg Performance:      {stats['avg_performance'] * 100:.1f}")
            if stats.get("avg_accessibility") is not None:
                print(f"Avg Accessibility:    {stats['avg_accessibility'] * 100:.1f}")
            if stats.get("avg_best_practices") is not None:
                print(f"Avg Best Practices:   {stats['avg_best_practices'] * 100:.1f}")
            if stats.get("avg_seo") is not None:
                print(f"Avg SEO:              {stats['avg_seo'] * 100:.1f}")
            print(f"Output:               {stats['output_path']}")

    except KeyboardInterrupt:
        print("\nScan interrupted by user")
        sys.exit(1)
    except Exception as exc:
        print(f"Error: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
