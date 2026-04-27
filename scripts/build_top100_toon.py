#!/usr/bin/env python3
"""Build the Top 100 US universities TOON seed file.

Reads ``data/rankings/us-news-top100.csv`` and cross-references against
``data/toon-seeds/usa-edu-master.toon`` to produce
``data/toon-seeds/usa-edu-top100.toon``.

Each domain entry in the output TOON carries a ``ranking`` field so that
the social media report can render an ordered, per-institution table for
the top 100.

Usage::

    python3 scripts/build_top100_toon.py [--rankings <csv>] [--master <toon>] [--output <toon>]
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_RANKINGS_CSV = REPO_ROOT / "data" / "rankings" / "us-news-top100.csv"
_DEFAULT_MASTER_TOON = REPO_ROOT / "data" / "toon-seeds" / "usa-edu-master.toon"
_DEFAULT_OUTPUT_TOON = REPO_ROOT / "data" / "toon-seeds" / "usa-edu-top100.toon"


def _load_rankings(csv_path: Path) -> list[dict]:
    """Return rankings as a list of ``{rank, institution_name, primary_domain}`` dicts.

    Args:
        csv_path: Path to the rankings CSV file.

    Returns:
        List of dicts with ``rank`` (int), ``institution_name`` (str), and
        ``primary_domain`` (str) keys, sorted ascending by rank.
    """
    rankings: list[dict] = []
    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rankings.append({
                "rank": int(row["rank"]),
                "institution_name": row["institution_name"].strip(),
                "primary_domain": row["primary_domain"].strip().lower(),
            })
    rankings.sort(key=lambda r: r["rank"])
    return rankings


def _build_domain_lookup(master_data: dict) -> dict[str, dict]:
    """Return a mapping of canonical_domain → domain entry from the master TOON.

    Args:
        master_data: Parsed master TOON JSON.

    Returns:
        Dict keyed by lowercase canonical domain string.
    """
    return {
        entry["canonical_domain"].lower(): entry
        for entry in master_data.get("domains", [])
        if entry.get("canonical_domain")
    }


def _make_minimal_domain_entry(rank_row: dict) -> dict:
    """Return a minimal TOON domain entry for a ranked institution not found in master.

    This ensures the output TOON is complete even when the master TOON does not
    contain an entry for a given ranked institution.

    Args:
        rank_row: A ranking row with ``rank``, ``institution_name``, and
            ``primary_domain`` keys.

    Returns:
        A minimal domain entry dict compatible with the TOON format.
    """
    domain = rank_row["primary_domain"]
    url = f"https://{domain}/"
    return {
        "canonical_domain": domain,
        "institution_name": rank_row["institution_name"],
        "parent_institution": None,
        "affiliated_domains": [domain],
        "source_types": ["rankings"],
        "pages": [{"url": url, "is_root_page": True}],
        "candidate_paths": [],
        "ranking": rank_row["rank"],
    }


def build_top100_toon(
    rankings_csv: Path = _DEFAULT_RANKINGS_CSV,
    master_toon: Path = _DEFAULT_MASTER_TOON,
    output_toon: Path = _DEFAULT_OUTPUT_TOON,
) -> dict:
    """Build the top-100 TOON seed file and return the resulting data dict.

    For each ranked institution the master TOON is searched by
    ``canonical_domain``.  If a match is found its entry is used (with a
    ``ranking`` field injected); otherwise a minimal entry is synthesised from
    the rankings CSV so the output TOON is always complete.

    Args:
        rankings_csv: Path to the rankings CSV.
        master_toon: Path to the master TOON seed file.
        output_toon: Destination path for the generated top-100 TOON.

    Returns:
        The generated TOON data as a Python dict.
    """
    if not rankings_csv.exists():
        print(f"Error: rankings CSV not found: {rankings_csv}", file=sys.stderr)
        sys.exit(1)
    if not master_toon.exists():
        print(f"Error: master TOON not found: {master_toon}", file=sys.stderr)
        sys.exit(1)

    rankings = _load_rankings(rankings_csv)
    print(f"Loaded {len(rankings)} ranked institutions from {rankings_csv}")

    master_data = json.loads(master_toon.read_text(encoding="utf-8"))
    domain_lookup = _build_domain_lookup(master_data)
    print(f"Master TOON has {len(domain_lookup)} domain entries")

    output_domains: list[dict] = []
    matched = 0
    minimal = 0

    for rank_row in rankings:
        domain = rank_row["primary_domain"]
        if domain in domain_lookup:
            entry = copy.deepcopy(domain_lookup[domain])
            entry["ranking"] = rank_row["rank"]
            # Use the canonical institution name from the rankings CSV for
            # clarity, but keep the master TOON name in a separate field so
            # the original data is preserved.
            entry["ranking_institution_name"] = rank_row["institution_name"]
            output_domains.append(entry)
            matched += 1
        else:
            entry = _make_minimal_domain_entry(rank_row)
            output_domains.append(entry)
            minimal += 1
            print(
                f"  [rank {rank_row['rank']:3d}] {domain} not found in master "
                f"— using minimal entry for: {rank_row['institution_name']}"
            )

    print(f"Matched {matched} institutions from master TOON, {minimal} minimal entries")

    output_data: dict = {
        "version": "0.1-seed",
        "country": "USA_EDU_TOP100",
        "dataset_scope": (
            "Top 100 US higher-education institutions by national university ranking"
        ),
        "ranking_source": "us-news-top100.csv",
        "institution_count": len(output_domains),
        "parent_group_count": 0,
        "page_count": sum(
            len(entry.get("pages", [])) for entry in output_domains
        ),
        "domains": output_domains,
    }

    output_toon.parent.mkdir(parents=True, exist_ok=True)
    output_toon.write_text(
        json.dumps(output_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Written top-100 TOON to {output_toon}")
    print(f"  {output_data['institution_count']} institutions, "
          f"{output_data['page_count']} pages")

    return output_data


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Build the Top 100 US universities TOON seed file."
    )
    parser.add_argument(
        "--rankings",
        type=Path,
        default=_DEFAULT_RANKINGS_CSV,
        help=f"Rankings CSV (default: {_DEFAULT_RANKINGS_CSV})",
    )
    parser.add_argument(
        "--master",
        type=Path,
        default=_DEFAULT_MASTER_TOON,
        help=f"Master TOON seed file (default: {_DEFAULT_MASTER_TOON})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT_TOON,
        help=f"Output TOON file (default: {_DEFAULT_OUTPUT_TOON})",
    )
    args = parser.parse_args()
    build_top100_toon(args.rankings, args.master, args.output)


if __name__ == "__main__":
    main()
