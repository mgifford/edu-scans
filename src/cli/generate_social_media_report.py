"""CLI tool to generate the social media scanning stats page.

Queries the metadata database for aggregate social media scan statistics
and updates ``docs/social-media.md`` with a live stats block between
``<!-- SOCIAL_MEDIA_STATS_START -->`` and ``<!-- SOCIAL_MEDIA_STATS_END -->``
markers.  A summary JSON data file (``docs/social-media-data.json``) is also
written so that external tools can access the machine-readable results.  This
file is uploaded as a workflow artifact rather than committed to the repository
(it can exceed GitHub's 100 MB file-size limit at scale).
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.lib.country_utils import country_code_to_display_name, country_filename_to_code
from src.lib.settings import load_settings


# ---------------------------------------------------------------------------
# HTML comment markers
# ---------------------------------------------------------------------------

_STATS_MARKER_START = "<!-- SOCIAL_MEDIA_STATS_START -->"
_STATS_MARKER_END = "<!-- SOCIAL_MEDIA_STATS_END -->"


# Country code for the Top 100 TOON seed file.
_TOP100_COUNTRY_CODE = "USA_EDU_TOP100"

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


def _load_top100_institution_metadata(toon_seeds_dir: Path) -> list[dict]:
    """Return per-institution metadata from the Top 100 TOON seed file.

    Reads ``usa-edu-top100.toon`` from *toon_seeds_dir* (if it exists) and
    returns a list of dicts — one per domain entry — sorted ascending by
    ``ranking``.  Each dict contains at minimum:

    - ``rank`` (int): numeric position in the ranking list.
    - ``institution_name`` (str): display name for the institution.
    - ``canonical_domain`` (str): primary domain.
    - ``url`` (str): first page URL extracted from ``pages``, or an empty
      string when the pages list is absent.

    Returns an empty list when the TOON file does not exist or cannot be
    parsed.

    Args:
        toon_seeds_dir: Directory containing ``*.toon`` seed files.

    Returns:
        List of institution metadata dicts sorted by rank ascending.
    """
    if not toon_seeds_dir or not toon_seeds_dir.is_dir():
        return []

    toon_path = toon_seeds_dir / "usa-edu-top100.toon"
    if not toon_path.exists():
        return []

    try:
        data = json.loads(toon_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    institutions: list[dict] = []
    for entry in data.get("domains", []):
        ranking = entry.get("ranking")
        if ranking is None:
            continue
        pages = entry.get("pages", [])
        url = pages[0].get("url", "") if pages else ""
        # Use the rankings CSV name when available; fall back to the
        # master-TOON institution_name.
        name = entry.get("ranking_institution_name") or entry.get("institution_name", "")
        institutions.append({
            "rank": int(ranking),
            "institution_name": name,
            "canonical_domain": entry.get("canonical_domain", ""),
            "url": url,
        })

    institutions.sort(key=lambda r: r["rank"])
    return institutions


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _query_summary(conn: sqlite3.Connection) -> dict:
    """Return aggregate social media scan totals from the database.

    Each URL may appear in multiple scan batches (one row per (url, scan_id)).
    All per-URL counts use COUNT(DISTINCT CASE WHEN … THEN url END) so that a
    URL is counted at most once regardless of how many scan batches it appears
    in.
    """
    row = conn.execute(
        """
        SELECT
            COUNT(DISTINCT scan_id)                                                     AS total_batches,
            COUNT(DISTINCT url)                                                         AS total_scanned,
            COUNT(DISTINCT CASE WHEN is_reachable = 1      THEN url ELSE NULL END)     AS total_reachable,
            COUNT(DISTINCT CASE WHEN twitter_links != '[]' THEN url ELSE NULL END)     AS twitter_pages,
            COUNT(DISTINCT CASE WHEN x_links       != '[]' THEN url ELSE NULL END)     AS x_pages,
            COUNT(DISTINCT CASE WHEN bluesky_links  != '[]' THEN url ELSE NULL END)    AS bluesky_pages,
            COUNT(DISTINCT CASE WHEN mastodon_links != '[]' THEN url ELSE NULL END)    AS mastodon_pages,
            COUNT(DISTINCT CASE WHEN facebook_links != '[]' THEN url ELSE NULL END)  AS facebook_pages,
            COUNT(DISTINCT CASE WHEN linkedin_links != '[]' THEN url ELSE NULL END)  AS linkedin_pages,
            MIN(scanned_at)                                                             AS first_scan,
            MAX(scanned_at)                                                             AS last_scan
        FROM url_social_media_results
        """
    ).fetchone()
    if row is None:
        return {}
    return dict(row)


_TWITTER_X_URL_SAMPLE_LIMIT = 25
"""Maximum number of Twitter/X site URLs to embed per country in the page.

URLs are embedded as a JSON blob in the generated HTML so the browser can
display them in accessible tooltips (< 25 sites) or a short sample list
(≥ 25 sites).  Capping at 25 keeps the page size manageable for countries
with hundreds or thousands of Twitter/X-linked pages — the full list is
always available in the machine-readable social-media-data.json file.
"""


def _query_twitter_x_urls_by_country(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Return a mapping of country_code → list of URLs with Twitter or X links.

    Each URL appears at most once per country, even if it was scanned in
    multiple batches.  Only URLs with at least one twitter.com or x.com link
    are included.  At most :data:`_TWITTER_X_URL_SAMPLE_LIMIT` URLs are
    returned per country so that the embedded JSON blob stays small even for
    countries with hundreds of Twitter/X-linked pages.

    The result is used by the report's JavaScript to populate per-country
    Twitter/X site lists in accessible tooltips (< 25 sites) or a short
    sample list inside a ``<details>`` widget (≥ 25 sites).
    """
    rows = conn.execute(
        """
        SELECT DISTINCT country_code, url
        FROM url_social_media_results
        WHERE twitter_links != '[]' OR x_links != '[]'
        ORDER BY country_code, url
        """
    ).fetchall()
    result: dict[str, list[str]] = {}
    for row in rows:
        cc = row["country_code"]
        url = row["url"]
        bucket = result.setdefault(cc, [])
        if len(bucket) < _TWITTER_X_URL_SAMPLE_LIMIT:
            bucket.append(url)
    return result


_PLATFORM_LINK_COLUMNS = {
    "twitter": "twitter_links",
    "x": "x_links",
    "bluesky": "bluesky_links",
    "mastodon": "mastodon_links",
    "facebook": "facebook_links",
    "linkedin": "linkedin_links",
}


def _parse_link_list(raw_value: str | None) -> list[str]:
    """Return a deduplicated list of platform URLs from JSON text."""
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    links: list[str] = []
    for item in parsed:
        if not isinstance(item, str) or not item:
            continue
        if item not in links:
            links.append(item)
    return links


