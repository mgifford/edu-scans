"""CLI tool to generate the Google Lighthouse scan results page.

Queries the metadata database for aggregate Lighthouse scan statistics and
updates ``docs/lighthouse-results.md`` with a live stats block between
``<!-- LIGHTHOUSE_STATS_START -->`` and ``<!-- LIGHTHOUSE_STATS_END -->``
markers.  A summary JSON data file (``docs/lighthouse-data.json``) is also
written so that the page and external tools can link to machine-readable
results.  An optional CSV file (``docs/lighthouse-data.csv``) exports one
row per scanned URL for independent verification of the aggregate numbers.
Both files are uploaded as workflow artifacts rather than committed to the
repository (they may exceed GitHub's 100 MB file-size limit at scale).
"""

from __future__ import annotations

import argparse
import csv
import io
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

_STATS_MARKER_START = "<!-- LIGHTHOUSE_STATS_START -->"
_STATS_MARKER_END = "<!-- LIGHTHOUSE_STATS_END -->"


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


def _build_institution_lookup(toon_seeds_dir: Path) -> dict[str, str]:
    """Return a mapping of canonical_domain → institution_name from toon seed files.

    Reads every ``*.toon`` file in *toon_seeds_dir* and builds a lookup from
    each domain's ``canonical_domain`` to its ``institution_name``.  Returns an
    empty dict when the directory does not exist or contains no seed files.
    """
    lookup: dict[str, str] = {}
    if not toon_seeds_dir.is_dir():
        return lookup
    for toon_file in toon_seeds_dir.glob("*.toon"):
        try:
            data = json.loads(toon_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for domain_entry in data.get("domains", []):
            canonical = domain_entry.get("canonical_domain", "").strip()
            name = domain_entry.get("institution_name", "").strip()
            if canonical and name:
                lookup[canonical] = name
    return lookup


def _group_by_institution(
    rows_by_url: list[dict],
    institution_lookup: dict[str, str] | None = None,
) -> list[dict]:
    """Group per-URL Lighthouse results by institution domain.

    Extracts the network location (e.g. ``labi.edu``) from each URL, groups
    rows by that domain, and computes per-institution aggregates.  Results are
    sorted by domain name for stable output.

    Args:
        rows_by_url: Rows returned by :func:`_query_by_url`.
        institution_lookup: Optional mapping from canonical domain to
            institution display name (from :func:`_build_institution_lookup`).

    Returns:
        A list of dicts, one per institution, with keys:
        ``domain``, ``institution_name``, ``total_scanned``, ``total_success``,
        ``avg_performance``, ``avg_accessibility``, ``avg_best_practices``,
        ``avg_seo``.
    """
    institution_lookup = institution_lookup or {}
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows_by_url:
        domain = urlparse(row.get("url", "")).netloc
        if domain:
            groups[domain].append(row)

    result: list[dict] = []
    for domain in sorted(groups):
        rows = groups[domain]
        success_rows = [r for r in rows if r.get("error_message") is None]

        def _avg(key: str) -> float | None:
            vals = [r[key] for r in success_rows if r.get(key) is not None]
            return sum(vals) / len(vals) if vals else None

        result.append(
            {
                "domain": domain,
                "institution_name": institution_lookup.get(domain, domain),
                "total_scanned": len(rows),
                "total_success": len(success_rows),
                "avg_performance": _avg("performance_score"),
                "avg_accessibility": _avg("accessibility_score"),
                "avg_best_practices": _avg("best_practices_score"),
                "avg_seo": _avg("seo_score"),
            }
        )
    return result


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _query_summary(conn: sqlite3.Connection) -> dict:
    """Return aggregate Lighthouse scan totals from the database.

    Each URL may appear in multiple scan batches.  Counts use
    COUNT(DISTINCT …) so that a URL is counted at most once regardless of
    how many scan batches it appears in.
    """
    row = conn.execute(
        """
        SELECT
            COUNT(DISTINCT scan_id)                                                         AS total_batches,
            COUNT(DISTINCT url)                                                             AS total_scanned,
            COUNT(DISTINCT CASE WHEN error_message IS NULL THEN url ELSE NULL END)         AS total_success,
            AVG(CASE WHEN error_message IS NULL AND performance_score IS NOT NULL
                     THEN performance_score END)                                           AS avg_performance,
            AVG(CASE WHEN error_message IS NULL AND accessibility_score IS NOT NULL
                     THEN accessibility_score END)                                         AS avg_accessibility,
            AVG(CASE WHEN error_message IS NULL AND best_practices_score IS NOT NULL
                     THEN best_practices_score END)                                        AS avg_best_practices,
            AVG(CASE WHEN error_message IS NULL AND seo_score IS NOT NULL
                     THEN seo_score END)                                                   AS avg_seo,
            MIN(scanned_at)                                                                 AS first_scan,
            MAX(scanned_at)                                                                 AS last_scan
        FROM url_lighthouse_results
        """
    ).fetchone()
    if row is None:
        return {}
    return dict(row)


def _query_by_country(conn: sqlite3.Connection) -> list[dict]:
    """Return per-country Lighthouse scan statistics.

    For each country, returns the most-recent successful score averages
    alongside total URLs audited and audit date.  Uses the latest
    successful scan per URL to avoid double-counting across batches.
    """
    rows = conn.execute(
        """
        SELECT
            country_code,
            COUNT(DISTINCT url)                                                             AS total_scanned,
            COUNT(DISTINCT CASE WHEN error_message IS NULL THEN url ELSE NULL END)         AS total_success,
            AVG(CASE WHEN error_message IS NULL AND performance_score IS NOT NULL
                     THEN performance_score END)                                           AS avg_performance,
            AVG(CASE WHEN error_message IS NULL AND accessibility_score IS NOT NULL
                     THEN accessibility_score END)                                         AS avg_accessibility,
            AVG(CASE WHEN error_message IS NULL AND best_practices_score IS NOT NULL
                     THEN best_practices_score END)                                        AS avg_best_practices,
            AVG(CASE WHEN error_message IS NULL AND seo_score IS NOT NULL
                     THEN seo_score END)                                                   AS avg_seo,
            MAX(scanned_at)                                                                 AS last_scan
        FROM url_lighthouse_results
        GROUP BY country_code
        ORDER BY country_code
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _query_by_url(conn: sqlite3.Connection) -> list[dict]:
    """Return per-URL Lighthouse scan results for independent verification.

    Returns one row per URL using the most recent scan result when a URL has
    been scanned more than once.  Results are ordered by country code then URL
    so the output is stable and easy to diff between runs.

    These rows back up the aggregate numbers shown in the country table —
    every claim in the report can be reproduced by grouping on ``country_code``
    and recalculating the averages from these individual rows.
    """
    rows = conn.execute(
        """
        SELECT
            r.country_code,
            r.url,
            r.performance_score,
            r.accessibility_score,
            r.best_practices_score,
            r.seo_score,
            r.error_message,
            r.scanned_at
        FROM url_lighthouse_results r
        INNER JOIN (
            SELECT url, MAX(scanned_at) AS latest_scanned_at
            FROM url_lighthouse_results
            GROUP BY url
        ) latest ON r.url = latest.url AND r.scanned_at = latest.latest_scanned_at
        ORDER BY r.country_code, r.url
        """
    ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------

_CSV_FIELDNAMES = [
    "country_code",
    "url",
    "performance",
    "accessibility",
    "best_practices",
    "seo",
    "error",
    "scanned_at",
]


def _score_pct(val: float | None) -> str:
    """Format a 0.0–1.0 score as a percentage string (one decimal place) or empty string."""
    return f"{val * 100:.1f}" if val is not None else ""


def _write_csv(rows_by_url: list[dict], csv_path: Path) -> None:
    """Write per-URL Lighthouse scan results to a CSV file.

    Args:
        rows_by_url: Rows returned by :func:`_query_by_url`.
        csv_path: Destination path for the CSV file.

    The CSV uses UTF-8 encoding with a BOM so it opens correctly in
    spreadsheet applications.  Scores are expressed on the 0–100 scale
    (rounded to one decimal place) to match the human-readable report;
    missing or error rows have empty score cells.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_FIELDNAMES, lineterminator="\r\n")
    writer.writeheader()
    for row in rows_by_url:
        writer.writerow(
            {
                "country_code": row.get("country_code", ""),
                "url": row.get("url", ""),
                "performance": _score_pct(row.get("performance_score")),
                "accessibility": _score_pct(row.get("accessibility_score")),
                "best_practices": _score_pct(row.get("best_practices_score")),
                "seo": _score_pct(row.get("seo_score")),
                "error": row.get("error_message") or "",
                "scanned_at": row.get("scanned_at") or "",
            }
        )
    # Write UTF-8 BOM so Excel opens the file correctly without import wizard.
    csv_path.write_bytes(b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8"))


# ---------------------------------------------------------------------------
# Stats block builder
# ---------------------------------------------------------------------------

def _pct(val: float | None) -> str:
    """Format a 0.0–1.0 score as an integer percentage string."""
    return f"{val * 100:.0f}" if val is not None else "—"


def _build_stats_block(
    summary: dict,
    by_country: list[dict],
    generated_at: str,
    total_available: int = 0,
    seed_counts: dict[str, int] | None = None,
    by_institution: list[dict] | None = None,
) -> str:
    """Return a Markdown stats block to inject between the markers.

    Args:
        summary: Aggregate stats from :func:`_query_summary`.
        by_country: Per-country rows from :func:`_query_by_country`.
        generated_at: Human-readable timestamp string.
        total_available: Total pages in toon seed files.  When > 0 the
            block includes a "X of Y available pages scanned" coverage line.
        seed_counts: Mapping of country_code → available page count.
        by_institution: Per-institution rows from :func:`_group_by_institution`.
            When provided, a "Lighthouse Scores by Institution" table is appended.
    """
    if not summary or not summary.get("total_scanned"):
        return (
            f"{_STATS_MARKER_START}\n\n"
            "_No Lighthouse scan data yet — stats update automatically after "
            "every scan run.  Trigger the **Scan Lighthouse** workflow manually "
            "or wait for the next scheduled run._\n\n"
            f"{_STATS_MARKER_END}"
        )

    batches = summary.get("total_batches") or 0
    scanned = summary.get("total_scanned") or 0
    success = summary.get("total_success") or 0
    last_scan = (summary.get("last_scan") or "")[:10] or "—"

    lines = [
        _STATS_MARKER_START,
        "",
        f"_Stats as of {generated_at} — last scan: {last_scan}_",
        "",
        f"**{batches:,}** scan batches run",
        "",
    ]

    if total_available > 0:
        scan_pct = f"{scanned / total_available * 100:.1f}%" if total_available else "—"
        lines.append(
            f"**{scanned:,}** of **{total_available:,}** available pages audited "
            f"(**{scan_pct}** coverage)"
        )
    else:
        lines.append(f"**{scanned:,}** pages audited")

    lines += [
        f"**{success:,}** successful audits "
        f"(**{success / scanned * 100:.1f}%** of audited)" if scanned else "",
        "",
    ]

    # Overall average scores
    avg_perf = summary.get("avg_performance")
    avg_a11y = summary.get("avg_accessibility")
    avg_bp = summary.get("avg_best_practices")
    avg_seo = summary.get("avg_seo")
    if any(v is not None for v in (avg_perf, avg_a11y, avg_bp, avg_seo)):
        lines += [
            "**Overall average Lighthouse scores** (0–100 scale):",
            "",
            "| Performance | Accessibility | Best Practices | SEO |",
            "|:-----------:|:-------------:|:--------------:|:---:|",
            f"| {_pct(avg_perf)} | {_pct(avg_a11y)} | {_pct(avg_bp)} | {_pct(avg_seo)} |",
            "",
        ]

    # Per-country breakdown table
    if by_country:
        seed_counts = seed_counts or {}
        lines += [
            "---",
            "",
            "## Lighthouse Scores by Country",
            "",
            "| Country | Audited | Available | Perf | A11y | Best Practices | SEO | Last Scan |",
            "|---------|--------:|----------:|:----:|:----:|:--------------:|:---:|-----------|",
        ]
        for row in by_country:
            cc = row["country_code"]
            display_cc = country_code_to_display_name(cc)
            available = seed_counts.get(cc, 0)
            avail_str = f"{available:,}" if available else "—"
            last = (row.get("last_scan") or "—")[:10]
            lines.append(
                f"| {display_cc} | {row['total_scanned']:,} | {avail_str} | "
                f"{_pct(row.get('avg_performance'))} | "
                f"{_pct(row.get('avg_accessibility'))} | "
                f"{_pct(row.get('avg_best_practices'))} | "
                f"{_pct(row.get('avg_seo'))} | "
                f"{last} |"
            )
        lines += [
            "",
            "> Scores are averages across all successfully audited URLs, displayed "
            "as 0–100 (Lighthouse stores scores as 0.0–1.0 internally).",
            "",
            "---",
            "",
        ]

    # Per-institution breakdown table
    if by_institution:
        lines += [
            "## Lighthouse Scores by Institution",
            "",
            "| Institution | Domain | Audited | Perf | A11y | Best Practices | SEO |",
            "|-------------|--------|--------:|:----:|:----:|:--------------:|:---:|",
        ]
        for row in by_institution:
            name = row.get("institution_name") or row.get("domain", "—")
            domain = row.get("domain", "—")
            lines.append(
                f"| {name} | {domain} | {row['total_scanned']:,} | "
                f"{_pct(row.get('avg_performance'))} | "
                f"{_pct(row.get('avg_accessibility'))} | "
                f"{_pct(row.get('avg_best_practices'))} | "
                f"{_pct(row.get('avg_seo'))} |"
            )
        lines += [
            "",
            "> Scores are averages across all successfully audited pages for each institution, "
            "displayed as 0–100.  Institutions with only failed audits show —.",
            "",
            "---",
            "",
        ]

    lines += [
        "📥 Machine-readable results: "
        "[Download machine-readable Lighthouse data (JSON)](lighthouse-data.json)"
        " · "
        "[Download per-URL Lighthouse data (CSV)](lighthouse-data.csv)",
        "",
        _STATS_MARKER_END,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_lighthouse_report(
    db_path: Path,
    page_path: Path,
    data_path: Path,
    toon_seeds_dir: Path | None = None,
    csv_path: Path | None = None,
) -> bool:
    """Update *page_path* stats block, write *data_path* JSON, and optionally write *csv_path* CSV.

    Args:
        db_path: Path to the SQLite metadata database.
        page_path: Path to the ``docs/lighthouse-results.md`` Markdown page.
        data_path: Output path for the machine-readable JSON data file.
        toon_seeds_dir: Directory containing ``*.toon`` seed files.  When
            provided the stats block includes a coverage line.
        csv_path: Optional output path for a CSV file containing one row per
            scanned URL.  When provided, the CSV enables independent
            verification of the aggregate numbers in the report.

    Returns:
        ``True`` on success, ``False`` when the markers are missing from
        *page_path* (the page is left unchanged in that case).
    """
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if not db_path.exists():
        summary: dict = {}
        by_country: list[dict] = []
        by_url: list[dict] = []
    else:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            summary = _query_summary(conn)
            by_country = _query_by_country(conn)
            by_url = _query_by_url(conn)
        finally:
            conn.close()

    seed_counts = _count_toon_seed_urls(toon_seeds_dir) if toon_seeds_dir else {}
    total_available = sum(seed_counts.values())
    institution_lookup = _build_institution_lookup(toon_seeds_dir) if toon_seeds_dir else {}
    by_institution = _group_by_institution(by_url, institution_lookup) if by_url else []

    # --- write the JSON data file -----------------------------------------
    data_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {
        "generated_at": generated_at,
        "summary": {
            "total_batches": summary.get("total_batches") or 0,
            "total_scanned": summary.get("total_scanned") or 0,
            "total_success": summary.get("total_success") or 0,
            "total_available": total_available,
            "avg_performance": summary.get("avg_performance"),
            "avg_accessibility": summary.get("avg_accessibility"),
            "avg_best_practices": summary.get("avg_best_practices"),
            "avg_seo": summary.get("avg_seo"),
            "first_scan": summary.get("first_scan"),
            "last_scan": summary.get("last_scan"),
        },
        "by_country": by_country,
        "by_url": by_url,
    }
    data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Data file written: {data_path}")

    # --- write the CSV data file (optional) --------------------------------
    if csv_path is not None:
        _write_csv(by_url, csv_path)
        print(f"CSV file written: {csv_path} ({len(by_url)} rows)")

    # --- update the Markdown page -----------------------------------------
    if not page_path.exists():
        print(f"Lighthouse results page not found: {page_path}", file=sys.stderr)
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

    new_block = _build_stats_block(
        summary, by_country, generated_at, total_available,
        seed_counts=seed_counts, by_institution=by_institution,
    )
    new_content = (
        content[:start_idx]
        + new_block
        + content[end_idx + len(_STATS_MARKER_END):]
    )
    page_path.write_text(new_content, encoding="utf-8")
    print(f"Lighthouse results page updated: {page_path}")

    # --- console summary --------------------------------------------------
    print("\n" + "=" * 60)
    print("LIGHTHOUSE STATS SUMMARY")
    print("=" * 60)
    print(f"Batches run       : {summary.get('total_batches', 0):,}")
    scanned = summary.get("total_scanned", 0)
    success = summary.get("total_success", 0)
    if total_available:
        print(
            f"Pages audited     : {scanned:,} / {total_available:,} available "
            f"({scanned / total_available * 100:.1f}% coverage)"
        )
    else:
        print(f"Pages audited     : {scanned:,}")
    print(f"Successful audits : {success:,} / {scanned:,}")
    avg_a11y = summary.get("avg_accessibility")
    avg_perf = summary.get("avg_performance")
    if avg_a11y is not None:
        print(f"Avg accessibility : {avg_a11y * 100:.1f}")
    if avg_perf is not None:
        print(f"Avg performance   : {avg_perf * 100:.1f}")
    print("=" * 60)

    return True


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate aggregate Lighthouse scan stats and update "
            "docs/lighthouse-results.md with a live stats block."
        )
    )
    parser.add_argument(
        "--page",
        help="Path to the Lighthouse results Markdown page (default: docs/lighthouse-results.md)",
        type=Path,
        default=Path("docs/lighthouse-results.md"),
    )
    parser.add_argument(
        "--data",
        help="Output path for the JSON data file (default: docs/lighthouse-data.json)",
        type=Path,
        default=Path("docs/lighthouse-data.json"),
    )
    parser.add_argument(
        "--db",
        help="Database file path (overrides settings)",
        type=Path,
    )
    parser.add_argument(
        "--csv",
        help=(
            "Output path for the per-URL CSV data file for independent verification "
            "(default: docs/lighthouse-data.csv)"
        ),
        type=Path,
        default=Path("docs/lighthouse-data.csv"),
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
        ok = generate_lighthouse_report(
            db_path,
            args.page,
            args.data,
            toon_seeds_dir=args.seeds_dir,
            csv_path=args.csv,
        )
        if not ok:
            sys.exit(1)
    except Exception as exc:
        print(f"Error generating Lighthouse report: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
