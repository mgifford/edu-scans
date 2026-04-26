"""CLI tool to generate the accessibility statement scanning stats page.

Queries the metadata database for aggregate accessibility scan statistics
and updates ``docs/accessibility-statements.md`` with a live stats block
between ``<!-- ACCESSIBILITY_STATS_START -->`` and
``<!-- ACCESSIBILITY_STATS_END -->`` markers.  A summary JSON data file
(``docs/accessibility-data.json``) is also written so that external tools
can access the machine-readable results.  This file is uploaded as a workflow
artifact rather than committed to the repository (it can exceed GitHub's
100 MB file-size limit at scale).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from src.lib.country_utils import country_code_to_display_name, country_filename_to_code
from src.lib.settings import load_settings


# ---------------------------------------------------------------------------
# HTML comment markers
# ---------------------------------------------------------------------------

_STATS_MARKER_START = "<!-- ACCESSIBILITY_STATS_START -->"
_STATS_MARKER_END = "<!-- ACCESSIBILITY_STATS_END -->"


# ---------------------------------------------------------------------------
# Toon seed helpers
# ---------------------------------------------------------------------------

def _count_toon_seed_urls(toon_seeds_dir: Path) -> dict[str, int]:
    """Return a mapping of country_code → page_count from toon seed files.

    Reads every ``*.toon`` file in *toon_seeds_dir* and extracts the
    ``page_count`` field.  Returns an empty dict when the directory does
    not exist or contains no seed files.
    """
    counts: dict[str, int] = {}
    if not toon_seeds_dir.is_dir():
        return counts
    for toon_file in toon_seeds_dir.glob("*.toon"):
        try:
            data = json.loads(toon_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        country_code = country_filename_to_code(toon_file.stem)
        counts[country_code] = int(data.get("page_count") or 0)
    return counts


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _query_summary(conn: sqlite3.Connection) -> dict:
    """Return aggregate accessibility scan totals from the database.

    Counts distinct domains (hostnames) rather than individual URLs so that
    multiple probe paths scanned per domain are collapsed to a single entry.
    A domain is counted as reachable / has_statement / found_in_footer if
    *any* of its scanned URLs produced that result.
    """
    row = conn.execute(
        """
        WITH domain_rows AS (
            SELECT
                CASE WHEN INSTR(SUBSTR(url, INSTR(url, '://') + 3), '/') > 0
                     THEN SUBSTR(url, INSTR(url, '://') + 3,
                                 INSTR(SUBSTR(url, INSTR(url, '://') + 3), '/') - 1)
                     ELSE SUBSTR(url, INSTR(url, '://') + 3)
                END                  AS domain,
                MAX(is_reachable)    AS is_reachable,
                MAX(has_statement)   AS has_statement,
                MAX(found_in_footer) AS found_in_footer,
                MIN(scanned_at)      AS first_scan,
                MAX(scanned_at)      AS last_scan
            FROM url_accessibility_results
            GROUP BY domain
        )
        SELECT
            (SELECT COUNT(DISTINCT scan_id) FROM url_accessibility_results) AS total_batches,
            COUNT(*)              AS total_scanned,
            SUM(is_reachable)     AS total_reachable,
            SUM(has_statement)    AS total_has_statement,
            SUM(found_in_footer)  AS total_in_footer,
            MIN(first_scan)       AS first_scan,
            MAX(last_scan)        AS last_scan
        FROM domain_rows
        """
    ).fetchone()
    if row is None:
        return {}
    return dict(row)


def _query_by_country(conn: sqlite3.Connection) -> list[dict]:
    """Return per-country accessibility scan totals.

    Counts distinct domains (hostnames) per country rather than individual
    URLs so that multiple probe paths scanned per domain are collapsed to a
    single domain entry.  A domain is counted as reachable / has_statement /
    found_in_footer if *any* of its scanned URLs produced that result.
    """
    rows = conn.execute(
        """
        WITH domain_rows AS (
            SELECT
                country_code,
                CASE WHEN INSTR(SUBSTR(url, INSTR(url, '://') + 3), '/') > 0
                     THEN SUBSTR(url, INSTR(url, '://') + 3,
                                 INSTR(SUBSTR(url, INSTR(url, '://') + 3), '/') - 1)
                     ELSE SUBSTR(url, INSTR(url, '://') + 3)
                END                  AS domain,
                MAX(is_reachable)    AS is_reachable,
                MAX(has_statement)   AS has_statement,
                MAX(found_in_footer) AS found_in_footer,
                MIN(scanned_at)      AS first_scan,
                MAX(scanned_at)      AS last_scan
            FROM url_accessibility_results
            GROUP BY country_code, domain
        )
        SELECT
            country_code,
            COUNT(*)              AS total_scanned,
            SUM(is_reachable)     AS reachable,
            SUM(has_statement)    AS has_statement,
            SUM(found_in_footer)  AS found_in_footer,
            MIN(first_scan)       AS first_scan,
            MAX(last_scan)        AS last_scan
        FROM domain_rows
        GROUP BY country_code
        ORDER BY country_code
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _parse_json_text_list(raw_value: str | None) -> list[str]:
    """Return a deduplicated list of strings parsed from JSON text."""
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    values: list[str] = []
    for item in parsed:
        if not isinstance(item, str) or not item:
            continue
        if item not in values:
            values.append(item)
    return values