def _query_platform_drilldowns_by_country(
    conn: sqlite3.Connection,
) -> dict[str, dict[str, list[dict[str, object]]]]:
    """Return per-country platform drilldowns for interactive table cells.

    Each platform record contains the scanned page URL and the distinct
    detected platform-profile URLs found on that page. Pages are deduplicated
    per country and platform across scan batches so the drilldowns stay aligned
    with the report's ``COUNT(DISTINCT url)`` totals.
    """
    column_sql = ", ".join(_PLATFORM_LINK_COLUMNS.values())
    rows = conn.execute(
        f"""
        SELECT country_code, url, {column_sql}
        FROM url_social_media_results
        ORDER BY country_code, url, scanned_at DESC
        """
    ).fetchall()

    grouped: dict[str, dict[str, dict[str, dict[str, object]]]] = {}
    for row in rows:
        country_code = row["country_code"]
        country_bucket = grouped.setdefault(
            country_code,
            {platform: {} for platform in _PLATFORM_LINK_COLUMNS},
        )
        page_url = row["url"]

        for platform, column in _PLATFORM_LINK_COLUMNS.items():
            detected_links = _parse_link_list(row[column])
            if not detected_links:
                continue

            page_entry = country_bucket[platform].setdefault(
                page_url,
                {"page_url": page_url, "detected_links": []},
            )
            existing_links = page_entry["detected_links"]
            for link in detected_links:
                if link not in existing_links:
                    existing_links.append(link)

    result: dict[str, dict[str, list[dict[str, object]]]] = {}
    for country_code in sorted(grouped):
        result[country_code] = {}
        for platform in _PLATFORM_LINK_COLUMNS:
            result[country_code][platform] = sorted(
                grouped[country_code][platform].values(),
                key=lambda item: str(item["page_url"]),
            )
    return result


def _query_metric_drilldowns_by_country(
    conn: sqlite3.Connection,
) -> dict[str, dict[str, list[dict[str, object]]]]:
    """Return per-country drilldowns for social country-table metrics."""
    column_sql = ", ".join(_PLATFORM_LINK_COLUMNS.values())
    rows = conn.execute(
        f"""
        SELECT
            country_code,
            url,
            is_reachable,
            social_tier,
            scanned_at,
            {column_sql}
        FROM url_social_media_results
        ORDER BY country_code, url, scanned_at DESC
        """
    ).fetchall()

    grouped: dict[str, dict[str, list[dict[str, object]]]] = {}
    seen_by_metric: dict[str, set[tuple[str, str]]] = {
        "scanned": set(),
        "reachable": set(),
        "no_social": set(),
        "legacy_only": set(),
        "modern": set(),
        "mixed": set(),
    }

    for row in rows:
        country_code = row["country_code"]
        page_url = row["url"]
        key = (country_code, page_url)
        country_bucket = grouped.setdefault(
            country_code,
            {
                "scanned": [],
                "reachable": [],
                "no_social": [],
                "legacy_only": [],
                "modern": [],
                "mixed": [],
            },
        )
        links_by_platform = {
            platform: _parse_link_list(row[column])
            for platform, column in _PLATFORM_LINK_COLUMNS.items()
        }
        record = {
            "page_url": page_url,
            "is_reachable": bool(row["is_reachable"]),
            "social_tier": row["social_tier"] or "",
            "links_by_platform": links_by_platform,
            "last_scanned": row["scanned_at"] or "",
        }

        if key not in seen_by_metric["scanned"]:
            country_bucket["scanned"].append(record)
            seen_by_metric["scanned"].add(key)

        if row["is_reachable"] and key not in seen_by_metric["reachable"]:
            country_bucket["reachable"].append(record)
            seen_by_metric["reachable"].add(key)

        if row["social_tier"] == "no_social" and key not in seen_by_metric["no_social"]:
            country_bucket["no_social"].append(record)
            seen_by_metric["no_social"].add(key)

        if row["social_tier"] == "twitter_only" and key not in seen_by_metric["legacy_only"]:
            country_bucket["legacy_only"].append(record)
            seen_by_metric["legacy_only"].add(key)

        if row["social_tier"] == "modern_only" and key not in seen_by_metric["modern"]:
            country_bucket["modern"].append(record)
            seen_by_metric["modern"].add(key)

        if row["social_tier"] == "mixed" and key not in seen_by_metric["mixed"]:
            country_bucket["mixed"].append(record)
            seen_by_metric["mixed"].add(key)

    return grouped


