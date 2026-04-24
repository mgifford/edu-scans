"""Build USA `.edu` institution master outputs and TOON seed data."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.services.usa_edu_builder import build_usa_edu_dataset, write_master_outputs


def main() -> None:
    """Run the USA `.edu` aggregation pipeline."""
    parser = argparse.ArgumentParser(
        description="Aggregate public university-domain datasets into USA .edu master outputs."
    )
    parser.add_argument(
        "--imports-dir",
        type=Path,
        default=Path("data/imports"),
        help="Directory for master JSON/CSV outputs (default: data/imports)",
    )
    parser.add_argument(
        "--toon-dir",
        type=Path,
        default=Path("data/toon-seeds"),
        help="Directory for generated TOON seed outputs (default: data/toon-seeds)",
    )
    args = parser.parse_args()

    result = build_usa_edu_dataset()
    write_master_outputs(result, args.imports_dir, args.toon_dir)

    print(f"Institutions written: {len(result.institutions)}")
    print(f"Orphan domains written: {len(result.orphan_domains)}")
    print("Parent group outputs: data/imports/usa-edu-parent-groups.{json,csv}")
    for source_name, count in sorted(result.source_counts.items()):
        print(f"  {source_name}: {count}")


if __name__ == "__main__":
    main()