def _hostname_from_url(url: str) -> str:
    """Return the hostname portion of a URL, or an empty string on failure."""
    try:
        return urlparse(url).hostname or ""
    except ValueError:
        return ""


def _initial_page_record(row: sqlite3.Row) -> dict[str, object]:
    """Return the initial aggregate page record for a query row."""
    url = row["url"]
    return {
        "url": url,
        "domain": _hostname_from_url(url),
        "is_reachable": bool(row["is_reachable"]),
        "has_statement": bool(row["has_statement"]),
        "found_in_footer": bool(row["found_in_footer"]),
        "statement_links": _parse_json_text_list(row["statement_links"]),
        "matched_terms": _parse_json_text_list(row["matched_terms"]),
        "error_message": row["error_message"] or "",
        "last_scanned": row["scanned_at"],
    }


def _merge_page_record(page_record: dict[str, object], row: sqlite3.Row) -> None:
    """Merge another scan row for the same page into *page_record*."""
    page_record["is_reachable"] = bool(page_record["is_reachable"]) or bool(row["is_reachable"])
    page_record["has_statement"] = bool(page_record["has_statement"]) or bool(row["has_statement"])
    page_record["found_in_footer"] = bool(page_record["found_in_footer"]) or bool(row["found_in_footer"])

    statement_links = page_record["statement_links"]
    for link in _parse_json_text_list(row["statement_links"]):
        if link not in statement_links:
            statement_links.append(link)

    matched_terms = page_record["matched_terms"]
    for term in _parse_json_text_list(row["matched_terms"]):
        if term not in matched_terms:
            matched_terms.append(term)

    error_message = row["error_message"] or ""
    if error_message:
        page_record["error_message"] = error_message

    scanned_at = row["scanned_at"]
    if scanned_at and (
        not page_record["last_scanned"]
        or str(scanned_at) > str(page_record["last_scanned"])
    ):
        page_record["last_scanned"] = scanned_at


def _categorize_page_records(
    page_records: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    """Return page records split into with-statement, without, and unreachable."""
    with_statement: list[dict[str, object]] = []
    without_statement: list[dict[str, object]] = []
    unreachable: list[dict[str, object]] = []

    for record in page_records:
        if record["has_statement"]:
            with_statement.append(record)
        elif record["is_reachable"]:
            without_statement.append(record)
        else:
            unreachable.append(record)

    return with_statement, without_statement, unreachable


def _summarize_domains(page_records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Return per-domain accessibility counts for a country's page records."""
    domains: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "domain": "",
            "total_pages": 0,
            "reachable_pages": 0,
            "has_statement_pages": 0,
            "no_statement_pages": 0,
            "found_in_footer_pages": 0,
            "unreachable_pages": 0,
        }
    )

    for record in page_records:
        domain = str(record["domain"] or "")
        if not domain:
            continue
        summary = domains[domain]
        summary["domain"] = domain
        summary["total_pages"] += 1
        if record["is_reachable"]:
            summary["reachable_pages"] += 1
        else:
            summary["unreachable_pages"] += 1
        if record["has_statement"]:
            summary["has_statement_pages"] += 1
        elif record["is_reachable"]:
            summary["no_statement_pages"] += 1
        if record["found_in_footer"]:
            summary["found_in_footer_pages"] += 1

    return sorted(domains.values(), key=lambda item: str(item["domain"]))


