"""CLI entry point for the subdomain scanner.

Reads a TOON seed file, probes each apex .edu domain with common subdomain
prefixes loaded from a YAML patterns file, validates the candidates, and
writes an updated TOON file (suffixed ``_subdomains.toon``) that contains
newly-discovered page entries without any duplicates.

Usage examples::

    # Scan all apex domains in usa-edu-master.toon
    python3 -m src.cli.scan_subdomains \\
        --toon data/toon-seeds/usa-edu-master.toon

    # Limit to the first 10 apex domains (useful for quick smoke-tests)
    python3 -m src.cli.scan_subdomains \\
        --toon data/toon-seeds/usa-edu-master.toon \\
        --max-domains 10

    # Use a custom patterns file and output path
    python3 -m src.cli.scan_subdomains \\
        --toon data/toon-seeds/usa-edu-master.toon \\
        --patterns data/common-subdomains.yml \\
        --output /tmp/usa-edu-master_subdomains.toon
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from src.services.subdomain_scanner import (
    DEFAULT_PATTERNS_FILE,
    SubdomainScanner,
    load_subdomain_patterns,
    load_toon,
    save_toon,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Discover active subdomains for .edu institutions recorded in a "
            "TOON seed file and append valid ones to the TOON output."
        )
    )
    parser.add_argument(
        "--toon",
        required=True,
        type=Path,
        metavar="PATH",
        help="Path to the input TOON seed file (e.g. data/toon-seeds/usa-edu-master.toon).",
    )
    parser.add_argument(
        "--patterns",
        type=Path,
        default=DEFAULT_PATTERNS_FILE,
        metavar="PATH",
        help=(
            "Path to the YAML file of common subdomain prefixes "
            f"(default: {DEFAULT_PATTERNS_FILE})."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Path for the output TOON file.  Defaults to the input filename "
            "with ``_subdomains`` inserted before the ``.toon`` extension."
        ),
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=2.0,
        metavar="FLOAT",
        dest="rate_limit",
        help="Maximum HTTP requests per second (default: 2.0).",
    )
    parser.add_argument(
        "--max-domains",
        type=int,
        default=None,
        metavar="N",
        dest="max_domains",
        help=(
            "Only probe the first N apex domains.  Omit to process all domains.  "
            "Useful for incremental runs and smoke-tests."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        metavar="SECONDS",
        help="HTTP request timeout in seconds (default: 15).",
    )
    return parser


def _default_output_path(toon_path: Path) -> Path:
    """Return ``<stem>_subdomains.toon`` alongside the input file."""
    return toon_path.parent / f"{toon_path.stem}_subdomains.toon"


async def _run(args: argparse.Namespace) -> int:
    """Async implementation of the scan-subdomains command.

    Returns:
        Exit code (0 for success, non-zero on error).
    """
    # ------------------------------------------------------------------ #
    # Resolve paths                                                         #
    # ------------------------------------------------------------------ #
    toon_path: Path = args.toon
    patterns_path: Path = args.patterns
    output_path: Path = args.output if args.output else _default_output_path(toon_path)

    # ------------------------------------------------------------------ #
    # Load inputs                                                           #
    # ------------------------------------------------------------------ #
    try:
        toon_data = load_toon(toon_path)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        prefixes = load_subdomain_patterns(patterns_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error loading subdomain patterns: {exc}", file=sys.stderr)
        return 1

    print(f"Loaded {len(prefixes)} subdomain prefixes from {patterns_path}")
    print(f"Input TOON:  {toon_path}")
    print(f"Output TOON: {output_path}")

    # ------------------------------------------------------------------ #
    # Run the scan                                                          #
    # ------------------------------------------------------------------ #
    scanner = SubdomainScanner(timeout_seconds=args.timeout)
    print(
        "\nScanning subdomains"
        + (f" (first {args.max_domains} domains)" if args.max_domains else "")
        + " …\n"
    )

    stats = await scanner.scan_toon(
        toon_data,
        prefixes,
        rate_limit_per_second=args.rate_limit,
        max_domains=args.max_domains,
    )

    # ------------------------------------------------------------------ #
    # Save output                                                           #
    # ------------------------------------------------------------------ #
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_toon(toon_data, output_path)

    # ------------------------------------------------------------------ #
    # Report                                                                #
    # ------------------------------------------------------------------ #
    print("\n" + "=" * 70)
    print("SUBDOMAIN SCAN COMPLETE")
    print("=" * 70)
    print(f"Apex domains scanned : {stats.domains_scanned}")
    print(f"Candidates probed    : {stats.candidates_probed}")
    print(f"Valid subdomains found: {stats.valid_found}")
    print(f"  of which redirected: {stats.redirected}")
    print(f"Output written to    : {output_path}")

    if stats.valid_found:
        print("\nDiscovered subdomains:")
        for result in stats.results:
            redirect_note = f" → {result.redirected_to}" if result.redirected_to else ""
            print(f"  {result.url}{redirect_note}")

    return 0


def main() -> None:
    """Entry point for ``python3 -m src.cli.scan_subdomains``."""
    parser = _build_parser()
    args = parser.parse_args()

    try:
        exit_code = asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\nScan interrupted.", file=sys.stderr)
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
