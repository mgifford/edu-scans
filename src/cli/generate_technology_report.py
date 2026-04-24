"""CLI tool to generate the technology scan stats page.

Queries the metadata database for aggregate technology scan statistics
and updates ``docs/technology-scanning.md`` with a live stats block between
``<!-- TECH_STATS_START -->`` and ``<!-- TECH_STATS_END -->``
markers.  A summary JSON data file (``docs/technology-data.json``) is also
written so that external tools and the page itself can link directly to the
machine-readable results.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.lib.country_utils import country_code_to_display_name, country_filename_to_code
from src.lib.settings import load_settings


# ---------------------------------------------------------------------------
# HTML comment markers
# ---------------------------------------------------------------------------

_STATS_MARKER_START = "<!-- TECH_STATS_START -->"
_STATS_MARKER_END = "<!-- TECH_STATS_END -->"


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
    """Return aggregate technology scan totals from the database.

    Each URL may appear in multiple scan batches (one row per (url, scan_id)).
    Counts use COUNT(DISTINCT …) so that a URL is counted at most once
    regardless of how many scan batches it appears in.
    """
    row = conn.execute(
        """
        SELECT
            COUNT(DISTINCT scan_id)                                                         AS total_batches,
            COUNT(DISTINCT url)                                                             AS total_scanned,
            COUNT(DISTINCT CASE WHEN error_message IS NULL THEN url ELSE NULL END)         AS total_detected,
            MIN(scanned_at)                                                                 AS first_scan,
            MAX(scanned_at)                                                                 AS last_scan
        FROM url_tech_results
        """
    ).fetchone()
    if row is None:
        return {}
    return dict(row)


def _query_tech_rows(conn: sqlite3.Connection) -> list[dict]:
    """Return per-URL technology data for aggregation.

    Returns one row per distinct URL where detection succeeded (no
    error_message) and technologies were found.  When a URL appears in
    multiple scan batches the row from the latest scan is used.
    """
    rows = conn.execute(
        """
        SELECT url, technologies
        FROM url_tech_results AS t
        WHERE error_message IS NULL
          AND technologies != '{}'
          AND scanned_at = (
              SELECT MAX(scanned_at)
              FROM url_tech_results AS t2
              WHERE t2.url = t.url
                AND t2.error_message IS NULL
          )
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _parse_technologies(raw_value: str | None) -> list[dict[str, object]]:
    """Return a normalized technology list from a JSON payload."""
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, dict):
        return []

    technologies: list[dict[str, object]] = []
    for name in sorted(parsed):
        info = parsed[name]
        if not isinstance(info, dict):
            technologies.append(
                {"name": name, "categories": [], "versions": []}
            )
            continue
        categories = info.get("categories")
        versions = info.get("versions")
        technologies.append(
            {
                "name": name,
                "categories": categories if isinstance(categories, list) else [],
                "versions": versions if isinstance(versions, list) else [],
            }
        )
    return technologies


def _query_country_drilldowns(
    conn: sqlite3.Connection,
) -> dict[str, dict[str, list[dict[str, object]]]]:
    """Return per-country evidence rows for the country table drilldowns."""
    rows = conn.execute(
        """
        SELECT country_code, url, technologies, error_message, scanned_at
        FROM url_tech_results
        ORDER BY country_code, url, scanned_at DESC
        """
    ).fetchall()

    grouped: dict[str, dict[str, list[dict[str, object]]]] = {}
    seen_scanned: set[tuple[str, str]] = set()
    seen_detected: set[tuple[str, str]] = set()

    for row in rows:
        country_code = row["country_code"]
        page_url = row["url"]
        key = (country_code, page_url)
        country_bucket = grouped.setdefault(
            country_code,
            {"scanned": [], "detected": []},
        )
        tech_list = _parse_technologies(row["technologies"])
        record = {
            "page_url": page_url,
            "technologies": tech_list,
            "technology_names": [item["name"] for item in tech_list],
            "error_message": row["error_message"] or "",
            "last_scanned": row["scanned_at"] or "",
        }

        if key not in seen_scanned:
            country_bucket["scanned"].append(record)
            seen_scanned.add(key)

        if key not in seen_detected and row["error_message"] is None:
            country_bucket["detected"].append(record)
            seen_detected.add(key)

    return grouped


