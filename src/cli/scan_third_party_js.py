"""CLI entry point for third-party JavaScript scanner."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from src.jobs.third_party_js_scanner import ThirdPartyJsScannerJob
from src.lib.country_utils import country_code_to_filename
from src.lib.settings import load_settings


def main():
    """Main CLI entry point for third-party JavaScript scanning."""
    parser = argparse.ArgumentParser(
        description=(
            "Scan government website pages for third-party JavaScript resources. "
            "Identifies known services (e.g. Google Analytics, Tag Manager, "
            "Facebook Pixel) and extracts version numbers for security tracking. "
            "Produces an annotated TOON file and persists results to the metadata "
            "database."
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
        default=Path("data/toon-seeds/countries"),
    )
    parser.add_argument(
        "--rate-limit",
        help="Maximum requests per second (default: 1.0 for polite crawling)",
        type=float,
        default=1.0,
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

    args = parser.parse_args()

    if not args.all and not args.country:
        print("Error: Must specify either --country or --all")
        parser.print_help()
        sys.exit(1)

    if not args.toon_dir.exists():
        print(f"Error: TOON directory not found: {args.toon_dir}")
        sys.exit(1)

    max_runtime_seconds = args.max_runtime * 60 if args.max_runtime > 0 else None

    settings = load_settings()
    job = ThirdPartyJsScannerJob(settings)

    try:
        if args.all:
            if max_runtime_seconds is not None:
                print(
                    f"Scanning all countries for third-party JavaScript "
                    f"(max runtime: {args.max_runtime} minutes)..."
                )
            else:
                print("Scanning all countries for third-party JavaScript...")
            all_stats = asyncio.run(
                job.scan_all_countries(
                    args.toon_dir,
                    rate_limit_per_second=args.rate_limit,
                    max_runtime_seconds=max_runtime_seconds,
                )
            )

            print("\n" + "=" * 80)
            print("THIRD-PARTY JS SCAN SUMMARY")
            print("=" * 80)
            for country_stats in all_stats:
                if "error" in country_stats:
                    print(
                        f"{country_stats['country_code']}: "
                        f"ERROR - {country_stats['error']}"
                    )
                else:
                    complete_flag = "" if country_stats.get("is_complete", True) else " (partial)"
                    print(
                        f"{country_stats['country_code']}{complete_flag}: "
                        f"{country_stats['urls_scanned']} scanned, "
                        f"{country_stats['urls_with_scripts']} with 3rd-party scripts, "
                        f"{country_stats['identified_services']} identified services"
                    )
        else:
            country_code = args.country.upper()
            toon_file = args.toon_dir / f"{country_code_to_filename(country_code)}.toon"

            if not toon_file.exists():
                print(
                    f"Error: TOON file not found: {toon_file}\n"
                    f"Expected a file named '{toon_file.name}' in {args.toon_dir}"
                )
                sys.exit(1)

            print(f"Scanning {country_code} for third-party JavaScript...")
            stats = asyncio.run(
                job.scan_country(
                    country_code,
                    toon_file,
                    rate_limit_per_second=args.rate_limit,
                    max_runtime_seconds=max_runtime_seconds,
                )
            )

            print("\n" + "=" * 80)
            print("THIRD-PARTY JS SCAN COMPLETE")
            print("=" * 80)
            print(f"Scan ID:               {stats['scan_id']}")
            print(f"Total URLs:            {stats['total_urls']}")
            print(f"Scanned:               {stats['urls_scanned']}")
            print(f"Complete:              {'Yes' if stats.get('is_complete', True) else 'No (stopped early)'}")
            print(f"Reachable:             {stats['reachable_count']}")
            print(f"Unreachable:           {stats['unreachable_count']}")
            print(f"URLs with scripts:     {stats['urls_with_scripts']}")
            print(f"Total scripts found:   {stats['total_scripts']}")
            print(f"Identified services:   {stats['identified_services']}")
            if stats["service_counts"]:
                print("Service breakdown:")
                for svc, cnt in sorted(
                    stats["service_counts"].items(), key=lambda x: -x[1]
                ):
                    print(f"  {svc}: {cnt}")
            print(f"Output:                {stats['output_path']}")

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
