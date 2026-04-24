"""CLI tool to generate a multi-scan progress report from the database.

Produces a Markdown summary that shows how far along each scan type
(URL validation, social media, technology) is across all countries,
so stakeholders can see overall coverage at a glance.
"""

from __future__ import annotations

import argparse
import io
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.lib.country_utils import country_code_to_display_name, country_filename_to_code
from src.lib.settings import load_settings


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

# Markers used in docs/index.md to delimit the auto-generated progress block.
_PROGRESS_MARKER_START = "<!-- SCAN_PROGRESS_START -->"
_PROGRESS_MARKER_END = "<!-- SCAN_PROGRESS_END -->"

# Progress-bar rendering constants.
_BAR_PX_PER_UNIT: int = 6        # pixels per logical width unit (width=20 → 120 px)
_BAR_MIN_SLIVER_PX: int = 2      # minimum filled width so non-zero bars are visible
_BAR_GREEN_THRESHOLD: float = 0.67   # ≥ this fraction → green fill
_BAR_AMBER_THRESHOLD: float = 0.34   # ≥ this fraction → amber fill; below → red


def _progress_bar(completed: int, total: int, width: int = 20) -> str:
    """Return an HTML progress bar for report tables.

    The bar is styled with inline CSS and meets WCAG 2.2 AA requirements:

    - Fill colours achieve ≥ 3:1 contrast against white (WCAG 1.4.11).
    - The percentage label (#374151) achieves > 9:1 contrast on white.
    - ``role="img"`` + ``aria-label`` provide a text alternative for
      screen readers (WCAG 1.1.1).

    Colour is mapped to completion level so the chart conveys status at
    a glance:

    - ≥ 67 %  → green  (#15803d, ~5.1:1 on white)
    - 34–66 % → amber  (#b45309, ~5.1:1 on white)
    - < 34 %  → red    (#b91c1c, ~6.0:1 on white)

    Args:
        completed: Number of items completed.
        total: Total number of items.
        width: Logical width units; each unit maps to ``_BAR_PX_PER_UNIT`` px
            (default 20 → 120 px wide bar).
    """
    if total == 0:
        return "—"
    pct = min(completed / total, 1.0)
    pct_display = f"{pct * 100:.1f}%"

    bar_px = width * _BAR_PX_PER_UNIT
    filled_px = round(pct * bar_px)
    # Always show a visible sliver for any non-zero count.
    if completed > 0 and filled_px == 0:
        filled_px = _BAR_MIN_SLIVER_PX

    # WCAG 1.4.11 Non-text Contrast: fill colour needs ≥ 3:1 vs background.
    if pct >= _BAR_GREEN_THRESHOLD:
        fill = "#15803d"  # green-700
    elif pct >= _BAR_AMBER_THRESHOLD:
        fill = "#b45309"  # amber-700
    else:
        fill = "#b91c1c"  # red-700

    return (
        f'<span role="img" aria-label="{pct_display} complete"'
        f' style="display:inline-flex;align-items:center;gap:4px;'
        f'vertical-align:middle;">'
        f'<span style="display:inline-block;width:{bar_px}px;height:12px;'
        f'background:#e2e8f0;border-radius:2px;overflow:hidden;">'
        f'<span style="display:block;width:{filled_px}px;height:100%;'
        f'background:{fill};"></span>'
        f'</span>'
        f'<span style="font-size:0.85em;color:#374151;">{pct_display}</span>'
        f'</span>'
    )


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


def _format_month_range(first: str | None, last: str | None) -> str:
    """Return a human-readable month range string.

    Both *first* and *last* are ISO-8601 timestamp strings (or None).
    Returns e.g. ``"Jan 2024 – Mar 2024"`` or ``"Mar 2024"`` when they are
    in the same month, or ``"—"`` when no data is available.
    """
    if not first and not last:
        return "—"

    def _to_month(ts: str) -> str:
        # Handle both "YYYY-MM-DD..." and "YYYY-MM-DDTHH:MM:SS..." formats.
        try:
            return datetime.fromisoformat(ts[:19]).strftime("%b %Y")
        except (ValueError, TypeError):
            return ts[:7]  # Fall back to "YYYY-MM"

    first_m = _to_month(first) if first else None
    last_m = _to_month(last) if last else None

    if first_m and last_m:
        return first_m if first_m == last_m else f"{first_m} – {last_m}"
    return first_m or last_m or "—"


# ---------------------------------------------------------------------------
# report generation
# ---------------------------------------------------------------------------