def _query_by_country(conn: sqlite3.Connection) -> list[dict]:
    """Return per-country technology scan totals."""
    rows = conn.execute(
        """
        SELECT
            country_code,
            COUNT(DISTINCT url)                                                             AS total_scanned,
            COUNT(DISTINCT CASE WHEN error_message IS NULL THEN url ELSE NULL END)         AS total_detected,
            MAX(scanned_at)                                                                 AS last_scan
        FROM url_tech_results
        GROUP BY country_code
        ORDER BY country_code
        """
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Technology aggregation
# ---------------------------------------------------------------------------

def _aggregate_tech_counts(
    tech_rows: list[dict],
) -> tuple[Counter, Counter, dict[str, list[str]]]:
    """Aggregate technology and category counts from per-URL technology data.

    Each URL is counted **at most once** per technology, even if the same
    URL appears in *tech_rows* more than once.

    Args:
        tech_rows: List of dicts with ``url`` and ``technologies`` (JSON str)
            keys, as returned by :func:`_query_tech_rows`.

    Returns:
        A three-tuple of:

        * *tech_counts* — ``Counter`` mapping technology name → page count.
        * *cat_counts*  — ``Counter`` mapping category name → page count.
        * *tech_categories* — dict mapping technology name → sorted list of
          category names (for display in the stats block).
    """
    tech_counts: Counter = Counter()
    cat_counts: Counter = Counter()
    tech_categories: dict[str, set] = {}

    seen_urls: set[str] = set()
    for row in tech_rows:
        url = row["url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)

        try:
            techs: dict = json.loads(row["technologies"] or "{}")
        except (json.JSONDecodeError, TypeError):
            continue

        for tech_name, tech_info in techs.items():
            tech_counts[tech_name] += 1
            if not isinstance(tech_info, dict):
                continue
            cats: list[str] = tech_info.get("categories", [])
            if tech_name not in tech_categories:
                tech_categories[tech_name] = set()
            tech_categories[tech_name].update(cats)
            for cat in cats:
                cat_counts[cat] += 1

    # Convert sets to sorted lists for deterministic output
    sorted_tech_categories: dict[str, list[str]] = {
        name: sorted(cats) for name, cats in tech_categories.items()
    }
    return tech_counts, cat_counts, sorted_tech_categories


# ---------------------------------------------------------------------------
# Stats block builder
# ---------------------------------------------------------------------------

def _build_stats_block(
    summary: dict,
    tech_counts: Counter,
    cat_counts: Counter,
    tech_categories: dict[str, list[str]],
    generated_at: str,
    total_available: int = 0,
    top_n_techs: int = 20,
    top_n_cats: int = 15,
    by_country: list[dict] | None = None,
    seed_counts: dict[str, int] | None = None,
) -> str:
    """Return a Markdown stats block to inject between the markers.

    Args:
        summary: Aggregate stats from :func:`_query_summary`.
        tech_counts: Technology name → page count from :func:`_aggregate_tech_counts`.
        cat_counts: Category name → page count from :func:`_aggregate_tech_counts`.
        tech_categories: Technology name → category list from :func:`_aggregate_tech_counts`.
        generated_at: Human-readable timestamp string.
        total_available: Total pages across all toon seed files.  When > 0
            the block includes a "X of Y available pages scanned" coverage line.
        top_n_techs: How many top technologies to list in the table.
        top_n_cats: How many top categories to list in the table.
        by_country: Per-country rows from :func:`_query_by_country`.  When
            provided, the block includes a per-country scan breakdown table.
        seed_counts: Mapping of country_code → available page count from
            toon seed files.  Used for the "Available" column in the per-country
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
    detected = summary.get("total_detected") or 0
    last_scan = (summary.get("last_scan") or "")[:10] or "—"
    unique_techs = len(tech_counts)

    def _pct(num: int, denom: int) -> str:
        return f"{num / denom * 100:.1f}%" if denom else "—"

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
            f"**{scanned:,}** of **{total_available:,}** available pages scanned "
            f"(**{scan_pct}** coverage)"
        )
    else:
        lines.append(f"**{scanned:,}** pages scanned")

    lines += [
        f"**{detected:,}** pages with technology detections "
        f"(**{_pct(detected, scanned)}** of scanned)",
        f"**{unique_techs:,}** unique technologies identified",
        "",
    ]

    # Per-country breakdown table
    if by_country:
        seed_counts = seed_counts or {}
        lines += [
            "---",
            "",
            "## Technology Scan by Country",
            "",
            "| Country | URLs Scanned | Pages with Detections | Available | Last Scan |",
            "|---------|-------------|----------------------|-----------|----------|",
        ]
        for row in by_country:
            cc = row["country_code"]
            display_cc = country_code_to_display_name(cc)
            available = seed_counts.get(cc, 0)
            avail_str = f"{available:,}" if available else "—"
            last = (row.get("last_scan") or "—")[:10]
            lines.append(
                f"| {display_cc} | {row['total_scanned']:,} | {row['total_detected']:,} "
                f"| {avail_str} | {last} |"
            )
        lines += [
            "",
            "> Hover or focus any non-zero country-table count to preview matching pages. "
            "Activate the number to keep the preview open and download a CSV for that "
            "country and metric from [Download machine-readable technology data (JSON)](technology-data.json).",
            "",
            "---",
            "",
        ]

    # Top technologies table
    if tech_counts:
        lines += [
            "### Top Technologies",
            "",
            "| # | Technology | Pages | Categories |",
            "|--:|-----------|------:|-----------|",
        ]
        for rank, (tech, count) in enumerate(tech_counts.most_common(top_n_techs), start=1):
            cats = ", ".join(tech_categories.get(tech, []))
            lines.append(f"| {rank} | {tech} | **{count:,}** | {cats} |")
        lines.append("")

    # Top categories table
    if cat_counts:
        lines += [
            "### Top Technology Categories",
            "",
            "| # | Category | Pages |",
            "|--:|---------|------:|",
        ]
        for rank, (cat, count) in enumerate(cat_counts.most_common(top_n_cats), start=1):
            lines.append(f"| {rank} | {cat} | **{count:,}** |")
        lines.append("")

    lines += [
        "📥 Machine-readable results: "
        "[Download machine-readable technology data (JSON)](technology-data.json)",
        "",
        _STATS_MARKER_END,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_technology_report(
    db_path: Path,
    page_path: Path,
    data_path: Path,
    toon_seeds_dir: Path | None = None,
) -> bool:
    """Update *page_path* stats block and write *data_path* JSON.

    Args:
        db_path: Path to the SQLite metadata database.
        page_path: Path to the ``docs/technology-scanning.md`` Markdown page.
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
        tech_rows: list[dict] = []
        by_country: list[dict] = []
        country_drilldowns: dict[str, dict[str, list[dict[str, object]]]] = {}
    else:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            summary = _query_summary(conn)
            tech_rows = _query_tech_rows(conn)
            by_country = _query_by_country(conn)
            country_drilldowns = _query_country_drilldowns(conn)
        finally:
            conn.close()

    tech_counts, cat_counts, tech_categories = _aggregate_tech_counts(tech_rows)

    seed_counts = _count_toon_seed_urls(toon_seeds_dir) if toon_seeds_dir else {}
    total_available = sum(seed_counts.values())

    # --- write the JSON data file -----------------------------------------
    data_path.parent.mkdir(parents=True, exist_ok=True)

    # Build top-technologies list for JSON (sorted by count descending)
    top_technologies = [
        {
            "name": tech,
            "pages": count,
            "categories": tech_categories.get(tech, []),
        }
        for tech, count in tech_counts.most_common()
    ]

    top_categories = [
        {"name": cat, "pages": count}
        for cat, count in cat_counts.most_common()
    ]

    data: dict = {
        "generated_at": generated_at,
        "summary": {
            "total_batches": summary.get("total_batches") or 0,
            "total_scanned": summary.get("total_scanned") or 0,
            "total_detected": summary.get("total_detected") or 0,
            "total_available": total_available,
            "unique_technologies": len(tech_counts),
            "unique_categories": len(cat_counts),
            "first_scan": summary.get("first_scan"),
            "last_scan": summary.get("last_scan"),
        },
        "top_technologies": top_technologies,
        "top_categories": top_categories,
        "by_country": by_country,
        "country_drilldowns": country_drilldowns,
    }
    data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Data file written: {data_path}")

    # --- update the Markdown page -----------------------------------------
    if not page_path.exists():
        print(f"Technology page not found: {page_path}", file=sys.stderr)
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
        summary, tech_counts, cat_counts, tech_categories, generated_at, total_available,
        by_country=by_country, seed_counts=seed_counts,
    )
    new_content = (
        content[:start_idx]
        + new_block
        + content[end_idx + len(_STATS_MARKER_END):]
    )
    page_path.write_text(new_content, encoding="utf-8")
    print(f"Technology page updated: {page_path}")

    # --- console summary --------------------------------------------------
    print("\n" + "=" * 60)
    print("TECHNOLOGY STATS SUMMARY")
    print("=" * 60)
    print(f"Batches run       : {summary.get('total_batches', 0):,}")
    scanned = summary.get("total_scanned", 0)
    detected = summary.get("total_detected", 0)
    if total_available:
        print(f"Pages scanned     : {scanned:,} / {total_available:,} available "
              f"({scanned / total_available * 100:.1f}% coverage)")
    else:
        print(f"Pages scanned     : {scanned:,}")
    print(f"Pages with tech   : {detected:,} / {scanned:,}")
    print(f"Unique technologies: {len(tech_counts):,}")
    print(f"Unique categories : {len(cat_counts):,}")
    if tech_counts:
        print("\nTop 10 technologies:")
        for tech, count in tech_counts.most_common(10):
            print(f"  {tech}: {count:,}")
    print("=" * 60)

    return True


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate aggregate technology scan stats and update "
            "docs/technology-scanning.md with a live stats block."
        )
    )
    parser.add_argument(
        "--page",
        help="Path to the technology Markdown page (default: docs/technology-scanning.md)",
        type=Path,
        default=Path("docs/technology-scanning.md"),
    )
    parser.add_argument(
        "--data",
        help="Output path for the JSON data file (default: docs/technology-data.json)",
        type=Path,
        default=Path("docs/technology-data.json"),
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
        ok = generate_technology_report(db_path, args.page, args.data, args.seeds_dir)
        if not ok:
            sys.exit(1)
    except Exception as exc:
        print(f"Error generating technology report: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
