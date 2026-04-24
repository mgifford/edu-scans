"""CLI tool to generate the third-party JavaScript stats page.

Queries the metadata database for aggregate third-party JavaScript scan
statistics and updates ``docs/third-party-tools.md`` with a live stats block
between ``<!-- THIRD_PARTY_JS_STATS_START -->`` and
``<!-- THIRD_PARTY_JS_STATS_END -->`` markers. A summary JSON data file
(``docs/third-party-tools-data.json``) is also written so that external tools
and the page itself can link directly to the machine-readable results.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from src.lib.country_utils import country_code_to_display_name, country_filename_to_code
from src.lib.settings import load_settings


_STATS_MARKER_START = "<!-- THIRD_PARTY_JS_STATS_START -->"
_STATS_MARKER_END = "<!-- THIRD_PARTY_JS_STATS_END -->"

# Query-string parameter names that may carry API keys or tokens embedded in
# third-party script src URLs found on scanned government websites.  These are
# stripped from src values before the data is written to the committed JSON
# data file so that the repo does not inadvertently store API credentials.
_SENSITIVE_QUERY_PARAMS: frozenset[str] = frozenset({"key", "token", "apikey", "api_key"})


def _sanitize_script_src(src: str) -> str:
    """Strip sensitive query parameters (e.g. ``key=``) from a script src URL.

    The function parses the URL, removes any query parameter whose name matches
    a known sensitive pattern, and returns the sanitised URL.  Non-URL values
    (e.g. relative paths without a scheme) are returned unchanged.
    """
    if not src:
        return src
    try:
        parsed = urlparse(src)
    except ValueError:
        return src
    if not parsed.query:
        return src
    filtered = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() not in _SENSITIVE_QUERY_PARAMS]
    clean_query = urlencode(filtered)
    return urlunparse(parsed._replace(query=clean_query))


def _count_toon_seed_urls(toon_seeds_dir: Path) -> dict[str, int]:
    """Return a mapping of country_code to page_count from toon seed files."""
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


def _query_summary(conn: sqlite3.Connection) -> dict:
    """Return aggregate third-party JavaScript scan totals from the database."""
    row = conn.execute(
        """
        SELECT
            COUNT(DISTINCT scan_id) AS total_batches,
            COUNT(DISTINCT url) AS total_scanned,
            COUNT(DISTINCT CASE WHEN is_reachable = 1 THEN url ELSE NULL END) AS total_reachable,
            COUNT(DISTINCT CASE WHEN scripts != '[]' THEN url ELSE NULL END) AS urls_with_scripts,
            MIN(scanned_at) AS first_scan,
            MAX(scanned_at) AS last_scan
        FROM url_third_party_js_results
        """
    ).fetchone()
    if row is None:
        return {}
    return dict(row)


def _query_script_rows(conn: sqlite3.Connection) -> list[dict]:
    """Return latest successful per-URL script payloads for aggregation."""
    rows = conn.execute(
        """
        SELECT url, scripts
        FROM url_third_party_js_results AS t
        WHERE is_reachable = 1
          AND scanned_at = (
              SELECT MAX(scanned_at)
              FROM url_third_party_js_results AS t2
              WHERE t2.url = t.url
                AND t2.is_reachable = 1
          )
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _query_by_country(conn: sqlite3.Connection) -> list[dict]:
    """Return per-country third-party JavaScript scan totals."""
    rows = conn.execute(
        """
        SELECT
            country_code,
            COUNT(DISTINCT url) AS total_scanned,
            COUNT(DISTINCT CASE WHEN is_reachable = 1 THEN url ELSE NULL END) AS reachable,
            COUNT(DISTINCT CASE WHEN scripts != '[]' THEN url ELSE NULL END) AS urls_with_scripts,
            MIN(scanned_at) AS first_scan,
            MAX(scanned_at) AS last_scan
        FROM url_third_party_js_results
        GROUP BY country_code
        ORDER BY country_code
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _parse_scripts(raw_value: str | None) -> list[dict[str, object]]:
    """Return a normalized third-party script list from JSON text."""
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []

    scripts: list[dict[str, object]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        categories = item.get("categories")
        scripts.append(
            {
                "src": _sanitize_script_src(item.get("src") or ""),
                "host": item.get("host") or "",
                "service_name": item.get("service_name") or "",
                "version": item.get("version") or "",
                "categories": categories if isinstance(categories, list) else [],
            }
        )
    return scripts


def _query_country_drilldowns(
    conn: sqlite3.Connection,
) -> dict[str, dict[str, list[dict[str, object]]]]:
    """Return per-country evidence rows for third-party JS report tables."""
    rows = conn.execute(
        """
        SELECT country_code, url, is_reachable, scripts, error_message, scanned_at
        FROM url_third_party_js_results
        ORDER BY country_code, url, scanned_at DESC
        """
    ).fetchall()

    grouped: dict[str, dict[str, list[dict[str, object]]]] = {}
    seen_reachable: set[tuple[str, str]] = set()
    seen_script_pages: set[tuple[str, str]] = set()
    seen_service_rows: set[tuple[str, str]] = set()

    for row in rows:
        country_code = row["country_code"]
        page_url = row["url"]
        key = (country_code, page_url)
        country_bucket = grouped.setdefault(
            country_code,
            {"scanned": [], "reachable": [], "urls_with_scripts": [], "service_loads": []},
        )
        scripts = _parse_scripts(row["scripts"])
        page_record = {
            "page_url": page_url,
            "scripts": scripts,
            "service_names": [
                script["service_name"] for script in scripts if script["service_name"]
            ],
            "error_message": row["error_message"] or "",
            "last_scanned": row["scanned_at"] or "",
        }

        if key not in seen_reachable:
            country_bucket["scanned"].append(page_record)
        if key not in seen_reachable and row["is_reachable"]:
            country_bucket["reachable"].append(page_record)
            seen_reachable.add(key)
        elif key not in seen_reachable:
            seen_reachable.add(key)

        if key not in seen_script_pages and scripts:
            country_bucket["urls_with_scripts"].append(page_record)
            seen_script_pages.add(key)

        if key in seen_service_rows or not row["is_reachable"]:
            continue

        for script in scripts:
            service_name = script["service_name"]
            if not service_name:
                continue
            country_bucket["service_loads"].append(
                {
                    "page_url": page_url,
                    "service_name": service_name,
                    "src": script["src"],
                    "host": script["host"],
                    "version": script["version"],
                    "categories": script["categories"],
                    "last_scanned": row["scanned_at"] or "",
                }
            )
        seen_service_rows.add(key)

    return grouped


def _aggregate_script_counts(
    script_rows: list[dict],
) -> tuple[Counter, Counter, int]:
    """Aggregate known service and category counts from per-URL script data."""
    service_counts: Counter = Counter()
    category_counts: Counter = Counter()
    identified_scripts = 0

    seen_urls: set[str] = set()
    for row in script_rows:
        url = row["url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)

        try:
            scripts = json.loads(row["scripts"] or "[]")
        except (json.JSONDecodeError, TypeError):
            continue

        for script in scripts:
            if not isinstance(script, dict):
                continue
            service_name = script.get("service_name")
            categories = script.get("categories") or []
            if service_name:
                service_counts[service_name] += 1
                identified_scripts += 1
            for category in categories:
                category_counts[category] += 1

    return service_counts, category_counts, identified_scripts


def _query_identified_services_by_country(conn: sqlite3.Connection) -> dict[str, int]:
    """Return per-country counts of identified known third-party services."""
    rows = conn.execute(
        """
        SELECT country_code, scripts
        FROM url_third_party_js_results
        WHERE is_reachable = 1
        ORDER BY country_code, scanned_at DESC
        """
    ).fetchall()

    latest_scripts: dict[str, dict[str, str]] = {}
    for country_code, scripts in rows:
        country_bucket = latest_scripts.setdefault(country_code, {})
        if scripts not in country_bucket:
            country_bucket[scripts] = scripts

    counts: dict[str, int] = {}
    per_url_seen: set[tuple[str, str]] = set()
    url_rows = conn.execute(
        """
        SELECT country_code, url, scripts
        FROM url_third_party_js_results
        WHERE is_reachable = 1
        ORDER BY scanned_at DESC
        """
    ).fetchall()
    for country_code, url, scripts in url_rows:
        key = (country_code, url)
        if key in per_url_seen:
            continue
        per_url_seen.add(key)
        try:
            script_list = json.loads(scripts or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        for script in script_list:
            if isinstance(script, dict) and script.get("service_name"):
                counts[country_code] = counts.get(country_code, 0) + 1
    return counts


def _build_stats_block(
    summary: dict,
    service_counts: Counter,
    category_counts: Counter,
    identified_scripts: int,
    generated_at: str,
    total_available: int = 0,
    by_country: list[dict] | None = None,
    identified_by_country: dict[str, int] | None = None,
    seed_counts: dict[str, int] | None = None,
    top_n_services: int = 20,
    top_n_categories: int = 15,
) -> str:
    """Return a Markdown stats block to inject between the markers."""
    if not summary or not summary.get("total_scanned"):
        return (
            f"{_STATS_MARKER_START}\n\n"
            "_No scan data yet — stats update automatically after every scan run._\n\n"
            f"{_STATS_MARKER_END}"
        )

    batches = summary.get("total_batches") or 0
    scanned = summary.get("total_scanned") or 0
    reachable = summary.get("total_reachable") or 0
    urls_with_scripts = summary.get("urls_with_scripts") or 0
    last_scan = (summary.get("last_scan") or "")[:10] or "—"

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
        f"**{reachable:,}** of **{scanned:,}** scanned pages were reachable "
        f"(**{_pct(reachable, scanned)}**)",
        f"**{urls_with_scripts:,}** reachable pages loaded at least one third-party script "
        f"(**{_pct(urls_with_scripts, reachable)}** of reachable)",
        f"**{identified_scripts:,}** known third-party service loads identified",
        f"**{len(service_counts):,}** unique known services across "
        f"**{len(category_counts):,}** categories",
        "",
    ]

    if by_country:
        seed_counts = seed_counts or {}
        identified_by_country = identified_by_country or {}
        lines += [
            "---",
            "",
            "## Third-Party JavaScript by Country",
            "",
            "| Country | Scanned | Available | Reachable | URLs with 3rd-Party JS | Known Service Loads | Last Scan |",
            "|---------|---------|-----------|-----------|------------------------|--------------------|----------|",
        ]
        for row in by_country:
            cc = row["country_code"]
            display_cc = country_code_to_display_name(cc)
            available = seed_counts.get(cc, 0)
            avail_str = f"{available:,}" if available else "—"
            last = (row.get("last_scan") or "—")[:10]
            lines.append(
                f"| {display_cc} | {row['total_scanned']:,} | {avail_str} | {row['reachable']:,} | "
                f"{row.get('urls_with_scripts', 0):,} | {identified_by_country.get(cc, 0):,} | {last} |"
            )
        lines += [
            "",
            "> Hover or focus any non-zero country-table count to preview matching pages. "
            "Activate the number to keep the preview open and download a CSV for that "
            "country and metric from [Download machine-readable third-party tools data (JSON)](third-party-tools-data.json).",
            "",
            "---",
            "",
        ]

    if service_counts:
        lines += [
            "### Top Third-Party Services",
            "",
            "| # | Service | Loads |",
            "|--:|---------|------:|",
        ]
        for rank, (service, count) in enumerate(service_counts.most_common(top_n_services), start=1):
            lines.append(f"| {rank} | {service} | **{count:,}** |")
        lines.append("")

    if category_counts:
        lines += [
            "### Top Service Categories",
            "",
            "| # | Category | Loads |",
            "|--:|----------|------:|",
        ]
        for rank, (category, count) in enumerate(category_counts.most_common(top_n_categories), start=1):
            lines.append(f"| {rank} | {category} | **{count:,}** |")
        lines.append("")

    lines += [
        "📥 Machine-readable results: "
        "[Download machine-readable third-party tools data (JSON)](third-party-tools-data.json)",
        "",
        _STATS_MARKER_END,
    ]
    return "\n".join(lines)


def generate_third_party_js_report(
    db_path: Path,
    page_path: Path,
    data_path: Path,
    toon_seeds_dir: Path | None = None,
) -> bool:
    """Update the third-party JS page stats block and write JSON summary data."""
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if not db_path.exists():
        summary: dict = {}
        script_rows: list[dict] = []
        by_country: list[dict] = []
        identified_by_country: dict[str, int] = {}
        country_drilldowns: dict[str, dict[str, list[dict[str, object]]]] = {}
    else:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            summary = _query_summary(conn)
            script_rows = _query_script_rows(conn)
            by_country = _query_by_country(conn)
            identified_by_country = _query_identified_services_by_country(conn)
            country_drilldowns = _query_country_drilldowns(conn)
        finally:
            conn.close()

    service_counts, category_counts, identified_scripts = _aggregate_script_counts(
        script_rows
    )
    seed_counts = _count_toon_seed_urls(toon_seeds_dir) if toon_seeds_dir else {}
    total_available = sum(seed_counts.values())

    data_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "generated_at": generated_at,
        "summary": {
            "total_batches": summary.get("total_batches") or 0,
            "total_scanned": summary.get("total_scanned") or 0,
            "total_reachable": summary.get("total_reachable") or 0,
            "urls_with_scripts": summary.get("urls_with_scripts") or 0,
            "total_available": total_available,
            "identified_service_loads": identified_scripts,
            "unique_services": len(service_counts),
            "unique_categories": len(category_counts),
            "first_scan": summary.get("first_scan"),
            "last_scan": summary.get("last_scan"),
        },
        "top_services": [
            {"name": service, "loads": count}
            for service, count in service_counts.most_common()
        ],
        "top_categories": [
            {"name": category, "loads": count}
            for category, count in category_counts.most_common()
        ],
        "by_country": [
            {
                **row,
                "identified_service_loads": identified_by_country.get(
                    row["country_code"], 0
                ),
            }
            for row in by_country
        ],
        "country_drilldowns": country_drilldowns,
    }
    data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Data file written: {data_path}")

    if not page_path.exists():
        print(f"Third-party JS page not found: {page_path}", file=sys.stderr)
        return False

    content = page_path.read_text(encoding="utf-8")
    start_idx = content.find(_STATS_MARKER_START)
    end_idx = content.find(_STATS_MARKER_END)
    if start_idx == -1 or end_idx == -1:
        print(
            f"Stats markers not found in {page_path}. Add {_STATS_MARKER_START!r} "
            f"and {_STATS_MARKER_END!r} to the file.",
            file=sys.stderr,
        )
        return False

    new_block = _build_stats_block(
        summary=summary,
        service_counts=service_counts,
        category_counts=category_counts,
        identified_scripts=identified_scripts,
        generated_at=generated_at,
        total_available=total_available,
        by_country=by_country,
        identified_by_country=identified_by_country,
        seed_counts=seed_counts,
    )
    new_content = (
        content[:start_idx] + new_block + content[end_idx + len(_STATS_MARKER_END):]
    )
    page_path.write_text(new_content, encoding="utf-8")
    print(f"Third-party JS page updated: {page_path}")
    return True


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate aggregate third-party JavaScript stats and update "
            "docs/third-party-tools.md with a live stats block."
        )
    )
    parser.add_argument(
        "--page",
        help="Path to the third-party JS Markdown page (default: docs/third-party-tools.md)",
        type=Path,
        default=Path("docs/third-party-tools.md"),
    )
    parser.add_argument(
        "--data",
        help="Output path for the JSON data file (default: docs/third-party-tools-data.json)",
        type=Path,
        default=Path("docs/third-party-tools-data.json"),
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
            "coverage (default: data/toon-seeds/countries)"
        ),
        type=Path,
        default=Path("data/toon-seeds/countries"),
    )
    args = parser.parse_args()

    if args.db:
        db_path = args.db
    else:
        settings = load_settings()
        db_path = Path(settings.metadata_db_url.replace("sqlite:///", ""))

    try:
        ok = generate_third_party_js_report(
            db_path, args.page, args.data, args.seeds_dir
        )
        if not ok:
            sys.exit(1)
    except Exception as exc:
        print(f"Error generating third-party JS report: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