def _query_country_detail(conn: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Return per-country page and domain detail for accessibility evidence."""
    rows = conn.execute(
        """
        SELECT
            country_code,
            url,
            is_reachable,
            has_statement,
            found_in_footer,
            statement_links,
            matched_terms,
            error_message,
            scanned_at
        FROM url_accessibility_results
        ORDER BY country_code, url, scanned_at DESC
        """
    ).fetchall()

    countries: dict[str, dict[str, dict[str, object]]] = {}
    for row in rows:
        country_code = row["country_code"]
        pages = countries.setdefault(country_code, {})
        page_record = pages.get(row["url"])
        if page_record is None:
            pages[row["url"]] = _initial_page_record(row)
            continue
        _merge_page_record(page_record, row)

    details: dict[str, dict[str, object]] = {}
    for country_code, pages in sorted(countries.items()):
        page_records = sorted(pages.values(), key=lambda item: str(item["url"]))
        with_statement, without_statement, unreachable = _categorize_page_records(page_records)
        details[country_code] = {
            "pages_with_statement": with_statement,
            "pages_without_statement": without_statement,
            "unreachable_pages": unreachable,
            "domains": _summarize_domains(page_records),
        }
    return details


# ---------------------------------------------------------------------------
# Stats block builder
# ---------------------------------------------------------------------------

def _build_stats_block(
    summary: dict,
    generated_at: str,
    total_available: int = 0,
    by_country: list[dict] | None = None,
    seed_counts: dict[str, int] | None = None,
) -> str:
    """Return a Markdown stats block to inject between the markers.

    Args:
        summary: Aggregate stats from ``_query_summary()``.
        generated_at: Human-readable timestamp string.
        total_available: Total pages across all toon seed files.  When > 0,
            the block includes a "X of Y available pages scanned" coverage line.
        by_country: Per-country rows from ``_query_by_country()``.  When
            provided, the block includes a per-country breakdown table.
        seed_counts: Mapping of country_code → available page count from toon
            seed files.  Used for the "Available" column in the per-country
            table when *by_country* is provided.
    """
    if not summary or not summary.get("total_scanned"):
        return (
            f"{_STATS_MARKER_START}\n\n"
            "_No scan data yet — stats update automatically after every scan run._\n\n"
            f"{_STATS_MARKER_END}"
        )

    batches = summary.get("total_batches") or 0
    scanned = summary.get("total_scanned") or 0
    reachable = summary.get("total_reachable") or 0
    has_statement = summary.get("total_has_statement") or 0
    in_footer = summary.get("total_in_footer") or 0
    last_scan = (summary.get("last_scan") or "")[:10] or "—"

    def _pct(num: int, denom: int) -> str:
        return f"{num / denom * 100:.1f}%" if denom else "—"

    def _month(ts: str | None) -> str:
        if not ts:
            return "—"
        try:
            return datetime.fromisoformat(ts[:19]).strftime("%b %Y")
        except (ValueError, TypeError):
            return ts[:7]

    def _scan_period(first: str | None, last: str | None) -> str:
        first_month = _month(first)
        last_month = _month(last)
        if first_month and last_month:
            return first_month if first_month == last_month else f"{first_month} – {last_month}"
        return first_month or last_month or "—"

    lines = [
        _STATS_MARKER_START,
        "",
        f"_Stats as of {generated_at} — last scan: {last_scan}_",
        "",
        f"**{batches:,}** scan batches run",
        "",
    ]

    if total_available > 0:
        scan_pct = _pct(scanned, total_available)
        lines.append(
            f"**{scanned:,}** of **{total_available:,}** available domains scanned "
            f"(**{scan_pct}** coverage)"
        )
    else:
        lines.append(f"**{scanned:,}** domains scanned")

    lines += [
        f"**{reachable:,}** of **{scanned:,}** scanned domains were reachable "
        f"(**{_pct(reachable, scanned)}**)",
        f"**{has_statement:,}** of **{reachable:,}** reachable domains have an "
        f"accessibility statement (**{_pct(has_statement, reachable)}**)",
        f"**{in_footer:,}** domains have the statement link in the footer "
        f"(**{_pct(in_footer, has_statement)}** of domains with a statement)",
        "",
        "📥 Machine-readable results are available as the "
        "[accessibility-data.json artifact (machine-readable JSON)]"
        "(https://github.com/mgifford/eu-plus-government-scans/actions/workflows/generate-scan-progress.yml).",
        "",
        "Each country entry in the JSON file includes page-level evidence for "
        "pages with and without accessibility statements, plus a per-domain "
        "summary you can share to validate the published counts.",
        "",
        "> Hover or focus any non-zero count in the country table to preview the "
        "matching pages. If there are 20 or fewer URLs, the preview shows all of "
        "them; otherwise it shows a short sample. Full machine-readable data is "
        "available as the [accessibility-data.json artifact (machine-readable JSON)]"
        "(https://github.com/mgifford/eu-plus-government-scans/actions/workflows/generate-scan-progress.yml).",
    ]

    # Per-country breakdown table
    if by_country:
        seed_counts = seed_counts or {}

        lines += [
            "",
            "---",
            "",
            "## Accessibility Statement Scan by Country",
            "",
            "| Country | Domains | Available | Reachable | Has Statement | In Footer | Statement % | Scan Period |",
            "|---------|---------|-----------|-----------|--------------|-----------|------------|-------------|",
        ]
        for row in by_country:
            cc = row["country_code"]
            display_cc = country_code_to_display_name(cc)
            available = seed_counts.get(cc, 0)
            avail_str = f"{available:,}" if available else "—"
            period = _scan_period(row.get("first_scan"), row.get("last_scan"))
            stmt_pct = _pct(row.get("has_statement", 0), row.get("reachable", 0))
            lines.append(
                f"| {display_cc} | {row['total_scanned']:,} | {avail_str} | {row['reachable']:,} | "
                f"{row.get('has_statement', 0):,} | {row.get('found_in_footer', 0):,} | "
                f"{stmt_pct} | {period} |"
            )

        # totals row
        tot_scanned = sum(r["total_scanned"] for r in by_country)
        tot_avail = sum(seed_counts.values())
        tot_avail_str = f"**{tot_avail:,}**" if tot_avail else "—"
        tot_reachable = sum(r["reachable"] for r in by_country)
        tot_has_statement = sum(r.get("has_statement", 0) for r in by_country)
        tot_in_footer = sum(r.get("found_in_footer", 0) for r in by_country)
        tot_stmt_pct = _pct(tot_has_statement, tot_reachable)
        lines.append(
            f"| **Total** | **{tot_scanned:,}** | {tot_avail_str} | **{tot_reachable:,}** | "
            f"**{tot_has_statement:,}** | **{tot_in_footer:,}** | **{tot_stmt_pct}** | — |"
        )
        lines += [
            "",
            "> **Statement %** is the percentage of *reachable* domains that contain "
            "at least one link to an accessibility statement.",
        ]

    lines += [
        "",
        _STATS_MARKER_END,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_accessibility_report(
    db_path: Path,
    page_path: Path,
    data_path: Path,
    toon_seeds_dir: Path | None = None,
) -> bool:
    """Update *page_path* stats block and write *data_path* JSON.

    Args:
        db_path: Path to the SQLite metadata database.
        page_path: Path to the ``docs/accessibility-statements.md`` Markdown page.
        data_path: Output path for the machine-readable JSON data file.
        toon_seeds_dir: Directory containing ``*.toon`` seed files.  When
            provided the stats block will include a "X of Y available pages
            scanned" coverage line and ``total_available`` is written to the
            JSON file.

    Returns ``True`` on success, ``False`` when the markers are missing from
    *page_path* (the page is left unchanged in that case).
    """
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if not db_path.exists():
        summary: dict = {}
        by_country: list[dict] = []
        country_detail: dict[str, dict[str, object]] = {}
    else:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            summary = _query_summary(conn)
            by_country = _query_by_country(conn)
            country_detail = _query_country_detail(conn)
        finally:
            conn.close()

    seed_counts = _count_toon_seed_urls(toon_seeds_dir) if toon_seeds_dir else {}
    total_available = sum(seed_counts.values())

    # --- write the JSON data file -----------------------------------------
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {
        "generated_at": generated_at,
        "summary": {
            "total_batches": summary.get("total_batches") or 0,
            "total_scanned": summary.get("total_scanned") or 0,
            "total_reachable": summary.get("total_reachable") or 0,
            "total_available": total_available,
            "total_has_statement": summary.get("total_has_statement") or 0,
            "total_in_footer": summary.get("total_in_footer") or 0,
            "first_scan": summary.get("first_scan"),
            "last_scan": summary.get("last_scan"),
        },
        "by_country": by_country,
        "country_detail": country_detail,
    }
    data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Data file written: {data_path}")

    # --- update the Markdown page -----------------------------------------
    if not page_path.exists():
        print(f"Accessibility page not found: {page_path}", file=sys.stderr)
        return False

    content = page_path.read_text(encoding="utf-8")
    start_idx = content.find(_STATS_MARKER_START)
    end_idx = content.find(_STATS_MARKER_END)

    if start_idx == -1 or end_idx == -1:
        print(
            f"Stats markers not found in {page_path}. "
            f"Add {_STATS_MARKER_START!r} and {_STATS_MARKER_END!r} to the file.",
            file=sys.stderr,
        )
        return False

    new_block = _build_stats_block(summary, generated_at, total_available, by_country, seed_counts)
    new_content = (
        content[:start_idx]
        + new_block
        + content[end_idx + len(_STATS_MARKER_END):]
    )
    page_path.write_text(new_content, encoding="utf-8")
    print(f"Accessibility page updated: {page_path}")

    # --- console summary --------------------------------------------------
    print("\n" + "=" * 60)
    print("ACCESSIBILITY STATS SUMMARY")
    print("=" * 60)
    print(f"Batches run       : {summary.get('total_batches', 0):,}")
    scanned = summary.get("total_scanned", 0)
    reachable = summary.get("total_reachable", 0)
    has_statement = summary.get("total_has_statement", 0)
    in_footer = summary.get("total_in_footer", 0)
    if total_available:
        print(f"Domains scanned   : {scanned:,} / {total_available:,} available "
              f"({scanned / total_available * 100:.1f}% coverage)")
    else:
        print(f"Domains scanned   : {scanned:,}")
    print(f"Reachable         : {reachable:,} / {scanned:,}")
    print(f"Has statement     : {has_statement:,} / {reachable:,}")
    print(f"Found in footer   : {in_footer:,}")
    print("=" * 60)

    return True


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate aggregate accessibility statement scan stats and update "
            "docs/accessibility-statements.md with a live stats block."
        )
    )
    parser.add_argument(
        "--page",
        help="Path to the accessibility Markdown page "
             "(default: docs/accessibility-statements.md)",
        type=Path,
        default=Path("docs/accessibility-statements.md"),
    )
    parser.add_argument(
        "--data",
        help="Output path for the JSON data file "
             "(default: docs/accessibility-data.json)",
        type=Path,
        default=Path("docs/accessibility-data.json"),
    )
    parser.add_argument(
        "--db",
        help="Database file path (overrides settings)",
        type=Path,
    )
    parser.add_argument(
        "--seeds-dir",
        help=(
            "Directory containing TOON seed files used to calculate scan "
            "coverage (default: data/toon-seeds)"
        ),
        type=Path,
        default=Path("data/toon-seeds"),
    )

    args = parser.parse_args()

    if args.db:
        db_path = args.db
    else:
        settings = load_settings()
        db_path = Path(settings.metadata_db_url.replace("sqlite:///", ""))

    try:
        ok = generate_accessibility_report(db_path, args.page, args.data, args.seeds_dir)
        if not ok:
            sys.exit(1)
    except Exception as exc:
        print(f"Error generating accessibility report: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