def _query_by_country(conn: sqlite3.Connection) -> list[dict]:
    """Return per-country social media platform totals with tier breakdown.

    Uses COUNT(DISTINCT CASE WHEN … THEN url END) so that each URL is counted
    at most once per country, even when a URL appears in multiple scan batches.
    Includes both per-platform link counts and social-tier distribution for
    use in the per-country tables on the social media stats page.
    """
    rows = conn.execute(
        """
        SELECT
            country_code,
            COUNT(DISTINCT url)                                                                                    AS total_scanned,
            COUNT(DISTINCT CASE WHEN is_reachable = 1               THEN url ELSE NULL END)                        AS reachable,
            COUNT(DISTINCT CASE WHEN twitter_links != '[]'          THEN url ELSE NULL END)                        AS twitter_pages,
            COUNT(DISTINCT CASE WHEN x_links       != '[]'          THEN url ELSE NULL END)                        AS x_pages,
            COUNT(DISTINCT CASE WHEN bluesky_links  != '[]'         THEN url ELSE NULL END)                        AS bluesky_pages,
            COUNT(DISTINCT CASE WHEN mastodon_links != '[]'         THEN url ELSE NULL END)                        AS mastodon_pages,
            COUNT(DISTINCT CASE WHEN facebook_links != '[]'         THEN url ELSE NULL END)                        AS facebook_pages,
            COUNT(DISTINCT CASE WHEN linkedin_links != '[]'         THEN url ELSE NULL END)                        AS linkedin_pages,
            COUNT(DISTINCT CASE WHEN social_tier = 'twitter_only'   THEN url ELSE NULL END)                        AS twitter_only,
            COUNT(DISTINCT CASE WHEN social_tier = 'modern_only'    THEN url ELSE NULL END)                        AS modern_only,
            COUNT(DISTINCT CASE WHEN social_tier = 'mixed'          THEN url ELSE NULL END)                        AS mixed,
            COUNT(DISTINCT CASE WHEN social_tier = 'no_social'      THEN url ELSE NULL END)                        AS no_social,
            COUNT(DISTINCT CASE WHEN (twitter_links != '[]' OR x_links != '[]'
                                      OR facebook_links != '[]'
                                      OR linkedin_links != '[]')     THEN url ELSE NULL END)                        AS has_any_legacy,
            COUNT(DISTINCT CASE WHEN (bluesky_links != '[]' OR mastodon_links != '[]')      THEN url ELSE NULL END) AS has_any_modern,
            MIN(scanned_at)                                                                                         AS first_scan,
            MAX(scanned_at)                                                                                         AS last_scan
        FROM url_social_media_results
        GROUP BY country_code
        ORDER BY country_code
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _query_top100_results(conn: sqlite3.Connection) -> dict[str, dict]:
    """Return the most recent social media scan result per URL for the Top 100.

    Queries ``url_social_media_results`` where ``country_code`` equals
    :data:`_TOP100_COUNTRY_CODE` and returns the most-recent row per URL.
    Columns returned match the platform link columns tracked by the scanner.

    Args:
        conn: Open SQLite connection with ``row_factory = sqlite3.Row``.

    Returns:
        Mapping of URL → dict with keys ``social_tier``, ``twitter_links``,
        ``x_links``, ``bluesky_links``, ``mastodon_links``, ``facebook_links``,
        ``linkedin_links``, ``is_reachable``, and ``scanned_at``.
        Returns an empty dict when no rows exist for the Top 100 country code.
    """
    rows = conn.execute(
        """
        SELECT
            url,
            is_reachable,
            twitter_links,
            x_links,
            bluesky_links,
            mastodon_links,
            facebook_links,
            linkedin_links,
            social_tier,
            scanned_at
        FROM url_social_media_results
        WHERE country_code = ?
        ORDER BY url, scanned_at DESC
        """,
        (_TOP100_COUNTRY_CODE,),
    ).fetchall()

    result: dict[str, dict] = {}
    for row in rows:
        url = row["url"]
        if url not in result:
            result[url] = dict(row)
    return result


# ---------------------------------------------------------------------------
# Digital Sovereignty helpers
# ---------------------------------------------------------------------------

def _sovereignty_score(row: dict) -> float:
    """Sovereignty score: % of reachable pages with no-social or modern-only presence.

    Higher scores indicate more digital sovereignty (fewer links to US corporate
    social-media platforms).  Pages with no social media at all score highest;
    pages linking *only* to Mastodon or Bluesky also rank well.
    """
    reachable = max(row.get("reachable", 0), 1)
    sovereign = row.get("no_social", 0) + row.get("modern_only", 0)
    return round(sovereign / reachable * 100, 1)


def _legacy_exposure(row: dict) -> float:
    """Legacy exposure: % of reachable pages with any legacy-platform link.

    "Legacy" means Twitter, X, Facebook, or LinkedIn — centralised platforms
    headquartered in the USA.
    """
    reachable = max(row.get("reachable", 0), 1)
    return round(row.get("has_any_legacy", 0) / reachable * 100, 1)


def _sovereignty_tier(score: float, legacy_pct: float) -> str:
    """Return a human-readable Digital Sovereignty tier label.

    Args:
        score: Sovereignty score (0–100) from :func:`_sovereignty_score`.
        legacy_pct: Legacy-platform exposure (0–100) from :func:`_legacy_exposure`.

    Returns:
        One of: "🥇 Leader", "🥈 Strong", "🥉 Growing",
        "⚠️ Legacy-heavy", or "➡️ Mixed".
    """
    if score >= 80 and legacy_pct <= 5:
        return "🥇 Leader"
    if score >= 60 and legacy_pct <= 20:
        return "🥈 Strong"
    if score >= 40:
        return "🥉 Growing"
    if legacy_pct >= 50:
        return "⚠️ Legacy-heavy"
    return "➡️ Mixed"


def _enrich_sovereignty_metrics(row: dict) -> dict:
    """Return a copy of *row* with sovereignty_score, legacy_exposure, and tier added.

    If the row has no reachable pages, ``sovereignty_score`` and
    ``legacy_exposure`` are set to ``None`` and the tier defaults to
    ``"➡️ Mixed"`` (insufficient data).
    """
    entry = dict(row)
    reachable = row.get("reachable", 0)
    if reachable:
        score = _sovereignty_score(row)
        leg_pct = _legacy_exposure(row)
    else:
        score = leg_pct = None
    entry["sovereignty_score"] = score
    entry["legacy_exposure"] = leg_pct
    entry["sovereignty_tier"] = _sovereignty_tier(score or 0.0, leg_pct or 0.0)
    return entry


def _build_sovereignty_section(by_country: list[dict]) -> list[str]:
    """Return Markdown lines for the Digital Sovereignty Rankings section.

    Countries are ranked by their Digital Sovereignty Score (descending), with
    legacy-platform exposure used as a tiebreaker (lower is better).  Only
    countries with at least one reachable page are included.

    The section explains the scoring methodology and lists the tier each
    country falls into so readers can quickly identify leaders, strong
    performers, and countries still dominated by US corporate platforms.
    """
    ranked = []
    for row in by_country:
        if row.get("reachable", 0) == 0:
            continue
        entry = _enrich_sovereignty_metrics(row)
        ranked.append({
            "country_code": row["country_code"],
            "score": entry["sovereignty_score"],
            "legacy_pct": entry["legacy_exposure"],
            "no_social": row.get("no_social", 0),
            "modern_only": row.get("modern_only", 0),
            "has_any_legacy": row.get("has_any_legacy", 0),
            "reachable": row.get("reachable", 0),
            "tier": entry["sovereignty_tier"],
        })

    if not ranked:
        return []

    # Sort: higher sovereignty score first; lower legacy exposure as tiebreaker.
    ranked.sort(key=lambda r: (-r["score"], r["legacy_pct"]))

    lines = [
        "",
        "---",
        "",
        "## Digital Sovereignty Rankings",
        "",
        "Countries ranked by **Digital Sovereignty Score** — the percentage of reachable pages using *no social media* or *modern open platforms only* (Mastodon / Bluesky).  A higher score means fewer links to US corporate social-media platforms (Twitter / X, Facebook, LinkedIn).  Pages with no social-media links at all score highest; pages linking only to Mastodon or Bluesky also rank well.  **Legacy Exposure** shows the percentage of reachable pages that still link to Twitter/X, Facebook, or LinkedIn.",
        "",
        "| Rank | Country | Sovereignty Score | No Social | Modern Only"
        " | Legacy Exposure | Tier |",
        "|------|---------|:-----------------:|:---------:|:-----------:"
        "|:---------------:|------|",
    ]
    for i, r in enumerate(ranked, start=1):
        lines.append(
            f"| {i} | {country_code_to_display_name(r['country_code'])} | {r['score']:.1f}% | "
            f"{r['no_social']:,} | {r['modern_only']:,} | "
            f"{r['legacy_pct']:.1f}% | {r['tier']} |"
        )

    return lines


# ---------------------------------------------------------------------------
# SVG pie chart builder
# ---------------------------------------------------------------------------

def _build_pie_svg(
    twitter_only: int,
    modern_only: int,
    mixed: int,
    no_social: int,
    pie_aria: str,
) -> list[str]:
    """Return lines of an inline, accessible SVG pie chart.

    The chart is self-contained (no external dependencies) and fully accessible:
    each segment carries a ``<title>`` element, and the root ``<svg>`` element
    is linked to ``<title>`` and ``<desc>`` elements via ``aria-labelledby``.
    SVG is preferred over ``<canvas>`` because SVG elements live in the DOM and
    are natively traversable by assistive technologies without JavaScript.
    """
    total = twitter_only + modern_only + mixed + no_social
    if total == 0:
        return ['<p style="font-size:0.85em;color:#666;text-align:center;">No data available.</p>']

    def pct(n: int) -> str:
        return f"{n / total * 100:.1f}%" if total else "0.0%"

    segments = [
        (twitter_only, "#1a8cd8", "Twitter/X only"),
        (modern_only, "#0085ff", "Modern only"),
        (mixed,       "#7856ff", "Mixed"),
        (no_social,   "#cccccc", "No Social"),
    ]

    cx, cy, r = 120, 110, 90
    paths: list[str] = []
    current_angle = -math.pi / 2  # start at 12 o'clock

    for count, color, label in segments:
        if count == 0:
            continue
        angle = 2 * math.pi * count / total
        # Guard against single full-circle segment
        if total == count:
            paths.append(
                f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}">'
                f'<title>{label}: {count:,} ({pct(count)})</title></circle>'
            )
            break
        end_angle = current_angle + angle
        x1 = cx + r * math.cos(current_angle)
        y1 = cy + r * math.sin(current_angle)
        x2 = cx + r * math.cos(end_angle)
        y2 = cy + r * math.sin(end_angle)
        large_arc = 1 if angle > math.pi else 0
        paths.append(
            f'<path d="M {cx},{cy} L {x1:.3f},{y1:.3f} A {r},{r} 0 {large_arc},1'
            f' {x2:.3f},{y2:.3f} Z" fill="{color}" stroke="#fff" stroke-width="1">'
            f'<title>{label}: {count:,} ({pct(count)})</title></path>'
        )
        current_angle = end_angle

    # Legend below the circle
    legend: list[str] = []
    ly = cy + r + 16
    for count, color, label in segments:
        legend.append(f'<rect x="20" y="{ly}" width="14" height="14" fill="{color}"/>')
        legend.append(
            f'<text x="40" y="{ly + 11}" font-size="11"'
            f' font-family="sans-serif" fill="#333">'
            f'{label} ({pct(count)})</text>'
        )
        ly += 22

    svg_height = ly + 10
    return [
        f'<svg role="img" aria-labelledby="pie-title pie-desc"'
        f' viewBox="0 0 240 {svg_height}" width="240" height="{svg_height}"'
        f' xmlns="http://www.w3.org/2000/svg">',
        '<title id="pie-title">Social media tier distribution</title>',
        f'<desc id="pie-desc">{pie_aria}</desc>',
        *paths,
        *legend,
        '</svg>',
    ]


# ---------------------------------------------------------------------------
# Top 100 section builder
# ---------------------------------------------------------------------------

# Tier display labels: maps internal tier keys to short Markdown strings.
_TIER_DISPLAY: dict[str, str] = {
    "twitter_only": "⚠️ Legacy-only",
    "modern_only": "🌟 Modern-only",
    "mixed": "🔀 Mixed",
    "no_social": "✅ No Social",
    "unreachable": "❌ Unreachable",
}


def _build_top100_section(
    institution_meta: list[dict],
    url_results: dict[str, dict],
) -> list[str]:
    """Return Markdown lines for the Top 100 Universities social media table.

    Renders an ordered table (rank ascending) with one row per ranked
    institution showing the institution name, social media tier, and a
    compact platform presence summary.  Institutions not yet scanned are
    shown with a "—" tier so the table is always complete.

    Args:
        institution_meta: List of dicts from
            :func:`_load_top100_institution_metadata`, sorted ascending by
            ``rank``.
        url_results: Mapping of URL → scan result dict from
            :func:`_query_top100_results`.

    Returns:
        List of Markdown line strings (empty list when *institution_meta* is
        empty).
    """
    if not institution_meta:
        return []

    def _has(result: dict | None, column: str) -> bool:
        """Return True when a platform link column is non-empty."""
        if result is None:
            return False
        raw = result.get(column) or "[]"
        try:
            return bool(json.loads(raw))
        except json.JSONDecodeError:
            return False

    def _platform_icons(result: dict | None) -> str:
        """Return compact emoji icons for present platforms."""
        if result is None:
            return "—"
        icons: list[str] = []
        if _has(result, "twitter_links"):
            icons.append("🐦 Twitter")
        if _has(result, "x_links"):
            icons.append("✖ X")
        if _has(result, "facebook_links"):
            icons.append("👍 Facebook")
        if _has(result, "linkedin_links"):
            icons.append("💼 LinkedIn")
        if _has(result, "bluesky_links"):
            icons.append("🦋 Bluesky")
        if _has(result, "mastodon_links"):
            icons.append("🐘 Mastodon")
        return ", ".join(icons) if icons else "*(none)*"

    lines: list[str] = [
        "",
        "---",
        "",
        "## Top 100 Universities — Social Media Presence",
        "",
        (
            "Social media presence for the top 100 US universities by national "
            "ranking. **Tier** shows the overall classification for each "
            "institution's homepage. **Platforms** lists which social media "
            "networks were detected. Rows with *Not yet scanned* have not been "
            "included in a scan run yet."
        ),
        "",
        "| Rank | Institution | Tier | Platforms |",
        "|-----:|-------------|------|-----------|",
    ]

    for inst in institution_meta:
        rank = inst["rank"]
        name = inst["institution_name"]
        url = inst["url"]
        result = url_results.get(url)

        if result is None:
            tier_str = "*Not yet scanned*"
            platform_str = "—"
        else:
            tier_key = result.get("social_tier") or "no_social"
            tier_str = _TIER_DISPLAY.get(tier_key, tier_key)
            if not result.get("is_reachable"):
                tier_str = _TIER_DISPLAY["unreachable"]
            platform_str = _platform_icons(result)

        lines.append(f"| {rank} | {name} | {tier_str} | {platform_str} |")

    # Summary counts
    scanned = sum(1 for i in institution_meta if url_results.get(i["url"]) is not None)
    total = len(institution_meta)
    lines += [
        "",
        f"*{scanned} of {total} ranked institutions scanned so far.*",
    ]

    return lines


# ---------------------------------------------------------------------------
# Stats block builder
# ---------------------------------------------------------------------------

def _build_stats_block(
    summary: dict,
    generated_at: str,
    total_available: int = 0,
    by_country: list[dict] | None = None,
    seed_counts: dict[str, int] | None = None,
    twitter_x_urls: dict[str, list[str]] | None = None,
    top100_meta: list[dict] | None = None,
    top100_results: dict[str, dict] | None = None,
) -> str:
    """Return a Markdown stats block to inject between the markers.

    Args:
        summary: Aggregate stats from ``_query_summary()``.
        generated_at: Human-readable timestamp string.
        total_available: Total pages across all toon seed files.  When > 0,
            the block includes a "X of Y available pages scanned" coverage line.
        by_country: Per-country rows from ``_query_by_country()``.  When
            provided, the block includes per-country breakdown tables, a pie
            chart, sortable table, and accessible tooltips for small numbers.
        seed_counts: Mapping of country_code → available page count from
            toon seed files.  Used for the "Available" column in the per-country
            table when *by_country* is provided.
        twitter_x_urls: Deprecated. Retained for backwards compatibility with
            older tests while the drilldown UI now reads from
            ``social-media-data.json`` directly.
        top100_meta: Per-institution metadata list from
            :func:`_load_top100_institution_metadata`.  When provided (and
            non-empty), a "Top 100 Universities" ranked table is appended.
        top100_results: Per-URL scan results for the Top 100 from
            :func:`_query_top100_results`.  Required alongside *top100_meta*
            to populate the ranked table.
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
    twitter = summary.get("twitter_pages") or 0
    x_pages = summary.get("x_pages") or 0
    bluesky = summary.get("bluesky_pages") or 0
    mastodon = summary.get("mastodon_pages") or 0
    facebook = summary.get("facebook_pages") or 0
    linkedin = summary.get("linkedin_pages") or 0
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
    ]

    # Pre-compute per-country totals (needed for pie chart and total rows).
    # The SVG pie chart is added first (float:right) so that the stats text
    # that follows wraps around it.
    if by_country:
        seed_counts = seed_counts or {}
        tot_scanned = sum(r["total_scanned"] for r in by_country)
        tot_avail = sum(seed_counts.values())
        tot_reachable = sum(r["reachable"] for r in by_country)
        tot_twitter_only = sum(r.get("twitter_only", 0) for r in by_country)
        tot_modern_only = sum(r.get("modern_only", 0) for r in by_country)
        tot_mixed = sum(r.get("mixed", 0) for r in by_country)
        tot_no_social = sum(r.get("no_social", 0) for r in by_country)
        tot_tw = sum(r.get("twitter_pages", 0) for r in by_country)
        tot_x = sum(r.get("x_pages", 0) for r in by_country)
        tot_bsky = sum(r.get("bluesky_pages", 0) for r in by_country)
        tot_mast = sum(r.get("mastodon_pages", 0) for r in by_country)
        tot_fb = sum(r.get("facebook_pages", 0) for r in by_country)
        tot_li = sum(r.get("linkedin_pages", 0) for r in by_country)

        # SVG pie chart: floated right so the stats text wraps to its left.
        # SVG is preferred over <canvas> because SVG elements live in the DOM
        # and are natively traversable by assistive technologies without JS.
        # Use the pie total (classified pages only) as the denominator so the
        # percentages in <desc> are consistent with the segment <title> elements.
        pie_aria = (
            f"Pie chart: social media tier distribution across {tot_scanned:,} scanned pages. "
            f"Legacy only: {tot_twitter_only:,} ({_pct(tot_twitter_only, tot_scanned)}), "
            f"Modern only: {tot_modern_only:,} ({_pct(tot_modern_only, tot_scanned)}), "
            f"Mixed: {tot_mixed:,} ({_pct(tot_mixed, tot_scanned)}), "
            f"No Social: {tot_no_social:,} ({_pct(tot_no_social, tot_scanned)})"
        )
        lines += [
            '<div id="sm-tier-pie-container" style="float:right;margin:0 0 1rem 1.5rem;'
            'width:260px;max-width:45%;">',
            *_build_pie_svg(
                tot_twitter_only, tot_modern_only, tot_mixed, tot_no_social,
                pie_aria,
            ),
            '<p style="text-align:center;font-size:0.75em;margin:0.3rem 0 0;'
            'color:#555;font-style:italic;">Social media tier distribution</p>',
            '</div>',
            "",
        ]

    lines += [
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

    reach_pct = _pct(reachable, scanned)
    lines += [
        f"**{reachable:,}** of **{scanned:,}** scanned pages were reachable "
        f"(**{reach_pct}**)",
        "",
    ]

    # Platform overview table
    lines += [
        "**Legacy social media** (older, centralised platforms):",
        "",
        "| Platform | Pages with link | % of scanned | % of reachable |",
        "|----------|----------------|:------------:|:--------------:|",
        f"| 🐦 Twitter | **{twitter:,}** | {_pct(twitter, scanned)} | {_pct(twitter, reachable)} |",
        f"| ✖ X | **{x_pages:,}** | {_pct(x_pages, scanned)} | {_pct(x_pages, reachable)} |",
        f"| 👍 Facebook | **{facebook:,}** | {_pct(facebook, scanned)} | {_pct(facebook, reachable)} |",
        f"| 💼 LinkedIn | **{linkedin:,}** | {_pct(linkedin, scanned)} | {_pct(linkedin, reachable)} |",
        "",
        "**Modern / open social media** (decentralised or open platforms):",
        "",
        "| Platform | Pages with link | % of scanned | % of reachable |",
        "|----------|----------------|:------------:|:--------------:|",
        f"| 🦋 Bluesky | **{bluesky:,}** | {_pct(bluesky, scanned)} | {_pct(bluesky, reachable)} |",
        f"| 🐘 Mastodon / Fediverse | **{mastodon:,}** | {_pct(mastodon, scanned)} | {_pct(mastodon, reachable)} |",
    ]

    if by_country:
        lines += [
            "",
            '<div style="clear:both;"></div>',
        ]

    lines += [
        "",
        "📥 Machine-readable results are available as the "
        "[social-media-data.json artifact (machine-readable JSON)]"
        "(https://github.com/mgifford/eu-plus-government-scans/actions/workflows/generate-scan-progress.yml).",
    ]

    # Digital Sovereignty Rankings section (leaderboard)
    if by_country:
        lines += _build_sovereignty_section(by_country)

    # Per-country breakdown table
    # Column order: Country | Scanned | Available | Reachable | Sov. Score |
    #   No Social | Legacy-only | Twitter | X | Facebook | LinkedIn |
    #   Modern | Mixed | Bluesky | Mastodon | Scan Period
    #
    # "Available" = total pages in the TOON seed file (all government pages tracked).
    # "Reachable" = pages that returned a valid HTTP response when scanned
    #               (not 404 / 500 / timeout).
    # "Sov. Score" = Digital Sovereignty Score (% reachable with no/modern social only).
    if by_country:
        # Overall sovereignty score from totals
        tot_sov_score = (
            f"{(tot_no_social + tot_modern_only) / max(tot_reachable, 1) * 100:.1f}%"
            if tot_reachable else "—"
        )
        lines += [
            "",
            "---",
            "",
            "## Social Media Scan by Institution Group",
            "",
            "**Available**: all pages tracked in our domain list. "
            "**Reachable**: of those scanned, pages that returned a valid HTTP response "
            "(not an error or timeout). "
            "**Sov. Score**: Digital Sovereignty Score — % of reachable pages with "
            "no social media or modern-only social presence. "
            "Tier columns classify each page by its overall social media presence; "
            "platform columns count pages with at least one link to that platform — "
            "a page may appear in more than one platform column.",
            "",
            "| Country | Scanned | Available | Reachable | Sov. Score | No Social | Legacy-only |"
            " Twitter | X | Facebook | LinkedIn | Modern | Mixed | Bluesky | Mastodon | Scan Period |",
            "|---------|---------|-----------|-----------|:----------:|-----------|-------------|"
            "---------|---|----------|----------|--------|-------|---------|----------|-------------|",
        ]
        for row in by_country:
            cc = row["country_code"]
            display_cc = country_code_to_display_name(cc)
            available = seed_counts.get(cc, 0)
            avail_str = f"{available:,}" if available else "—"
            period = _scan_period(row.get("first_scan"), row.get("last_scan"))
            sov = (
                f"{_sovereignty_score(row):.1f}%"
                if row.get("reachable", 0) else "—"
            )
            lines.append(
                f"| {display_cc} | {row['total_scanned']:,} | {avail_str} | {row['reachable']:,} | "
                f"{sov} | "
                f"{row.get('no_social', 0):,} | {row.get('twitter_only', 0):,} | "
                f"{row.get('twitter_pages', 0):,} | {row.get('x_pages', 0):,} | "
                f"{row.get('facebook_pages', 0):,} | {row.get('linkedin_pages', 0):,} | "
                f"{row.get('modern_only', 0):,} | {row.get('mixed', 0):,} | "
                f"{row.get('bluesky_pages', 0):,} | {row.get('mastodon_pages', 0):,} | "
                f"{period} |"
            )

        # totals row
        tot_avail_str = f"**{tot_avail:,}**" if tot_avail else "—"
        lines.append(
            f"| **Total** | **{tot_scanned:,}** | {tot_avail_str} | **{tot_reachable:,}** | "
            f"**{tot_sov_score}** | "
            f"**{tot_no_social:,}** | **{tot_twitter_only:,}** | "
            f"**{tot_tw:,}** | **{tot_x:,}** | **{tot_fb:,}** | **{tot_li:,}** | "
            f"**{tot_modern_only:,}** | **{tot_mixed:,}** | "
            f"**{tot_bsky:,}** | **{tot_mast:,}** | — |"
        )

        lines += [
            "",
            "> Hover or focus any non-zero country-table count to preview matching pages. "
            "Activate the number to keep the preview open. Full machine-readable data is "
            "available as the [social-media-data.json artifact (machine-readable JSON)]"
            "(https://github.com/mgifford/eu-plus-government-scans/actions/workflows/generate-scan-progress.yml).",
        ]

    # Top 100 Universities ranked table
    if top100_meta:
        lines += _build_top100_section(
            top100_meta,
            top100_results or {},
        )

    lines += [
        "",
        _STATS_MARKER_END,
    ]
    return "\n".join(lines)


def _build_interactive_block(
    twitter_x_urls: dict[str, list[str]] | None = None,
) -> list[str]:
    """Return the CSS ``<style>`` and JavaScript ``<script>`` lines.

    The returned lines are appended at the end of the stats section.  They
    provide three interactive enhancements:

    1. Sortable column headers on the "Social Media Scan by Country" table.
    2. Accessible WCAG 2.2 AA tooltips (role="tooltip" + aria-describedby)
       for numeric cells whose value is less than 25.
    3. For the Twitter and X columns specifically, the tooltip (< 25 sites)
       or an expandable ``<details>/<summary>`` widget (≥ 25 sites) shows
       the actual scanned-page URLs that link to Twitter or X, making it easy
       to identify which government sites still use those platforms.
    """
    # Embed the per-country Twitter/X URL data as a JS variable so the browser
    # script can populate tooltips / details widgets with real site names.
    tw_x_data = twitter_x_urls or {}
    tw_x_json = json.dumps(tw_x_data, ensure_ascii=False).replace("</", "<\\/")
    data_script = f"<script>\nvar SM_TWITTER_X_URLS = {tw_x_json};\n</script>"

    css = """\
<style>
/* Pie chart container — floats right so stats text wraps to its left */
#sm-tier-pie-container { float: right; margin: 0 0 1rem 1.5rem; width: 260px; max-width: 45%; }

/* Accessible tooltip trigger */
.sm-tip {
  position: relative;
  display: inline-block;
  cursor: help;
  text-decoration: underline dotted;
  text-underline-offset: 2px;
}
/* Tooltip popup — hidden until hover/focus */
.sm-tooltip-popup {
  visibility: hidden;
  position: absolute;
  bottom: calc(100% + 6px);
  left: 50%;
  transform: translateX(-50%);
  background: #222;
  color: #fff;
  padding: 5px 9px;
  border-radius: 4px;
  font-size: 0.78em;
  white-space: normal;
  overflow-wrap: break-word;
  z-index: 200;
  min-width: 180px;
  max-width: 320px;
  line-height: 1.4;
}
.sm-tooltip-popup::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 5px solid transparent;
  border-top-color: #222;
}
/* Show tooltip on hover or keyboard focus */
.sm-tip:hover .sm-tooltip-popup,
.sm-tip:focus .sm-tooltip-popup { visibility: visible; }

/* Twitter/X expandable site-list widget (used when count >= 25) */
.sm-tw-details { display: inline; }
.sm-tw-summary {
  cursor: pointer;
  text-decoration: underline dotted;
  text-underline-offset: 2px;
  color: inherit;
  font-size: 1em;
}
.sm-tw-summary::-webkit-details-marker { display: none; }
.sm-tw-details .sm-tw-list {
  position: absolute;
  background: #222;
  color: #fff;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 0.78em;
  line-height: 1.5;
  z-index: 200;
  max-height: 220px;
  overflow-y: auto;
  min-width: 240px;
  max-width: 420px;
  list-style: none;
  margin: 4px 0 0;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
  overflow-wrap: break-word;
}
.sm-tw-details .sm-tw-list a {
  color: #9ecfff;
  text-decoration: none;
}
.sm-tw-details .sm-tw-list a:hover,
.sm-tw-details .sm-tw-list a:focus { text-decoration: underline; }
.sm-tw-details[open] .sm-tw-summary { outline: 2px solid currentColor; outline-offset: 2px; }

/* Sortable table column headers */
.sm-sortable th[aria-sort] { cursor: pointer; white-space: nowrap; user-select: none; }
.sm-sortable th[aria-sort]:hover,
.sm-sortable th[aria-sort]:focus-visible { text-decoration: underline; outline: 2px solid currentColor; outline-offset: 2px; }
.sm-sortable th[aria-sort="ascending"]::after  { content: " ▲"; font-size: 0.75em; }
.sm-sortable th[aria-sort="descending"]::after { content: " ▼"; font-size: 0.75em; }
.sm-sortable th[aria-sort="none"]::after       { content: " ⇅"; font-size: 0.75em; opacity: 0.5; }
</style>"""

    js = """\
<script>
(function () {
  "use strict";

  // ── Accessible tooltips ──────────────────────────────────────────────────
  // Twitter/X columns (< 25 sites): WCAG 2.2 AA tooltip showing actual URLs.
  // Twitter/X columns (≥ 25 sites): accessible <details>/<summary> widget.
  // Other numeric columns (< 25): generic "small sample" tooltip.
  // All use role="tooltip" + aria-describedby where applicable.
  var _tipSeq = 0;

  function addTooltips() {
    var countryTable = _findCountryTable();
    if (!countryTable) return;

    var headers = Array.from(countryTable.querySelectorAll("thead th"));
    // Numeric columns are all except Country (0), Sov. Score, and Scan Period.
    var numericCols = [];
    // Track which column indices are the Twitter and X platform columns.
    var twitterXCols = [];
    headers.forEach(function (th, i) {
      var t = th.textContent.trim();
      if (t !== "Country" && t !== "Scan Period" && t !== "Sov. Score") {
        numericCols.push(i);
      }
      if (t === "Twitter" || t === "X") {
        twitterXCols.push(i);
      }
    });

    countryTable.querySelectorAll("tbody tr").forEach(function (row) {
      var cells = row.querySelectorAll("td");
      // Skip the totals row
      if (cells[0] && cells[0].textContent.includes("Total")) return;
      var country = cells[0] ? cells[0].textContent.trim() : "";
      numericCols.forEach(function (ci) {
        var cell = cells[ci];
        if (!cell) return;
        var raw = cell.textContent.replace(/,/g, "").trim();
        var n = parseInt(raw, 10);
        if (isNaN(n) || n <= 0) return;
        var colName = headers[ci] ? headers[ci].textContent.trim() : "";
        // Store original value so sorting still works after innerHTML change
        cell.dataset.sortVal = String(n);

        if (twitterXCols.indexOf(ci) !== -1) {
          // ── Twitter / X column ───────────────────────────────────────────
          // Retrieve the scanned-page URLs that link to Twitter/X for this country.
          var urls = (typeof SM_TWITTER_X_URLS !== "undefined" && SM_TWITTER_X_URLS[country]) || [];
          if (n < 25) {
            // Tooltip: list the actual site URLs (WCAG 2.2 AA, role="tooltip").
            var id = "sm-tip-" + (++_tipSeq);
            var tipContent = urls.length > 0
              ? urls.map(function (u) { return _escHtml(u); }).join("<br>")
              : n + " site(s)";
            cell.innerHTML =
              '<span class="sm-tip" tabindex="0" aria-describedby="' + id + '">' +
              raw + "</span>" +
              '<span role="tooltip" id="' + id + '" class="sm-tooltip-popup">' +
              "<strong>" + _escHtml(colName) + " (" + n + " site" + (n === 1 ? "" : "s") + "):</strong><br>" +
              tipContent +
              "</span>";
          } else {
            // Details/summary: accessible expandable list for ≥ 25 sites.
            cell.innerHTML = _buildTwXDetails(urls, n, colName);
          }
        } else if (n < 25) {
          // ── Other numeric column ─────────────────────────────────────────
          // Generic "small sample" tooltip for any other column with < 25.
          var id = "sm-tip-" + (++_tipSeq);
          cell.innerHTML =
            '<span class="sm-tip" tabindex="0" aria-describedby="' + id + '">' +
            raw +
            "</span>" +
            '<span role="tooltip" id="' + id + '" class="sm-tooltip-popup">' +
            colName + ": " + n + " for " + country +
            ". Small sample — interpret with caution." +
            "</span>";
        }
      });
    });

    // Allow Escape key to dismiss any focused tooltip
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        var active = document.activeElement;
        if (active && active.classList.contains("sm-tip")) active.blur();
      }
    });
  }

  // Build an accessible <details>/<summary> widget listing sites that link to
  // Twitter/X.  Used when count >= 25 (too many for a tooltip).
  // Shows up to 10 sample URLs; if there are more, appends a note with a link
  // to the full machine-readable data file.
  function _buildTwXDetails(urls, count, colName) {
    var label = _escHtml(colName) + ": " + count + " site" + (count === 1 ? "" : "s");
    var sample = urls.slice(0, 10);
    var items = sample.length > 0
      ? sample.map(function (u) {
          var linkLabel = _escHtml(_formatSiteLinkLabel(u));
          return '<li><a href="' + _escHtml(u) + '" rel="noopener noreferrer">' +
                 linkLabel + "</a></li>";
        }).join("")
      : "";
    var more = count > sample.length
      ? '<li style="color:#aaa;font-style:italic;">…and ' +
        (count - sample.length).toLocaleString() +
        ' more — see the <a href="https://github.com/mgifford/eu-plus-government-scans/actions/workflows/generate-scan-progress.yml" rel="noopener noreferrer" style="color:#9ecfff;">social-media-data.json artifact (machine-readable JSON) in the Generate Scan Progress workflow</a> for the full list.</li>'
      : "";
    return (
      '<details class="sm-tw-details">' +
      '<summary class="sm-tw-summary" aria-label="' + label + '">' + label + "</summary>" +
      '<ul class="sm-tw-list">' + items + more + "</ul>" +
      "</details>"
    );
  }

  // Build descriptive link text for a URL in the Twitter/X details widget.
  // Returns a human-readable label and falls back to "Visit linked site"
  // for malformed URLs.
  function _formatSiteLinkLabel(rawUrl) {
    try {
      var parsed = new URL(rawUrl);
      var path = parsed.pathname && parsed.pathname !== "/" ? parsed.pathname : "";
      return path
        ? "Visit " + parsed.hostname + path
        : "Visit " + parsed.hostname + " homepage";
    } catch (e) {
      return "Visit linked site";
    }
  }

  // HTML-escape a string for safe insertion into attribute values and content.
  function _escHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function addSortable() {
    var countryTable = _findCountryTable();
    if (!countryTable) return;

    countryTable.classList.add("sm-sortable");
    var headers = Array.from(countryTable.querySelectorAll("thead th"));
    headers.forEach(function (th, ci) {
      th.setAttribute("aria-sort", "none");
      th.setAttribute("tabindex", "0");
      function doSort(e) {
        if (e.type === "keydown" && e.key !== "Enter" && e.key !== " ") return;
        if (e.type === "keydown") e.preventDefault();
        var asc = th.getAttribute("aria-sort") !== "ascending";
        headers.forEach(function (h) { h.setAttribute("aria-sort", "none"); });
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        _sortTable(countryTable, ci, asc);
      }
      th.addEventListener("click", doSort);
      th.addEventListener("keydown", doSort);
    });
  }

  function _getCellVal(cell) {
    if (!cell) return null;
    // Prefer the data attribute set when a tooltip was injected
    if (cell.dataset && cell.dataset.sortVal !== undefined) {
      return parseInt(cell.dataset.sortVal, 10);
    }
    // Use textContent directly — CSS ::after pseudo-elements and Markdown bold
    // markers are not included in textContent, so no stripping is needed.
    var text = cell.textContent.trim();
    if (text === "—" || text === "") return null;
    if (text.endsWith("%")) return parseFloat(text) || 0;
    var n = parseInt(text.replace(/,/g, ""), 10);
    return isNaN(n) ? text.toLowerCase() : n;
  }

  function _sortTable(table, ci, asc) {
    var tbody = table.querySelector("tbody");
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    // Pin the Total row to the bottom
    var pinned = null;
    if (rows.length && rows[rows.length - 1].textContent.includes("Total")) {
      pinned = rows.pop();
    }
    rows.sort(function (a, b) {
      var av = _getCellVal(a.querySelectorAll("td")[ci]);
      var bv = _getCellVal(b.querySelectorAll("td")[ci]);
      if (av === null) return asc ? 1 : -1;
      if (bv === null) return asc ? -1 : 1;
      if (typeof av === "number" && typeof bv === "number") return asc ? av - bv : bv - av;
      return asc
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av));
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
    if (pinned) tbody.appendChild(pinned);
  }}

  // ── Pie chart ────────────────────────────────────────────────────────────
  function _buildPie() {{
    var canvas = document.getElementById("sm-tier-pie");
    if (!canvas || !window.Chart) return;
    var total = SM_PIE.twitterOnly + SM_PIE.modernOnly + SM_PIE.mixed + SM_PIE.noSocial;
    function pct(n) {{ return total ? (n / total * 100).toFixed(1) + "%" : "—"; }}
    new Chart(canvas, {{
      type: "pie",
      data: {{
        labels: [
          "Legacy only (" + pct(SM_PIE.twitterOnly) + ")",
          "Modern only (" + pct(SM_PIE.modernOnly) + ")",
          "Mixed (" + pct(SM_PIE.mixed) + ")",
          "No Social (" + pct(SM_PIE.noSocial) + ")"
        ],
        datasets: [{{
          data: [SM_PIE.twitterOnly, SM_PIE.modernOnly, SM_PIE.mixed, SM_PIE.noSocial],
          backgroundColor: ["#1a8cd8", "#0085ff", "#7856ff", "#cccccc"],
          borderWidth: 1,
          borderColor: "#fff"
        }}]
      }},
      options: {{
        responsive: true,
        plugins: {{
          legend: {{ position: "bottom", labels: {{ font: {{ size: 11 }}, boxWidth: 14 }} }},
          tooltip: {{
            callbacks: {{
              label: function (ctx) {{
                var v = ctx.raw;
                var p = total ? (v / total * 100).toFixed(1) + "%" : "—";
                return " " + v.toLocaleString() + " pages (" + p + ")";
              }}
            }}
          }}
        }}
      }}
    }});
  }}

  function _loadChartJs() {{
    if (window.Chart) {{ _buildPie(); return; }}
    var s = document.createElement("script");
    s.src = "{_CHART_JS_CDN}";
    s.crossOrigin = "anonymous";
    s.onload = _buildPie;
    s.onerror = function () {{
      var c = document.getElementById("sm-tier-pie-container");
      if (c) {{
        c.innerHTML =
          '<p style="font-size:0.85em;color:#666;text-align:center;">' +
          "Chart unavailable. See the platform table for data." +
          "</p>";
      }}
    }};
    document.head.appendChild(s);
  }}

  // ── Helpers ──────────────────────────────────────────────────────────────
  function _findCountryTable() {
    var found = null;
    document.querySelectorAll("table").forEach(function (t) {
      t.querySelectorAll("th").forEach(function (th) {
        if (th.textContent.trim() === "Scan Period") found = t;
      });
    });
    return found;
  }

  // ── Init ─────────────────────────────────────────────────────────────────
  function _init() {
    addTooltips();
    addSortable();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", _init);
  } else {
    _init();
  }
})();
</script>"""

    return ["", css, "", data_script, "", js]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_social_media_report(
    db_path: Path,
    page_path: Path,
    data_path: Path,
    toon_seeds_dir: Path | None = None,
) -> bool:
    """Update *page_path* stats block and write *data_path* JSON.

    Args:
        db_path: Path to the SQLite metadata database.
        page_path: Path to the ``docs/social-media.md`` Markdown page.
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
        platform_drilldowns: dict[str, dict[str, list[dict[str, object]]]] = {}
        metric_drilldowns: dict[str, dict[str, list[dict[str, object]]]] = {}
        top100_results: dict[str, dict] = {}
    else:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            summary = _query_summary(conn)
            by_country = _query_by_country(conn)
            platform_drilldowns = _query_platform_drilldowns_by_country(conn)
            metric_drilldowns = _query_metric_drilldowns_by_country(conn)
            top100_results = _query_top100_results(conn)
        finally:
            conn.close()

    seed_counts = _count_toon_seed_urls(toon_seeds_dir) if toon_seeds_dir else {}
    total_available = sum(seed_counts.values())

    # Load Top 100 institution metadata from the seed file (if present).
    top100_meta = _load_top100_institution_metadata(toon_seeds_dir) if toon_seeds_dir else []

    # --- write the JSON data file -----------------------------------------
    data_path.parent.mkdir(parents=True, exist_ok=True)
    # Enrich each per-country row with computed sovereignty metrics.
    enriched_by_country = [_enrich_sovereignty_metrics(row) for row in by_country]
    data: dict = {
        "generated_at": generated_at,
        "summary": {
            "total_batches": summary.get("total_batches") or 0,
            "total_scanned": summary.get("total_scanned") or 0,
            "total_reachable": summary.get("total_reachable") or 0,
            "total_available": total_available,
            "twitter_pages": summary.get("twitter_pages") or 0,
            "x_pages": summary.get("x_pages") or 0,
            "bluesky_pages": summary.get("bluesky_pages") or 0,
            "mastodon_pages": summary.get("mastodon_pages") or 0,
            "facebook_pages": summary.get("facebook_pages") or 0,
            "linkedin_pages": summary.get("linkedin_pages") or 0,
            "first_scan": summary.get("first_scan"),
            "last_scan": summary.get("last_scan"),
        },
        "by_country": enriched_by_country,
        "platform_drilldowns": platform_drilldowns,
        "metric_drilldowns": metric_drilldowns,
        "top100_institutions": top100_meta,
    }
    data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Data file written: {data_path}")

    # --- update the Markdown page -----------------------------------------
    if not page_path.exists():
        print(f"Social media page not found: {page_path}", file=sys.stderr)
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
        summary,
        generated_at,
        total_available,
        by_country,
        seed_counts,
        top100_meta=top100_meta,
        top100_results=top100_results,
    )
    new_content = (
        content[:start_idx]
        + new_block
        + content[end_idx + len(_STATS_MARKER_END):]
    )
    page_path.write_text(new_content, encoding="utf-8")
    print(f"Social media page updated: {page_path}")

    # --- console summary --------------------------------------------------
    print("\n" + "=" * 60)
    print("SOCIAL MEDIA STATS SUMMARY")
    print("=" * 60)
    print(f"Batches run  : {summary.get('total_batches', 0):,}")
    scanned = summary.get('total_scanned', 0)
    reachable = summary.get('total_reachable', 0)
    if total_available:
        print(f"Pages scanned: {scanned:,} / {total_available:,} available "
              f"({scanned / total_available * 100:.1f}% coverage)")
    else:
        print(f"Sites crawled: {scanned:,} ({reachable:,} reachable)")
    print(f"Reachable    : {reachable:,} / {scanned:,}")
    print(f"Twitter pages: {summary.get('twitter_pages', 0):,}")
    print(f"X pages      : {summary.get('x_pages', 0):,}")
    print(f"Bluesky pages: {summary.get('bluesky_pages', 0):,}")
    print(f"Mastodon pages:{summary.get('mastodon_pages', 0):,}")
    if top100_meta:
        print(f"Top 100 scanned: {len(top100_results)}/{len(top100_meta)}")
    print("=" * 60)

    return True


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate aggregate social media scan stats and update "
            "docs/social-media.md with a live stats block."
        )
    )
    parser.add_argument(
        "--page",
        help="Path to the social-media Markdown page (default: docs/social-media.md)",
        type=Path,
        default=Path("docs/social-media.md"),
    )
    parser.add_argument(
        "--data",
        help="Output path for the JSON data file (default: docs/social-media-data.json)",
        type=Path,
        default=Path("docs/social-media-data.json"),
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
        ok = generate_social_media_report(db_path, args.page, args.data, args.seeds_dir)
        if not ok:
            sys.exit(1)
    except Exception as exc:
        print(f"Error generating social media report: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
