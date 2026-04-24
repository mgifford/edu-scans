"""CLI entry point for URL validation scanner."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from src.jobs.url_validation_scanner import UrlValidationScanner
from src.lib.country_utils import country_code_to_filename
from src.lib.settings import load_settings


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Validate URLs in government TOON files"
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
        help="Maximum requests per second",
        type=float,
        default=2.0,
    )
    parser.add_argument(
        "--all",
        help="Scan all countries",
        action="store_true",
    )
    parser.add_argument(
        "--max-runtime",
        help=(
            "Maximum runtime in minutes before graceful stop "
            "(for GitHub Actions timeout prevention). Default: no limit."
        ),
        type=int,
        default=None,
        dest="max_runtime",
    )
    parser.add_argument(
        "--skip-recently-validated-days",
        help=(
            "Skip URLs already confirmed reachable by any scanner within this "
            "many days (default: 30). Set to 0 to always re-validate every URL."
        ),
        type=int,
        default=30,
        dest="skip_recently_validated_days",
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.all and not args.country:
        print("Error: Must specify either --country or --all")
        parser.print_help()
        sys.exit(1)

    if not args.toon_dir.exists():
        print(f"Error: TOON directory not found: {args.toon_dir}")
        sys.exit(1)

    max_runtime_seconds = args.max_runtime * 60 if args.max_runtime is not None else None

    # Load settings
    settings = load_settings()
    scanner = UrlValidationScanner(settings)

    # Run scan
    try:
        if args.all:
            print("Scanning all countries...")
            stats = asyncio.run(
                scanner.scan_all_countries(
                    args.toon_dir,
                    rate_limit_per_second=args.rate_limit,
                    skip_recently_validated_days=args.skip_recently_validated_days,
                    max_runtime_seconds=max_runtime_seconds,
                )
            )

            print("\n" + "=" * 80)
            print("SUMMARY")
            print("=" * 80)
            for country_stats in stats:
                if "error" in country_stats:
                    print(f"{country_stats['country_code']}: ERROR - {country_stats['error']}")
                else:
                    complete_flag = "" if country_stats.get("is_complete", True) else " (partial)"
                    print(
                        f"{country_stats['country_code']}: "
                        f"{country_stats['valid_urls']} valid, "
                        f"{country_stats['invalid_urls']} invalid, "
                        f"{country_stats['urls_removed']} removed"
                        f"{complete_flag}"
                    )
        else:
            # Scan specific country
            country_code = args.country.upper()
            # Convert country code to filename format using utility function
            toon_file = args.toon_dir / f"{country_code_to_filename(country_code)}.toon"

            if not toon_file.exists():
                print(f"Error: TOON file not found: {toon_file}")
                sys.exit(1)

            print(f"Scanning {country_code}...")
            stats = asyncio.run(
                scanner.scan_country(
                    country_code,
                    toon_file,
                    rate_limit_per_second=args.rate_limit,
                    skip_recently_validated_days=args.skip_recently_validated_days,
                    max_runtime_seconds=max_runtime_seconds,
                )
            )

            print("\n" + "=" * 80)
            print("SCAN COMPLETE" if stats.get("is_complete", True) else "SCAN PARTIAL")
            print("=" * 80)
            print(f"Scan ID: {stats['scan_id']}")
            print(f"Total URLs: {stats['total_urls']}")
            print(f"Validated: {stats['urls_validated']}")
            if not stats.get("is_complete", True):
                print("  ⚠️  Validation stopped early (time budget reached)")
            print(f"Skipped (failed 2×): {stats['urls_skipped']}")
            recently = stats.get("urls_skipped_recently_confirmed", 0)
            if recently:
                print(f"Skipped (recently confirmed): {recently}")
            print(f"Valid: {stats['valid_urls']}")
            print(f"Invalid: {stats['invalid_urls']}")
            print(f"Redirected: {stats['redirected_urls']}")
            print(f"Removed: {stats['urls_removed']}")
            print(f"Output: {stats['output_path']}")

    except KeyboardInterrupt:
        print("\nScan interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
