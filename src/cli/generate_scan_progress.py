"""CLI tool to generate a multi-scan progress report from the database.

Produces a Markdown summary that shows how far along each scan type
(URL validation, social media, technology) is across all countries,
so stakeholders can see overall coverage at a glance.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# Maximum number of history snapshots to retain (one per day → ~3 months).
_HISTORY_MAX_ENTRIES: int = 90

# Workflow file name for each scan type, used for auto-prioritisation output.
_SCAN_WORKFLOW_FILES: dict[str, str] = {
    "accessibility": "scan-accessibility.yml",
    "social": "scan-social-media.yml",
    "technology": "scan-technology.yml",
    "third_party_js": "scan-third-party-js.yml",
    "lighthouse": "scan-lighthouse.yml",
}

from src.lib.country_utils import country_code_to_display_name, country_filename_to_code
from src.lib.settings import load_settings
from src.services.organization_mapper import load_domain_to_parent_map, extract_domain_from_url


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
    history_path: Path | None = None,
    parent_institutions_csv_path: Path | None = None,
) -> list[dict]:
    """Generate a comprehensive scan-progress report from the database.

    Args:
        db_path: Path to the SQLite metadata database.
        output_path: Output file path for the Markdown report.
        toon_seeds_dir: Directory containing ``*.toon`` seed files.  When
            provided the report will include "X of Y available pages scanned"
            coverage figures in the overall-coverage section.
        data_path: Optional path for the scan-progress drilldown JSON.
        history_path: Optional path to the daily-snapshot history JSON file.
            When provided a new snapshot is appended and the trend table is
            included in the report.
        parent_institutions_csv_path: Optional path for a CSV file listing all
            parent institutions ranked by scan coverage.

    Returns:
        The updated history list (oldest first), or an empty list when
        *history_path* is ``None``.
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
                    {
                        "generated_at": generated_at,
                        "url_validation_drilldowns": {},
                        "parent_institutions": [],
                    },
                    ensure_ascii=True,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
        print(f"Report generated (empty): {output_path}")
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    seed_counts = _count_toon_seed_urls(toon_seeds_dir) if toon_seeds_dir else {}

    try:
        history = _write_report(
            conn, output_path, generated_at, seed_counts, data_path, toon_seeds_dir,
            history_path=history_path,
            parent_institutions_csv_path=parent_institutions_csv_path,
        )
    finally:
        conn.close()

    print(f"Report generated: {output_path}")
    return history


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
                f"| Accessibility Statements | {a11y_total:,} domains | "
                f"{_progress_bar(a11y_total, denom)} |\n"
            )
        buf.write("\n")
        _n = len(all_countries)
        _country_label = f"**{_n}** {'country' if _n == 1 else 'countries'}"
        if total_available:
            buf.write(
                f"Scan data **{combined_total:,}** of **{total_available:,}** available pages confirmed reachable. "
                "See the [Scan Progress Report](scan-progress.md) for full details.\n\n"
            )
        else:
            buf.write(

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

    Counts distinct domains (hostnames) rather than individual URLs so that
    the multiple probe paths scanned per domain (e.g. /accessibility,
    /accessibility-statement) are collapsed to a single domain entry.  A
    domain is counted as reachable / has_statement / found_in_footer if *any*
    of its scanned URLs produced that result.
    """
    result: dict[str, dict] = {}
    for row in conn.execute(
        """
        WITH domain_rows AS (
            SELECT country_code,
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
        SELECT country_code,
               COUNT(*)              AS total,
               SUM(is_reachable)     AS reachable,
               SUM(has_statement)    AS has_statement,
               SUM(found_in_footer)  AS found_in_footer,
               MIN(first_scan)       AS first_scan,
               MAX(last_scan)        AS last_scan
        FROM domain_rows
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


def _query_third_party_js(conn: sqlite3.Connection) -> dict[str, dict]:
    """Return per-country third-party JavaScript scan stats from the database."""
    result: dict[str, dict] = {}
    for row in conn.execute(
        """
        SELECT country_code,
               COUNT(DISTINCT url)                                                AS total,
               COUNT(DISTINCT CASE WHEN is_reachable = 1 THEN url ELSE NULL END) AS reachable,
               MAX(scanned_at)                                                    AS last_scan
        FROM url_third_party_js_results
        GROUP BY country_code
        ORDER BY country_code
        """
    ):
        result[row["country_code"]] = dict(row)
    return result


def _query_social_media_by_parent_institution(
    conn: sqlite3.Connection,
    domain_to_parent: dict[str, str],
) -> dict[str, dict]:
    """Return per-parent-institution social media scan stats from the database.

    Maps URLs to parent institutions using the domain_to_parent mapping,
    then aggregates counts by parent_institution.

    Returns a dict mapping parent_institution → scan statistics.
    """
    result: dict[str, dict] = {}

    # Query all distinct URLs with their scan stats
    rows = conn.execute(
        """
        SELECT DISTINCT
               url,
               COUNT(*) FILTER (WHERE is_reachable = 1) as reachable_count,
               COUNT(*) as total_scans
        FROM url_social_media_results
        GROUP BY url
        """
    ).fetchall()

    for url, reachable_count, total_scans in rows:
        domain = extract_domain_from_url(url)
        parent_institution = domain_to_parent.get(domain, "Other") if domain else "Other"

        if parent_institution not in result:
            result[parent_institution] = {
                "total_urls": 0,
                "reachable_urls": 0,
            }

        result[parent_institution]["total_urls"] += 1
        if reachable_count > 0:
            result[parent_institution]["reachable_urls"] += 1

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
    third_party_js: dict[str, dict] | None = None,
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
    tpjs_total = sum(d["total"] for d in (third_party_js or {}).values())
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
        f"{_progress_bar(tech_total, denom)} |\n"
    )
    f.write(
        f"| Lighthouse | {lh_total:,} scanned | "
        f"{avail_str} | "
        f"{_progress_bar(lh_total, denom)} |\n"
    )
    f.write(
        f"| Accessibility Statements | {a11y_total:,} domains | "
        f"{avail_str} | "
        f"{_progress_bar(a11y_total, denom)} |\n"
    )
    f.write(
        f"| Third-Party JS | {tpjs_total:,} scanned | "
        f"{avail_str} | "
        f"{_progress_bar(tpjs_total, denom)} |\n"
    )
    f.write("\n")
    f.write(
        "> **Combined Reachability** counts each URL once if it was confirmed "
        "reachable by any scan type.\n\n"
    )

    return uv_total, uv_valid, sm_total, sm_reachable, tech_total, tpjs_total


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

    Shows the number of distinct domains scanned, domains where at least one
    URL was reachable, domains that have an accessibility statement link, and
    domains where the link was found in the footer, alongside the last-scan date.
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
        "Checks whether each institution's website links to an accessibility statement. "
        "Each row counts distinct domains (one per institution), not individual URLs.\n\n"
    )
    f.write(
        "| Country | Domains | Reachable | Has Statement | In Footer | Statement % | Scan Period |\n"
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
        "> **Statement %** is the percentage of *reachable* domains that contain "
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


def _write_parent_institutions_csv(
    parent_institutions: dict[str, dict], csv_path: Path
) -> None:
    """Write top parent institutions to a CSV file.

    Args:
        parent_institutions: Mapping from parent institution name to stats dict
            (``total_urls``, ``reachable_urls``) as returned by
            :func:`_query_social_media_by_parent_institution`.
        csv_path: Destination path for the CSV file.

    The CSV uses UTF-8 encoding with a BOM so it opens correctly in
    spreadsheet applications.  All institutions are included (not just
    the top 50 shown in the Markdown table).
    """
    sorted_institutions = sorted(
        parent_institutions.items(),
        key=lambda x: x[1]["total_urls"],
        reverse=True,
    )
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["rank", "parent_institution", "urls_scanned", "reachable", "coverage_pct"],
        lineterminator="\r\n",
    )
    writer.writeheader()
    for rank, (parent_inst, stats) in enumerate(sorted_institutions, start=1):
        total = stats["total_urls"]
        reachable = stats["reachable_urls"]
        coverage = f"{reachable / total * 100:.1f}" if total > 0 else ""
        writer.writerow(
            {
                "rank": rank,
                "parent_institution": parent_inst,
                "urls_scanned": total,
                "reachable": reachable,
                "coverage_pct": coverage,
            }
        )
    # Write UTF-8 BOM so Excel opens the file correctly without import wizard.
    csv_path.write_bytes(b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8"))


def _write_top_parent_institutions(
    f, parent_institutions: dict[str, dict], csv_filename: str = "scan-progress-parent-institutions.csv"
) -> None:
    """Write a breakdown of top parent institutions by survey coverage.

    Shows aggregated scan coverage across all institutions, grouped by their
    parent_institution affiliations (e.g., University of California System,
    California State University System).

    Helps identify which networks of institutions have been scanned vs. still
    pending, and provides visibility into concentration of scan coverage.
    """
    if not parent_institutions:
        return

    # Sort by total URLs scanned (descending)
    sorted_institutions = sorted(
        parent_institutions.items(),
        key=lambda x: x[1]["total_urls"],
        reverse=True
    )

    f.write("## Top Parent Institutions by Scan Coverage\n\n")
    f.write(
        "Aggregated results across all institutions grouped by parent organization "
        "(system affiliation, network, etc.):\n\n"
    )
    f.write(
        "| Parent Institution | URLs Scanned | Reachable | Coverage |\n"
    )
    f.write("|---|---|---|---|\n")

    for parent_inst, stats in sorted_institutions[:50]:  # Top 50
        total = stats["total_urls"]
        reachable = stats["reachable_urls"]
        pct = f"{reachable / total * 100:.0f}%" if total > 0 else "—"
        f.write(
            f"| {parent_inst} | {total:,} | {reachable:,} | {pct} |\n"
        )

    f.write("\n")
    f.write(
        "> This grouping organizes individual institution domains under their parent "
        "systems or networks (e.g., \"University of California\" spans UC Berkeley, "
        "UCLA, UC San Diego, etc.). Useful for identifying coverage gaps at the "
        "system level.\n\n"
    )
    f.write(
        f"📥 [Download full parent institutions list (CSV)]({csv_filename})\n\n"
    )


def _write_third_party_js_table(
    f, third_party_js: dict[str, dict], all_countries: list[str]
) -> None:
    """Write the per-country third-party JavaScript scan table (or a placeholder)."""
    if not third_party_js:
        f.write(
            "## Third-Party JavaScript Scan\n\n"
            "_No third-party JavaScript scans have been run yet. "
            "Trigger the **Scan Third-Party JavaScript** workflow or wait "
            "for the next scheduled run._\n\n"
        )
        return
    f.write("## Third-Party JavaScript Scan by Country\n\n")
    f.write("| Country | URLs Scanned | Last Scan |\n")
    f.write("|---------|-------------|----------|\n")
    for cc in all_countries:
        if cc not in third_party_js:
            continue
        d = third_party_js[cc]
        last = (d["last_scan"] or "—")[:10]
        f.write(f"| {country_code_to_display_name(cc)} | {d['total']:,} | {last} |\n")
    f.write("\n")


def _write_coverage_trend_table(f, history: list[dict]) -> None:
    """Write a table showing coverage % for each scan type over recent days.

    Args:
        f: File-like object to write to.
        history: List of daily snapshot dicts, oldest first.  Each dict must
            contain at least ``date`` and the per-scan ``*_pct`` keys.
    """
    if not history:
        return

    # Show at most the 14 most recent entries (newest last → display newest first).
    recent = history[-14:]
    recent_reversed = list(reversed(recent))

    f.write("## Coverage Trend (Last 14 Days)\n\n")
    f.write(
        "Coverage percentage for each scan type, updated daily. "
        "When a scan type is far behind the others it will be automatically "
        "prioritised for an extra run.\n\n"
    )
    f.write(
        "| Date | Accessibility | Social Media | Technology"
        " | Third-Party JS | Lighthouse |\n"
    )
    f.write(
        "|------|--------------|--------------|------------|"
        "----------------|------------|\n"
    )
    for entry in recent_reversed:
        date = entry.get("date", "—")
        a11y = entry.get("accessibility_pct")
        social = entry.get("social_pct")
        tech = entry.get("technology_pct")
        tpjs = entry.get("third_party_js_pct")
        lh = entry.get("lighthouse_pct")

        def _format_pct(v: float | None) -> str:
            return f"{v:.1f}%" if v is not None else "—"

        f.write(
            f"| {date} | {_format_pct(a11y)} | {_format_pct(social)} | {_format_pct(tech)}"
            f" | {_format_pct(tpjs)} | {_format_pct(lh)} |\n"
        )
    f.write("\n")
    f.write(
        "> Percentages are calculated as *pages scanned* ÷ *total pages available* × 100. "
        "Lighthouse scans take longer per URL and may lag other scan types; "
        "the auto-prioritisation step compensates by triggering extra runs for the "
        "most-lagging scan each day.\n\n"
    )


def _update_progress_history(
    history_path: Path,
    snapshot: dict,
    max_entries: int = _HISTORY_MAX_ENTRIES,
) -> list[dict]:
    """Append *snapshot* to the history file and return the updated list.

    Reads the existing history JSON (an array of snapshot dicts), appends the
    new snapshot for today (replacing any existing entry for the same date),
    trims to at most *max_entries* entries (oldest first), and writes the
    result back to *history_path*.

    Args:
        history_path: Path to the JSON history file.
        snapshot: Dict with at minimum a ``date`` key (``YYYY-MM-DD``).
        max_entries: Maximum number of daily snapshots to retain.

    Returns:
        The updated history list (oldest first).
    """
    history: list[dict] = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
            if not isinstance(history, list):
                history = []
        except (json.JSONDecodeError, OSError):
            history = []

    today = snapshot.get("date", "")
    # Replace any existing entry for the same date.
    history = [e for e in history if e.get("date") != today]
    history.append(snapshot)
    # Keep oldest-first; trim to max_entries.
    history = sorted(history, key=lambda e: e.get("date", ""))[-max_entries:]

    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        json.dumps(history, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return history


def _recommend_lagging_workflow(history: list[dict]) -> str | None:
    """Return the workflow filename for the most-lagging scan, or ``None``.

    Inspects the most recent history snapshot and compares coverage percentages
    across the five scheduled scan types.  If the gap between the highest and
    lowest coverage is greater than 10 percentage points, the workflow file
    name for the lowest-coverage scan is returned so the caller can trigger an
    extra run to help close the gap.

    Returns ``None`` when there is no meaningful gap or the history is empty.

    Args:
        history: List of daily snapshot dicts, oldest first.

    Returns:
        A workflow file name such as ``"scan-social-media.yml"``, or ``None``.
    """
    if not history:
        return None

    latest = history[-1]
    pcts = {
        key: latest.get(f"{key}_pct", 0.0) or 0.0
        for key in _SCAN_WORKFLOW_FILES
    }

    max_pct = max(pcts.values())
    if max_pct <= 0:
        return None

    min_key = min(pcts, key=lambda k: pcts[k])
    min_pct = pcts[min_key]

    if (max_pct - min_pct) > 10.0:
        return _SCAN_WORKFLOW_FILES[min_key]
    return None


def _write_priority_guide(f) -> None:
    """Write the scan priority guide section."""
    f.write("## Scan Priority Guide\n\n")
    f.write(
        "Scans are ordered from **highest** to **lowest** priority:\n\n"
    )
    f.write(
        "1. **Social Media Scan** — runs every 2 hours; downloads and "
        "parses full pages, confirming reachability *and* detecting social "
        "links in one pass.\n"
    )
    f.write(
        "2. **Accessibility Statement Scan** — runs every 4 hours; checks "
        "whether each page links to an accessibility statement as required "
        "by the EU Web Accessibility Directive (Directive 2016/2102).\n"
    )
    f.write(
        "3. **Technology Scan** — runs every 4 hours; detects CMS, framework, "
        "and analytics platforms.\n"
    )
    f.write(
        "4. **Third-Party JavaScript Scan** — runs every 6 hours; identifies "
        "externally hosted scripts, CDNs, and third-party services.\n"
    )
    f.write(
        "5. **Lighthouse Scan** — runs once per day; measures performance, "
        "accessibility (WCAG), best practices, and SEO for each URL. "
        "Each URL takes ~20–30 s so coverage builds gradually.\n"
    )
    f.write(
        "6. **URL Validation** — runs every 2 hours in the background; "
        "a lightweight redirect/404 check that is **automatically skipped** "
        "for URLs already confirmed reachable by a higher-priority scan "
        "within the last 30 days.\n"
    )
    f.write("\n")
    f.write(
        "> **Auto-prioritisation:** when any scan type is more than 10 percentage "
        "points behind the leader, the daily report-generation step automatically "
        "dispatches an extra run of that workflow to help close the gap.\n\n"
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
    toon_seeds_dir: Path | None = None,
    history_path: Path | None = None,
    parent_institutions_csv_path: Path | None = None,
) -> list[dict]:
    """Query the database and write the Markdown report.

    Returns the updated history list (oldest first); empty when no
    *history_path* is provided.
    """

    url_val = _query_url_validation(conn)
    url_val_detail = _query_url_validation_detail(conn)
    social = _query_social_media(conn)
    tech = _query_technology(conn)
    lighthouse = _query_lighthouse(conn)
    accessibility = _query_accessibility(conn)
    third_party_js = _query_third_party_js(conn)
    combined_reachable = _query_combined_reachability(conn)

    # Load parent institution mapping if toon_seeds_dir is available
    domain_to_parent = {}
    parent_institutions = {}
    if toon_seeds_dir:
        domain_to_parent = load_domain_to_parent_map(toon_seeds_dir)
        parent_institutions = _query_social_media_by_parent_institution(conn, domain_to_parent)

    all_countries = sorted(
        set(url_val) | set(social) | set(tech)
        | set(lighthouse) | set(accessibility) | set(third_party_js)
    )

    total_available = sum((seed_counts or {}).values())
    denom = total_available or 1

    lh_total = sum(d["total"] for d in lighthouse.values())
    a11y_total = sum(d["total"] for d in accessibility.values())
    tpjs_total = sum(d["total"] for d in third_party_js.values())
    combined_total = sum(d["confirmed"] for d in combined_reachable.values())

    # Build today's history snapshot.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sm_total = sum(d["total"] for d in social.values())
    tech_total = sum(d["total"] for d in tech.values())
    snapshot: dict = {
        "date": today,
        "total_available": total_available,
        "accessibility_count": a11y_total,
        "accessibility_pct": round(a11y_total / denom * 100, 1),
        "social_count": sm_total,
        "social_pct": round(sm_total / denom * 100, 1),
        "technology_count": tech_total,
        "technology_pct": round(tech_total / denom * 100, 1),
        "third_party_js_count": tpjs_total,
        "third_party_js_pct": round(tpjs_total / denom * 100, 1),
        "lighthouse_count": lh_total,
        "lighthouse_pct": round(lh_total / denom * 100, 1),
    }

    # Update history file and get the full list for the trend table.
    history: list[dict] = []
    if history_path is not None:
        history = _update_progress_history(history_path, snapshot)

    with output_path.open("w", encoding="utf-8") as f:
        f.write("---\ntitle: Scan Progress Report\nlayout: page\n---\n\n")
        f.write(f"_Generated: {generated_at}_\n\n")
        f.write(
            "This report tracks how far along each scan type is across all "
            "countries. It is regenerated automatically after every scan run.\n\n"
        )

        totals = _write_overall_coverage(
            f, url_val, social, tech, lighthouse, seed_counts,
            combined_reachable, accessibility, third_party_js,
        )
        uv_total, uv_valid, sm_total, sm_reachable, tech_total, tpjs_total = totals

        # Write trend table when history data is available.
        if history:
            _write_coverage_trend_table(f, history)

        # Write parent institution breakdown if available
        if parent_institutions:
            csv_filename = (
                parent_institutions_csv_path.name
                if parent_institutions_csv_path is not None
                else "scan-progress-parent-institutions.csv"
            )
            _write_top_parent_institutions(f, parent_institutions, csv_filename)

        _write_url_validation_table(f, url_val, all_countries, seed_counts)
        _write_social_media_table(f, social, all_countries, seed_counts)
        _write_technology_table(f, tech, all_countries)
        _write_lighthouse_table(f, lighthouse, all_countries)
        _write_accessibility_table(f, accessibility, all_countries)
        _write_third_party_js_table(f, third_party_js, all_countries)
        _write_pending_sections(f, url_val, social)
        _write_priority_guide(f)

    if data_path is not None:
        # Build a serializable list for parent_institutions
        parent_institutions_list = [
            {
                "rank": rank,
                "parent_institution": name,
                "urls_scanned": stats["total_urls"],
                "reachable": stats["reachable_urls"],
                "coverage_pct": (
                    round(stats["reachable_urls"] / stats["total_urls"] * 100, 1)
                    if stats["total_urls"] > 0
                    else None
                ),
            }
            for rank, (name, stats) in enumerate(
                sorted(
                    parent_institutions.items(),
                    key=lambda x: x[1]["total_urls"],
                    reverse=True,
                ),
                start=1,
            )
        ]
        payload = {
            "generated_at": generated_at,
            "url_validation_drilldowns": url_val_detail,
            "parent_institutions": parent_institutions_list,
        }
        data_path.parent.mkdir(parents=True, exist_ok=True)
        data_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )

    if parent_institutions_csv_path is not None and parent_institutions:
        _write_parent_institutions_csv(parent_institutions, parent_institutions_csv_path)
        print(
            f"Parent institutions CSV written: {parent_institutions_csv_path} "
            f"({len(parent_institutions)} institutions)"
        )

    # Print console summary
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
    print(f"Third-Party JS : {tpjs_total:,} URLs scanned")
    print(f"Accessibility  : {a11y_total:,} domains scanned")
    print(f"Countries      : {len(all_countries)} with data")
    print("=" * 70)

    return history


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
    parser.add_argument(
        "--history",
        help=(
            "Path to the daily-snapshot history JSON file "
            "(default: docs/scan-progress-history.json). "
            "When provided a snapshot is appended and the trend table is "
            "included in the report."
        ),
        type=Path,
        default=Path("docs/scan-progress-history.json"),
        metavar="HISTORY_PATH",
    )
    parser.add_argument(
        "--recommend-workflow",
        help=(
            "If a scan type is more than 10%% behind the leader, write its "
            "workflow filename to this file so the caller can trigger an extra run."
        ),
        type=Path,
        default=None,
        metavar="RECOMMEND_PATH",
    )
    parser.add_argument(
        "--parent-institutions-csv",
        help=(
            "Output path for the parent institutions CSV file "
            "(default: docs/scan-progress-parent-institutions.csv)"
        ),
        type=Path,
        default=Path("docs/scan-progress-parent-institutions.csv"),
        metavar="PARENT_INST_CSV_PATH",
    )

    args = parser.parse_args()

    if args.db:
        db_path = args.db
    else:
        settings = load_settings()
        db_path = Path(settings.metadata_db_url.replace("sqlite:///", ""))

    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        history = generate_progress_report(
            db_path,
            args.output,
            args.seeds_dir,
            args.data,
            args.history,
            parent_institutions_csv_path=args.parent_institutions_csv,
        )
        if args.update_index is not None:
            update_index_progress(args.update_index, db_path, args.seeds_dir)
        if args.recommend_workflow is not None:
            workflow = _recommend_lagging_workflow(history)
            if workflow:
                args.recommend_workflow.parent.mkdir(parents=True, exist_ok=True)
                args.recommend_workflow.write_text(workflow + "\n", encoding="utf-8")
                print(f"Lagging scan identified: {workflow}")
            else:
                print("All scans are within 10 pp of each other — no extra run needed.")
    except Exception as exc:
        print(f"Error generating report: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
