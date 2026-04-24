"""CLI tool to generate a government domains listing page from TOON seed files.

Reads all country TOON files and produces a Markdown page that lists every
government domain tracked in the dataset, grouped by country.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load_toon(path: Path) -> dict:
    """Load and return a TOON JSON file, or empty dict on error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Warning: could not read {path}: {exc}", file=sys.stderr)
        return {}


def _country_sort_key(entry: tuple[str, dict]) -> str:
    """Sort key for (filename, toon_data) tuples: use country name."""
    _name, data = entry
    return data.get("country", "").lower()


def _page_link_label(url: str) -> str:
    """Build descriptive anchor text for page URLs.

    Args:
        url: Absolute page URL.

    Returns:
        Human-readable link text describing the destination page.
        Returns ``"Visit linked site"`` when the URL cannot be parsed or does
        not include a hostname.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return "Visit linked site"
    if not parsed.hostname:
        return "Visit linked site"
    path = parsed.path if parsed.path and parsed.path != "/" else ""
    if not path:
        return f"Visit {parsed.hostname} homepage"
    return f"Visit {parsed.hostname}{path}"


# ---------------------------------------------------------------------------
# report generation
# ---------------------------------------------------------------------------

def generate_domains_report(toon_dir: Path, output_path: Path) -> None:
    """Generate the domains listing Markdown page from TOON seed files."""

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    toon_files = sorted(toon_dir.glob("*.toon"))
    if not toon_files:
        with output_path.open("w", encoding="utf-8") as f:
            f.write("---\ntitle: Government Domains\nlayout: page\n---\n\n")
            f.write(f"_Generated: {generated_at}_\n\n")
            f.write("No TOON seed files found.\n")
        print(f"Domains report generated (empty): {output_path}")
        return

    # Load all TOON data
    entries: list[tuple[str, dict]] = []
    for path in toon_files:
        data = _load_toon(path)
        if data:
            entries.append((path.stem, data))

    entries.sort(key=_country_sort_key)

    total_countries = len(entries)
    total_domains = sum(len(d.get("domains", [])) for _, d in entries)
    total_pages = sum(d.get("page_count", 0) for _, d in entries)

    with output_path.open("w", encoding="utf-8") as f:
        f.write("---\ntitle: Government Domains\nlayout: page\n---\n\n")
        f.write(f"_Generated: {generated_at}_\n\n")
        f.write(
            "This page lists all government domains tracked in the dataset, "
            "grouped by country. Data is sourced from the "
            "[TOON seed files](https://github.com/mgifford/eu-plus-government-scans"
            "/tree/main/data/toon-seeds) in the repository.\n\n"
        )
        f.write(
            f"**{total_countries} countries** · "
            f"**{total_domains:,} domains** · "
            f"**{total_pages:,} pages**\n\n"
        )

        # Table of contents
        f.write("## Countries\n\n")
        for _stem, data in entries:
            country = data.get("country", "Unknown")
            anchor = country.lower().replace(" ", "-").replace("(", "").replace(")", "")
            domain_count = len(data.get("domains", []))
            page_count = data.get("page_count", 0)
            f.write(
                f"- [{country}](#{anchor}) "
                f"({domain_count:,} domains, {page_count:,} pages)\n"
            )
        f.write("\n---\n\n")

        # Per-country domain tables
        for _stem, data in entries:
            country = data.get("country", "Unknown")
            domains = data.get("domains", [])
            page_count = data.get("page_count", 0)

            f.write(f"## {country}\n\n")
            f.write(
                f"**{len(domains):,} domains** · **{page_count:,} pages**\n\n"
            )

            if domains:
                f.write("| Domain | Pages |\n")
                f.write("|--------|-------|\n")
                for domain_entry in sorted(
                    domains, key=lambda d: d.get("canonical_domain", "")
                ):
                    canonical = domain_entry.get("canonical_domain", "")
                    pages = domain_entry.get("pages", [])
                    page_links = ", ".join(
                        f"[{_page_link_label(p['url'])}]({p['url']})"
                        for p in pages[:3]
                    )
                    if len(pages) > 3:
                        page_links += f" _(+{len(pages) - 3} more)_"
                    f.write(f"| `{canonical}` | {page_links} |\n")
            else:
                f.write("_No domains listed._\n")

            f.write("\n")

    print(
        f"Domains report generated: {output_path} "
        f"({total_countries} countries, {total_domains:,} domains)"
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate a government domains listing page from TOON seed files."
        )
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file path (default: docs/domains.md)",
        type=Path,
        default=Path("docs/domains.md"),
    )
    parser.add_argument(
        "--toon-dir",
        help="Directory containing TOON seed files (default: data/toon-seeds)",
        type=Path,
        default=Path("data/toon-seeds"),
    )

    args = parser.parse_args()

    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        generate_domains_report(args.toon_dir, args.output)
    except Exception as exc:
        print(f"Error generating domains report: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
