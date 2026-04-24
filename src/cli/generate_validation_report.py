"""CLI tool to generate validation reports from the database."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from src.lib.settings import load_settings


def _country_anchor(country_code: str) -> str:
    """Return a stable HTML anchor ID for a country's error section."""
    return "errors-" + country_code.lower().replace("_", "-")


def generate_report(db_path: Path, output_path: Path):
    """Generate a comprehensive validation report from the database."""

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        print("No validation data available yet.")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        # Get latest scan information per country
        cursor = conn.execute("""
            SELECT
                country_code,
                scan_id,
                MAX(validated_at) as latest_validation
            FROM url_validation_results
            GROUP BY country_code
            ORDER BY country_code
        """)
        country_scans = cursor.fetchall()

        if not country_scans:
            with output_path.open("w") as f:
                f.write("# URL Validation Report\n\n")
                f.write("No validation data available yet.\n")
            print(f"Report generated: {output_path}")
            return

        # Collect statistics per country
        country_stats = {}
        error_details = defaultdict(list)

        for scan in country_scans:
            country_code = scan["country_code"]
            scan_id = scan["scan_id"]

            # Get validation statistics for this country
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN is_valid = 1 THEN 1 ELSE 0 END) as valid,
                    SUM(CASE WHEN is_valid = 0 THEN 1 ELSE 0 END) as invalid,
                    SUM(CASE WHEN redirected_to IS NOT NULL THEN 1 ELSE 0 END) as redirected,
                    SUM(CASE WHEN failure_count >= 2 THEN 1 ELSE 0 END) as removed
                FROM url_validation_results
                WHERE country_code = ?
                AND scan_id = ?
            """, (country_code, scan_id))

            stats = cursor.fetchone()
            country_stats[country_code] = {
                "scan_id": scan_id,
                "total": stats["total"] or 0,
                "valid": stats["valid"] or 0,
                "invalid": stats["invalid"] or 0,
                "redirected": stats["redirected"] or 0,
                "removed": stats["removed"] or 0,
                "latest_validation": scan["latest_validation"],
            }

            # Get error details for this country
            cursor = conn.execute("""
                SELECT
                    url,
                    status_code,
                    error_message,
                    failure_count,
                    redirected_to
                FROM url_validation_results
                WHERE country_code = ?
                AND scan_id = ?
                AND is_valid = 0
                ORDER BY failure_count DESC, url
            """, (country_code, scan_id))

            errors = cursor.fetchall()
            if errors:
                error_details[country_code] = [
                    {
                        "url": row["url"],
                        "status_code": row["status_code"],
                        "error_message": row["error_message"],
                        "failure_count": row["failure_count"],
                        "redirected_to": row["redirected_to"],
                    }
                    for row in errors
                ]

        # Generate markdown report
        with output_path.open("w") as f:
            f.write('<a id="url-validation-report"></a>\n\n')
            f.write("# URL Validation Report\n\n")
            f.write(f"**Generated:** {country_scans[0]['latest_validation']}\n\n")

            # Table of contents
            f.write("## Contents\n\n")
            f.write("- [Summary by Country](#summary-by-country)\n")
            if error_details:
                f.write("- [Errors by Country](#errors-by-country)\n")
                for country_code in sorted(error_details.keys()):
                    anchor = _country_anchor(country_code)
                    errors = error_details[country_code]
                    f.write(
                        f"  - [{country_code} ({len(errors)} errors)](#{anchor})\n"
                    )
            f.write("- [Legend](#legend)\n\n")

            # Summary table
            f.write("## Summary by Country\n\n")
            f.write("| Country | Total URLs | Valid | Invalid | Redirected | Removed | Success Rate |\n")
            f.write("|---------|------------|-------|---------|------------|---------|-------------|\n")

            total_all = 0
            valid_all = 0
            invalid_all = 0
            redirected_all = 0
            removed_all = 0

            for country_code in sorted(country_stats.keys()):
                stats = country_stats[country_code]
                total = stats["total"]
                valid = stats["valid"]
                invalid = stats["invalid"]
                redirected = stats["redirected"]
                removed = stats["removed"]

                success_rate = (valid / total * 100) if total > 0 else 0

                total_all += total
                valid_all += valid
                invalid_all += invalid
                redirected_all += redirected
                removed_all += removed

                f.write(f"| {country_code} | {total} | {valid} | {invalid} | "
                       f"{redirected} | {removed} | {success_rate:.1f}% |\n")

            # Overall totals
            success_rate_all = (valid_all / total_all * 100) if total_all > 0 else 0
            f.write(f"| **TOTAL** | **{total_all}** | **{valid_all}** | **{invalid_all}** | "
                   f"**{redirected_all}** | **{removed_all}** | **{success_rate_all:.1f}%** |\n")

            # Error details by country
            if error_details:
                f.write("\n## Errors by Country\n\n")

                for country_code in sorted(error_details.keys()):
                    errors = error_details[country_code]
                    anchor = _country_anchor(country_code)
                    f.write(f'<a id="{anchor}"></a>\n\n')
                    f.write(f"### {country_code} ({len(errors)} errors)\n\n")

                    # Group by error type
                    by_status = defaultdict(list)
                    for error in errors:
                        status = error["status_code"] if error["status_code"] else "Unknown"
                        by_status[status].append(error)

                    for status in sorted(by_status.keys(), key=str):
                        status_errors = by_status[status]
                        f.write(f"#### Status {status} ({len(status_errors)} URLs)\n\n")

                        for error in status_errors[:10]:  # Limit to first 10 per status
                            f.write(f"- `{error['url']}`")
                            if error["failure_count"] >= 2:
                                f.write(" ⚠️ **REMOVED** (failed 2+ times)")
                            if error["error_message"]:
                                f.write(f"\n  - Error: {error['error_message']}")
                            f.write("\n")

                        if len(status_errors) > 10:
                            f.write(f"\n_... and {len(status_errors) - 10} more URLs with status {status}_\n")

                        f.write("\n")

                    f.write("[↑ Back to top](#url-validation-report)\n\n")

            # Legend
            f.write("\n## Legend\n\n")
            f.write("- **Valid**: URL responded with HTTP 2xx status\n")
            f.write("- **Invalid**: URL returned error or non-2xx status\n")
            f.write("- **Redirected**: URL redirected to another location\n")
            f.write("- **Removed**: URL failed validation twice and was removed from TOON file\n")
            f.write("- ⚠️ **REMOVED** marker indicates URLs that have been removed due to 2+ failures\n")

        print(f"Report generated: {output_path}")

        # Print summary to console
        print("\n" + "=" * 80)
        print("VALIDATION SUMMARY")
        print("=" * 80)
        print(f"Total URLs validated: {total_all}")
        print(f"Valid URLs: {valid_all} ({success_rate_all:.1f}%)")
        print(f"Invalid URLs: {invalid_all}")
        print(f"Redirected URLs: {redirected_all}")
        print(f"Removed URLs: {removed_all}")
        print(f"\nCountries scanned: {len(country_stats)}")
        if error_details:
            print(f"Countries with errors: {len(error_details)}")
        print("=" * 80)

    finally:
        conn.close()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate URL validation report from database"
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file path for the report",
        type=Path,
        default=Path("validation-report.md"),
    )
    parser.add_argument(
        "--db",
        help="Database file path (overrides settings)",
        type=Path,
    )

    args = parser.parse_args()

    # Get database path
    if args.db:
        db_path = args.db
    else:
        settings = load_settings()
        db_path = Path(settings.metadata_db_url.replace("sqlite:///", ""))

    try:
        generate_report(db_path, args.output)
    except Exception as e:
        print(f"Error generating report: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