def generate_progress_report(
    db_path: Path,
    output_path: Path,
    toon_seeds_dir: Path | None = None,
    data_path: Path | None = None,
) -> None:
    """Generate a comprehensive scan-progress report from the database.

    Args:
        db_path: Path to the SQLite metadata database.
        output_path: Output file path for the Markdown report.
        toon_seeds_dir: Directory containing ``*.toon`` seed files.  When
            provided the report will include "X of Y available pages scanned"
            coverage figures in the overall-coverage section.
    """

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if not db_path.exists():
        with output_path.open("w") as f:
            f.write("---\ntitle: Scan Progress Report\nlayout: page\n---\n\n")
            f.write(f"_Generated: {generated_at}_\n\n")
            f.write("No scan data available yet. Run a scan first.\n")
        if data_path is not None:
            data_path.parent.mkdir(parents=True, exist_ok=True)
            data_path.write_text(
                json.dumps(
                    {"generated_at": generated_at, "url_validation_drilldowns": {}},
                    ensure_ascii=True,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
        print(f"Report generated (empty): {output_path}")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    seed_counts = _count_toon_seed_urls(toon_seeds_dir) if toon_seeds_dir else {}

    try:
        _write_report(conn, output_path, generated_at, seed_counts, data_path)
    finally:
        conn.close()

    print(f"Report generated: {output_path}")


def update_index_progress(
    index_path: Path,
    db_path: Path,
    toon_seeds_dir: Path | None = None,
) -> bool:
    """Replace the progress block in *index_path* with fresh scan stats.

    The block is delimited by ``<!-- SCAN_PROGRESS_START -->`` and
    ``<!-- SCAN_PROGRESS_END -->`` HTML comments.  If the markers are not
    found, the file is left unchanged and ``False`` is returned.

    Args:
        index_path: Path to the ``docs/index.md`` file to update.
        db_path: Path to the SQLite metadata database.
        toon_seeds_dir: Directory containing ``*.toon`` seed files.  When
            provided the coverage column shows scan coverage vs. available
            pages rather than reachability.

    Returns ``True`` when the index file was successfully updated.
    """
    if not index_path.exists():
        print(f"Index file not found: {index_path}", file=sys.stderr)
        return False

    content = index_path.read_text(encoding="utf-8")
    start_idx = content.find(_PROGRESS_MARKER_START)
    end_idx = content.find(_PROGRESS_MARKER_END)

    if start_idx == -1 or end_idx == -1:
        print(
            f"Progress markers not found in {index_path}. "
            "Add <!-- SCAN_PROGRESS_START --> and <!-- SCAN_PROGRESS_END --> "
            "to the file first.",
            file=sys.stderr,
        )
        return False

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    seed_counts = _count_toon_seed_urls(toon_seeds_dir) if toon_seeds_dir else {}
    total_available = sum(seed_counts.values())

    buf = io.StringIO()
    buf.write(_PROGRESS_MARKER_START + "\n\n")
    buf.write(f"_Progress as of {generated_at}_\n\n")

    if db_path.exists():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            url_val = _query_url_validation(conn)
            social = _query_social_media(conn)
            tech = _query_technology(conn)
            lighthouse = _query_lighthouse(conn)
            accessibility = _query_accessibility(conn)
            combined_reachable = _query_combined_reachability(conn)
        finally:
            conn.close()

        uv_total = sum(d["total"] for d in url_val.values())
        uv_valid = sum(d["valid"] for d in url_val.values())
        sm_total = sum(d["total"] for d in social.values())
        sm_reachable = sum(d["reachable"] for d in social.values())
        tech_total = sum(d["total"] for d in tech.values())
        lh_total = sum(d["total"] for d in lighthouse.values())
        a11y_total = sum(d["total"] for d in accessibility.values())
        combined_total = sum(d["confirmed"] for d in combined_reachable.values())
        all_countries = sorted(set(url_val) | set(social) | set(tech) | set(lighthouse) | set(accessibility))

        denom = total_available or combined_total or sm_total or uv_total or 1

        buf.write("| Scan Type | Pages Scanned | Coverage |\n")
        buf.write("|-----------|--------------|----------|\n")
        if combined_total:
            buf.write(
                f"| **Combined Reachability** | **{combined_total:,} confirmed reachable** | "
                f"**{_progress_bar(combined_total, denom)}** |\n"
            )
        buf.write(
            f"| Social Media | {sm_total:,} scanned "
            f"({sm_reachable:,} reachable) | "
            f"{_progress_bar(sm_total, denom)} |\n"
        )
        if tech_total:
            buf.write(
                f"| Technology | {tech_total:,} scanned | "
                f"{_progress_bar(tech_total, denom)} |\n"
            )
        if lh_total:
            buf.write(
                f"| Lighthouse | {lh_total:,} scanned | "
                f"{_progress_bar(lh_total, denom)} |\n"
            )
        if a11y_total:
            buf.write(
                f"| Accessibility Statements | {a11y_total:,} scanned | "
                f"{_progress_bar(a11y_total, denom)} |\n"
            )
        buf.write("\n")
        if total_available:
            buf.write(
                f"**{len(all_countries)} countries** with scan data · "
                f"**{combined_total:,}** of **{total_available:,}** available pages confirmed reachable. "
                "See the [Scan Progress Report](scan-progress.md) for full details.\n\n"
            )
        else:
            buf.write(
                f"**{len(all_countries)} countries** with scan data. "
                "See the [Scan Progress Report](scan-progress.md) for full details.\n\n"
            )
    else:
        buf.write(
            "_No scan data yet — progress updates automatically after every scan run._\n\n"
        )

    buf.write(_PROGRESS_MARKER_END)

    new_block = buf.getvalue()
    new_content = (
        content[:start_idx]
        + new_block
        + content[end_idx + len(_PROGRESS_MARKER_END):]
    )
    index_path.write_text(new_content, encoding="utf-8")
    print(f"Index updated: {index_path}")
    return True


def _query_url_validation(conn: sqlite3.Connection) -> dict[str, dict]:
    """Return per-country URL validation stats from the database.

    Uses COUNT(DISTINCT CASE WHEN … THEN url END) so that each URL is
    counted at most once per country even when it appears in multiple
    scan batches.
    """
    result: dict[str, dict] = {}
    for row in conn.execute(
        """
        SELECT country_code,
               COUNT(DISTINCT url)                                                   AS total,
               COUNT(DISTINCT CASE WHEN is_valid = 1 THEN url ELSE NULL END)        AS valid,
               COUNT(DISTINCT CASE WHEN is_valid = 0 THEN url ELSE NULL END)        AS invalid,
               MIN(validated_at)                                                     AS first_scan,
               MAX(validated_at)                                                     AS last_scan
        FROM url_validation_results
        GROUP BY country_code
        ORDER BY country_code
        """
    ):
        result[row["country_code"]] = dict(row)
    return result


def _query_url_validation_detail(conn: sqlite3.Connection) -> dict[str, dict[str, list[dict[str, object]]]]:
    """Return per-country drilldown data for URL validation counts.

    The summary table counts a URL once per country for each bucket where it ever
    appeared, so ``valid`` and ``invalid`` can overlap across scan runs.  The
    drilldown data mirrors that behavior while preserving the latest known
    validation state for each URL so stakeholders can inspect the evidence.
    """
    rows = conn.execute(
        """
        SELECT
            country_code,
            url,
            status_code,
            error_message,
            redirected_to,
            redirect_chain,
            is_valid,
            failure_count,
            validated_at
        FROM url_validation_results
        ORDER BY country_code, url, validated_at DESC
        """
    ).fetchall()

    by_country: dict[str, dict[str, dict[str, dict[str, object]]]] = {}
    for row in rows:
        country_code = row["country_code"]
        country = by_country.setdefault(
            country_code,
            {"total": {}, "valid": {}, "invalid": {}},
        )
        url = row["url"]
        record = country["total"].get(url)
        if record is None:
            record = {
                "url": url,
                "latest_status": "valid" if row["is_valid"] else "invalid",
                "latest_status_code": row["status_code"],
                "latest_error_message": row["error_message"] or "",
                "latest_redirected_to": row["redirected_to"] or "",
                "latest_redirect_chain": row["redirect_chain"] or "",
                "latest_failure_count": row["failure_count"] or 0,
                "latest_validated_at": row["validated_at"] or "",
                "ever_valid": False,
                "ever_invalid": False,
                "latest_valid_at": "",
                "latest_invalid_at": "",
            }
            country["total"][url] = record

        if row["is_valid"]:
            record["ever_valid"] = True
            if not record["latest_valid_at"]:
                record["latest_valid_at"] = row["validated_at"] or ""
            country["valid"].setdefault(url, record)
        else:
            record["ever_invalid"] = True
            if not record["latest_invalid_at"]:
                record["latest_invalid_at"] = row["validated_at"] or ""
            country["invalid"].setdefault(url, record)

    result: dict[str, dict[str, list[dict[str, object]]]] = {}
    for country_code, categories in by_country.items():
        result[country_code] = {
            key: sorted(category.values(), key=lambda item: str(item["url"]))
            for key, category in categories.items()
        }
    return result


def _query_social_media(conn: sqlite3.Connection) -> dict[str, dict]:
    """Return per-country social media scan stats from the database.

    Includes both tier distribution and per-platform link counts so that
    a single merged table can be generated without a separate query.
    Uses COUNT(DISTINCT CASE WHEN … THEN url END) so that each URL is
    counted at most once per country even when it appears in multiple
    scan batches.
    """
    result: dict[str, dict] = {}
    for row in conn.execute(
        """
        SELECT country_code,
               COUNT(DISTINCT url)                                                                                 AS total,
               COUNT(DISTINCT CASE WHEN is_reachable = 1             THEN url ELSE NULL END)                      AS reachable,
               COUNT(DISTINCT CASE WHEN social_tier = 'twitter_only' THEN url ELSE NULL END)                      AS twitter_only,
               COUNT(DISTINCT CASE WHEN social_tier = 'modern_only'  THEN url ELSE NULL END)                      AS modern_only,
               COUNT(DISTINCT CASE WHEN social_tier = 'mixed'        THEN url ELSE NULL END)                      AS mixed,
               COUNT(DISTINCT CASE WHEN social_tier = 'no_social'    THEN url ELSE NULL END)                      AS no_social,
               COUNT(DISTINCT CASE WHEN social_tier = 'unreachable'  THEN url ELSE NULL END)                      AS unreachable,
               COUNT(DISTINCT CASE WHEN twitter_links  != '[]'       THEN url ELSE NULL END)                      AS has_twitter,
               COUNT(DISTINCT CASE WHEN x_links        != '[]'       THEN url ELSE NULL END)                      AS has_x,
               COUNT(DISTINCT CASE WHEN bluesky_links  != '[]'       THEN url ELSE NULL END)                      AS has_bluesky,
               COUNT(DISTINCT CASE WHEN mastodon_links != '[]'       THEN url ELSE NULL END)                      AS has_mastodon,
               MIN(scanned_at)                                                                                     AS first_scan,
               MAX(scanned_at)                                                                                     AS last_scan
        FROM url_social_media_results
        GROUP BY country_code
        ORDER BY country_code
        """
    ):
        result[row["country_code"]] = dict(row)
    return result


def _query_combined_reachability(conn: sqlite3.Connection) -> dict[str, dict]:
    """Return per-country counts of URLs confirmed reachable by *any* scan.

    A URL is counted once even if it appears in both
    ``url_validation_results`` (``is_valid = 1``) and
    ``url_social_media_results`` (``is_reachable = 1``).  The UNION
    deduplicates across the two tables so each unique URL is counted at
    most once per country.
    """
    result: dict[str, dict] = {}
    for row in conn.execute(
        """
        SELECT country_code,
               COUNT(DISTINCT url) AS confirmed
        FROM (
            SELECT country_code, url
            FROM url_validation_results
            WHERE is_valid = 1
            UNION
            SELECT country_code, url
            FROM url_social_media_results
            WHERE is_reachable = 1
        )
        GROUP BY country_code
        ORDER BY country_code
        """
    ):
        result[row["country_code"]] = dict(row)
    return result


def _query_accessibility(conn: sqlite3.Connection) -> dict[str, dict]:
    """Return per-country accessibility statement scan stats from the database.

    Uses COUNT(DISTINCT CASE WHEN … THEN url END) so that each URL is counted
    at most once per country even when it appears in multiple scan batches.
    """
    result: dict[str, dict] = {}
    for row in conn.execute(
        """
        SELECT country_code,
               COUNT(DISTINCT url)                                                            AS total,
               COUNT(DISTINCT CASE WHEN is_reachable = 1    THEN url ELSE NULL END)          AS reachable,
               COUNT(DISTINCT CASE WHEN has_statement = 1   THEN url ELSE NULL END)          AS has_statement,
               COUNT(DISTINCT CASE WHEN found_in_footer = 1 THEN url ELSE NULL END)          AS found_in_footer,
               MIN(scanned_at)                                                                AS first_scan,
               MAX(scanned_at)                                                                AS last_scan
        FROM url_accessibility_results
        GROUP BY country_code
        ORDER BY country_code
        """
    ):
        result[row["country_code"]] = dict(row)
    return result


def _query_technology(conn: sqlite3.Connection) -> dict[str, dict]:
    """Return per-country technology scan stats from the database."""
    result: dict[str, dict] = {}
    for row in conn.execute(
        """
        SELECT country_code,
               COUNT(DISTINCT url)  AS total,
               MAX(scanned_at)      AS last_scan
        FROM url_tech_results
        GROUP BY country_code
        ORDER BY country_code
        """
    ):
        result[row["country_code"]] = dict(row)
    return result


def _query_lighthouse(conn: sqlite3.Connection) -> dict[str, dict]:
    """Return per-country Google Lighthouse scan stats from the database."""
    result: dict[str, dict] = {}
    for row in conn.execute(
        """
        SELECT country_code,
               COUNT(DISTINCT url)                                        AS total,
               AVG(CASE WHEN performance_score IS NOT NULL
                        THEN performance_score END)                       AS avg_performance,
               AVG(CASE WHEN accessibility_score IS NOT NULL
                        THEN accessibility_score END)                     AS avg_accessibility,
               AVG(CASE WHEN best_practices_score IS NOT NULL
                        THEN best_practices_score END)                    AS avg_best_practices,
               AVG(CASE WHEN seo_score IS NOT NULL
                        THEN seo_score END)                               AS avg_seo,
               MAX(scanned_at)                                            AS last_scan
        FROM url_lighthouse_results
        WHERE error_message IS NULL
        GROUP BY country_code
        ORDER BY country_code
        """
    ):
        result[row["country_code"]] = dict(row)
    return result


def _write_overall_coverage(
    f,
    url_val: dict[str, dict],
    social: dict[str, dict],
    tech: dict[str, dict],
    lighthouse: dict[str, dict] | None = None,
    seed_counts: dict[str, int] | None = None,
    combined_reachable: dict[str, dict] | None = None,
    accessibility: dict[str, dict] | None = None,
) -> tuple:
    """Write the overall coverage section.

    When *seed_counts* is provided the progress bar denominator is the total
    number of pages available in the toon seed files; otherwise the total
    number of scanned URLs is used.

    When *combined_reachable* is provided a summary row is prepended that
    shows the union of URLs confirmed reachable by *any* scan type (URL
    Validation or Social Media).
    """
    uv_total = sum(d["total"] for d in url_val.values())
    uv_valid = sum(d["valid"] for d in url_val.values())
    sm_total = sum(d["total"] for d in social.values())
    sm_reachable = sum(d["reachable"] for d in social.values())
    tech_total = sum(d["total"] for d in tech.values())
    lh_total = sum(d["total"] for d in (lighthouse or {}).values())
    a11y_total = sum(d["total"] for d in (accessibility or {}).values())
    combined_total = sum(d["confirmed"] for d in (combined_reachable or {}).values())

    total_available = sum((seed_counts or {}).values())
    denom = total_available or combined_total or sm_total or uv_total or 1

    avail_str = f"{total_available:,}" if total_available else "—"

    f.write("## Overall Coverage\n\n")
    if total_available:
        f.write(
            f"Coverage is measured as pages scanned out of "
            f"**{total_available:,}** pages available in the seed files.\n\n"
        )
    f.write("| Scan Type | Pages Scanned | Available | Coverage |\n")
    f.write("|-----------|--------------|-----------|----------|\n")
    if combined_total:
        f.write(
            f"| **Combined Reachability** | **{combined_total:,} confirmed reachable** | "
            f"{avail_str} | "
            f"**{_progress_bar(combined_total, denom)}** |\n"
        )
    f.write(
        f"| Social Media | {sm_total:,} scanned "
        f"({sm_reachable:,} reachable) | "
        f"{avail_str} | "
        f"{_progress_bar(sm_total, denom)} |\n"
    )
    f.write(
        f"| Technology | {tech_total:,} scanned | "
        f"{avail_str} | "
        f"{'(manual scan)' if tech_total == 0 else _progress_bar(tech_total, denom)} |\n"
    )
    f.write(
        f"| Lighthouse | {lh_total:,} scanned | "
        f"{avail_str} | "
        f"{'(manual scan)' if lh_total == 0 else _progress_bar(lh_total, denom)} |\n"
    )
    f.write(
        f"| Accessibility Statements | {a11y_total:,} scanned | "
        f"{avail_str} | "
        f"{_progress_bar(a11y_total, denom)} |\n"
    )
    f.write("\n")
    f.write(
        "> **Combined Reachability** counts each URL once if it was confirmed "
        "reachable by any scan type.\n\n"
    )

    return uv_total, uv_valid, sm_total, sm_reachable, tech_total


def _write_url_validation_table(
    f,
    url_val: dict[str, dict],
    all_countries: list[str],
    seed_counts: dict[str, int] | None = None,
) -> None:
    """Write the per-country URL validation table."""
    if not url_val:
        return
    f.write("## URL Validation by Country\n\n")
    f.write("| Country | Total | Valid | Invalid | Scan Period | Coverage |\n")
    f.write("|---------|-------|-------|---------|-------------|----------|\n")
    for cc in all_countries:
        if cc not in url_val:
            continue
        d = url_val[cc]
        available = (seed_counts or {}).get(cc) or d["total"]
        scan_period = _format_month_range(d.get("first_scan"), d.get("last_scan"))
        f.write(
            f"| {country_code_to_display_name(cc)} | {d['total']:,} | {d['valid']:,} | "
            f"{d['invalid']:,} | {scan_period} | "
            f"{_progress_bar(d['total'], available, 15)} |\n"
        )
    f.write("\n")
    f.write(
        "> Hover or focus any non-zero **Total**, **Valid**, or **Invalid** count "
        "to preview matching URLs. **Valid** and **Invalid** can overlap because "
        "a URL may have passed in one validation run and failed in another during "
        "the same scan period; download the CSV for the underlying evidence from "
        "[scan-progress-data.json](scan-progress-data.json).\n\n"
    )


def _write_social_media_table(
    f,
    social: dict[str, dict],
    all_countries: list[str],
    seed_counts: dict[str, int] | None = None,
) -> None:
    """Write the per-country social media scan table.

    Combines tier distribution (Twitter-only, Modern, Mixed, No Social) with
    per-platform link counts (Twitter, X, Bluesky, Mastodon) in a single
    table to avoid redundant Country, Scanned, and Reachable columns.
    A page may link to more than one platform, so platform counts can exceed
    tier counts.
    """
    if not social:
        return
    f.write("## Social Media Scan by Country\n\n")
    f.write(
        "| Country | Scanned | Available | Reachable | Twitter-only | Modern | "
        "Mixed | No Social | Twitter | X | Bluesky | Mastodon | Scan Period |\n"
    )
    f.write(
        "|---------|---------|-----------|-----------|-------------|--------|"
        "-------|-----------|---------|---|---------|----------|-------------|\n"
    )
    for cc in all_countries:
        if cc not in social:
            continue
        d = social[cc]
        available = (seed_counts or {}).get(cc, 0)
        available_str = f"{available:,}" if available else "—"
        scan_period = _format_month_range(d.get("first_scan"), d.get("last_scan"))
        f.write(
            f"| {country_code_to_display_name(cc)} | {d['total']:,} | {available_str} | {d['reachable']:,} | "
            f"{d['twitter_only']:,} | {d['modern_only']:,} | "
            f"{d['mixed']:,} | {d['no_social']:,} | "
            f"{d.get('has_twitter', 0):,} | {d.get('has_x', 0):,} | "
            f"{d.get('has_bluesky', 0):,} | {d.get('has_mastodon', 0):,} | "
            f"{scan_period} |\n"
        )
    f.write("\n")
    f.write(
        "> **Tier columns** (Twitter-only / Modern / Mixed / No Social) classify each "
        "page by its overall social media presence. **Platform columns** (Twitter / X / "
        "Bluesky / Mastodon) count pages with at least one link to that platform — "
        "a page may appear in more than one platform column.\n\n"
    )
    f.write(
        "> Hover or focus any non-zero platform count to preview matching pages. "
        "Activate the number to keep the preview open and download a CSV for that "
        "country and platform from [social-media-data.json](social-media-data.json).\n\n"
    )


def _write_technology_table(
    f, tech: dict[str, dict], all_countries: list[str]
) -> None:
    """Write the per-country technology scan table (or a placeholder)."""
    if not tech:
        f.write(
            "## Technology Scan\n\n"
            "_No technology scans have been run yet. "
            "Trigger the **Scan Technology Stack** workflow manually._\n\n"
        )
        return
    f.write("## Technology Scan by Country\n\n")
    f.write("| Country | URLs Scanned | Last Scan |\n")
    f.write("|---------|-------------|----------|\n")
    for cc in all_countries:
        if cc not in tech:
            continue
        d = tech[cc]
        last = (d["last_scan"] or "—")[:10]
        f.write(f"| {country_code_to_display_name(cc)} | {d['total']:,} | {last} |\n")
    f.write("\n")


def _write_lighthouse_table(
    f, lighthouse: dict[str, dict], all_countries: list[str]
) -> None:
    """Write the per-country Google Lighthouse scan table (or a placeholder).

    Shows average scores (×100) for Performance, Accessibility,
    Best Practices, and SEO alongside the last-scan date.
    """
    if not lighthouse:
        f.write(
            "## Lighthouse Scan\n\n"
            "_No Lighthouse scans have been run yet. "
            "Trigger the **Scan Lighthouse** workflow manually._\n\n"
        )
        return

    def _pct(val: float | None) -> str:
        return f"{val * 100:.0f}" if val is not None else "—"

    f.write("## Lighthouse Scan by Country\n\n")
    f.write(
        "| Country | URLs | Perf | A11y | Best Practices | SEO | Last Scan |\n"
    )
    f.write(
        "|---------|------|------|------|----------------|-----|----------|\n"
    )
    for cc in all_countries:
        if cc not in lighthouse:
            continue
        d = lighthouse[cc]
        last = (d["last_scan"] or "—")[:10]
        f.write(
            f"| {country_code_to_display_name(cc)} | {d['total']:,} | "
            f"{_pct(d.get('avg_performance'))} | "
            f"{_pct(d.get('avg_accessibility'))} | "
            f"{_pct(d.get('avg_best_practices'))} | "
            f"{_pct(d.get('avg_seo'))} | "
            f"{last} |\n"
        )
    f.write("\n")
    f.write(
        "> Scores are averages across all successfully audited URLs, "
        "displayed as 0–100 (multiply source values × 100).\n\n"
    )


def _write_accessibility_table(
    f, accessibility: dict[str, dict], all_countries: list[str]
) -> None:
    """Write the per-country accessibility statement scan table (or a placeholder).

    Shows the number of scanned pages, reachable pages, pages with an
    accessibility statement link, and pages where the link was found in the
    footer alongside the last-scan date.
    """
    if not accessibility:
        f.write(
            "## Accessibility Statement Scan\n\n"
            "_No accessibility statement scans have been run yet. "
            "Trigger the **Scan Accessibility Statements** workflow manually "
            "or wait for the next scheduled run._\n\n"
        )
        return

    def _pct(num: int, denom: int) -> str:
        return f"{num / denom * 100:.0f}%" if denom else "—"

    f.write("## Accessibility Statement Scan by Country\n\n")
    f.write(
        "Checks whether each government page links to an accessibility statement "
        "as required by the EU Web Accessibility Directive (Directive 2016/2102).\n\n"
    )
    f.write(
        "| Country | Scanned | Reachable | Has Statement | In Footer | Statement % | Scan Period |\n"
    )
    f.write(
        "|---------|---------|-----------|--------------|-----------|------------|-------------|\n"
    )
    for cc in all_countries:
        if cc not in accessibility:
            continue
        d = accessibility[cc]
        scan_period = _format_month_range(d.get("first_scan"), d.get("last_scan"))
        stmt_pct = _pct(d["has_statement"], d["reachable"])
        f.write(
            f"| {country_code_to_display_name(cc)} | {d['total']:,} | {d['reachable']:,} | "
            f"{d['has_statement']:,} | {d['found_in_footer']:,} | "
            f"{stmt_pct} | {scan_period} |\n"
        )
    f.write("\n")
    f.write(
        "> **Statement %** is the percentage of *reachable* pages that contain "
        "at least one link to an accessibility statement.\n\n"
    )


def _write_pending_sections(
    f,
    url_val: dict[str, dict],
    social: dict[str, dict],
) -> None:
    """Highlight countries that still need a particular scan type."""
    not_social = sorted(set(url_val) - set(social))
    not_url_val = sorted(set(social) - set(url_val))

    if not_social:
        f.write("## Countries Pending Social Media Scan\n\n")
        f.write(
            "These countries have URL validation data but have not yet been "
            "scanned for social media links:\n\n"
        )
        f.write(", ".join(f"`{cc}`" for cc in not_social) + "\n\n")

    if not_url_val:
        f.write("## Countries With Social Scan But No URL Validation\n\n")
        f.write(
            "These countries have social media scan data but no URL "
            "validation data (URL validation may have been skipped because "
            "the social scan already confirmed reachability):\n\n"
        )
        f.write(", ".join(f"`{cc}`" for cc in not_url_val) + "\n\n")


def _write_priority_guide(f) -> None:
    """Write the scan priority guide section."""
    f.write("## Scan Priority Guide\n\n")
    f.write(
        "Scans are ordered from **highest** to **lowest** priority:\n\n"
    )
    f.write(
        "1. **Social Media Scan** — runs every 3 hours; downloads and "
        "parses full pages, confirming reachability *and* detecting social "
        "links in one pass.\n"
    )
    f.write(
        "2. **Accessibility Statement Scan** — runs every 4 hours; checks "
        "whether each page links to an accessibility statement as required "
        "by the EU Web Accessibility Directive (Directive 2016/2102).\n"
    )
    f.write(
        "3. **Technology Scan** — run on demand; detects CMS, framework, "
        "and analytics platforms.\n"
    )
    f.write(
        "4. **Lighthouse Scan** — run on demand; measures performance, "
        "accessibility (WCAG), best practices, and SEO for each URL.\n"
    )
    f.write(
        "5. **URL Validation** — runs every 6 hours in the background; "
        "a lightweight redirect/404 check that is **automatically skipped** "
        "for URLs already confirmed reachable by a higher-priority scan "
        "within the last 30 days.\n"
    )
    f.write("\n")
    f.write(
        "> **Tip:** Run a social media scan first for a new country — "
        "this simultaneously validates all URLs *and* collects social "
        "media data, avoiding a separate URL-only pass.\n\n"
    )
    f.write("### Why are Social Media and URL Validation counts different?\n\n")
    f.write(
        "The Social Media scanner runs more frequently than URL Validation "
        "and therefore covers more URLs over time.  Because the Social Media "
        "scanner already confirms whether each URL is reachable, the URL "
        "Validation job automatically *skips* any page already confirmed "
        "reachable within the last 30 days.  As a result the two individual "
        "scan counts do **not** simply add up — each scan covers a different "
        "subset of pages.\n\n"
        "**What URL Validation adds beyond Social Media:**\n\n"
        "- **Failure tracking** — records how many consecutive times each URL "
        "has failed; URLs that fail twice are removed from future scans to "
        "keep the seed file accurate.\n"
        "- **Redirect-chain capture** — follows and stores the full redirect "
        "chain so the seed file can be updated with the final canonical URL.\n"
        "- **Lightweight fallback** — a fast HTTP-only check for URLs that the "
        "Social Media scanner has not yet reached, without the overhead of "
        "downloading and parsing the full page.\n\n"
        "The **Combined Reachability** row at the top of the coverage table "
        "counts each URL once if it was confirmed reachable by *either* scan, "
        "giving the most accurate picture of overall URL health.\n"
    )


def _write_report(
    conn: sqlite3.Connection,
    output_path: Path,
    generated_at: str,
    seed_counts: dict[str, int] | None = None,
    data_path: Path | None = None,
) -> None:
    """Query the database and write the Markdown report."""

    url_val = _query_url_validation(conn)
    url_val_detail = _query_url_validation_detail(conn)
    social = _query_social_media(conn)
    tech = _query_technology(conn)
    lighthouse = _query_lighthouse(conn)
    accessibility = _query_accessibility(conn)
    combined_reachable = _query_combined_reachability(conn)

    all_countries = sorted(set(url_val) | set(social) | set(tech) | set(lighthouse) | set(accessibility))

    with output_path.open("w", encoding="utf-8") as f:
        f.write("---\ntitle: Scan Progress Report\nlayout: page\n---\n\n")
        f.write(f"_Generated: {generated_at}_\n\n")
        f.write(
            "This report tracks how far along each scan type is across all "
            "countries. It is regenerated automatically after every scan run.\n\n"
        )

        totals = _write_overall_coverage(f, url_val, social, tech, lighthouse, seed_counts, combined_reachable, accessibility)
        uv_total, uv_valid, sm_total, sm_reachable, tech_total = totals

        _write_url_validation_table(f, url_val, all_countries, seed_counts)
        _write_social_media_table(f, social, all_countries, seed_counts)
        _write_technology_table(f, tech, all_countries)
        _write_lighthouse_table(f, lighthouse, all_countries)
        _write_accessibility_table(f, accessibility, all_countries)
        _write_pending_sections(f, url_val, social)
        _write_priority_guide(f)

    if data_path is not None:
        payload = {
            "generated_at": generated_at,
            "url_validation_drilldowns": url_val_detail,
        }
        data_path.parent.mkdir(parents=True, exist_ok=True)
        data_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )

    lh_total = sum(d["total"] for d in lighthouse.values())
    a11y_total = sum(d["total"] for d in accessibility.values())
    combined_total = sum(d["confirmed"] for d in combined_reachable.values())
    # Print console summary
    total_available = sum((seed_counts or {}).values())
    print("\n" + "=" * 70)
    print("SCAN PROGRESS SUMMARY")
    print("=" * 70)
    if combined_total:
        print(f"Combined       : {combined_total:,} URLs confirmed reachable (URL Validation + Social Media)")
    print(f"URL Validation : {uv_valid:,} / {uv_total:,} URLs valid")
    if total_available:
        print(f"Social Media   : {sm_total:,} / {total_available:,} available pages scanned "
              f"({sm_reachable:,} reachable)")
    else:
        print(f"Social Media   : {sm_reachable:,} / {sm_total:,} URLs reachable")
    print(f"Technology     : {tech_total:,} URLs scanned")
    print(f"Lighthouse     : {lh_total:,} URLs scanned")
    print(f"Accessibility  : {a11y_total:,} URLs scanned")
    print(f"Countries      : {len(all_countries)} with data")
    print("=" * 70)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate a multi-scan progress report showing URL validation, "
            "social media scan, and technology scan coverage."
        )
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file path for the report (default: docs/scan-progress.md)",
        type=Path,
        default=Path("docs/scan-progress.md"),
    )
    parser.add_argument(
        "--db",
        help="Database file path (overrides settings)",
        type=Path,
    )
    parser.add_argument(
        "--update-index",
        help=(
            "Path to docs/index.md (or similar) whose "
            "<!-- SCAN_PROGRESS_START/END --> block should be updated with "
            "the latest scan summary (default: docs/index.md)"
        ),
        type=Path,
        nargs="?",
        const=Path("docs/index.md"),
        default=None,
        metavar="INDEX_PATH",
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
    parser.add_argument(
        "--data",
        help="Output file path for scan-progress drilldown JSON (default: docs/scan-progress-data.json)",
        type=Path,
        default=Path("docs/scan-progress-data.json"),
    )

    args = parser.parse_args()

    if args.db:
        db_path = args.db
    else:
        settings = load_settings()
        db_path = Path(settings.metadata_db_url.replace("sqlite:///", ""))

    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        generate_progress_report(db_path, args.output, args.seeds_dir, args.data)
        if args.update_index is not None:
            update_index_progress(args.update_index, db_path, args.seeds_dir)
    except Exception as exc:
        print(f"Error generating report: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
