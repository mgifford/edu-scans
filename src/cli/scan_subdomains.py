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
            "Only probe *N* apex domains starting from --offset.  Omit to "
            "process all domains after the offset.  Useful for incremental "
            "runs and smoke-tests."
        ),
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        metavar="N",
        dest="offset",
        help=(
            "Skip the first N apex domains before scanning.  Combine with "
            "--max-domains to process the domain list in batches across "
            "multiple runs (e.g. --offset 0 --max-domains 500, then "
            "--offset 500 --max-domains 500, …)."
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        metavar="N",
        dest="concurrency",
        help=(
            "Number of apex domains to scan concurrently (default: 1).  "
            "Higher values multiply effective throughput at the cost of a "
            "proportionally higher combined outgoing request rate.  A value "
            "of 20 combined with --rate-limit 5.0 yields ~100 req/sec."
        ),
    )
    parser.add_argument(
        "--save-interval",
        type=int,
        default=50,
        metavar="N",
        dest="save_interval",
        help=(
            "Write the output TOON file every N domains (default: 50).  "
            "Frequent saves mean partial results are preserved if the job is "
            "cancelled or times out."
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
    """Return ``<stem>_subdomains.toon`` alongside the input file.

    Args:
        toon_path: Path to the input ``.toon`` seed file.

    Returns:
        Output path with ``_subdomains`` inserted before the ``.toon``
        extension, in the same directory as the input file.
    """
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
    if args.offset:
        print(f"Starting from domain offset: {args.offset}")
    if args.concurrency > 1:
        print(f"Concurrency: {args.concurrency} domains in parallel")
    print(f"Saving progress every {args.save_interval} domains")

    # ------------------------------------------------------------------ #
    # Ensure output directory exists before the first periodic save        #
    # ------------------------------------------------------------------ #
    if not output_path.parent.exists():
        print(f"Creating output directory: {output_path.parent}")
        output_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Build an on_progress callback that saves the TOON periodically       #
    # ------------------------------------------------------------------ #
    def _on_progress(completed: int, total: int) -> None:
        if completed % args.save_interval == 0 or completed == total:
            save_toon(toon_data, output_path)
            print(
                f"  💾 Progress saved: {completed}/{total} domains processed "
                f"({output_path})"
            )

    # ------------------------------------------------------------------ #
    # Run the scan                                                          #
    # ------------------------------------------------------------------ #
    scanner = SubdomainScanner(timeout_seconds=args.timeout)
    range_note = ""
    if args.offset:
        range_note += f" from offset {args.offset}"
    if args.max_domains:
        range_note += f" (first {args.max_domains} domains)"
    print(f"\nScanning subdomains{range_note} …\n")

    stats = await scanner.scan_toon(
        toon_data,
        prefixes,
        rate_limit_per_second=args.rate_limit,
        max_domains=args.max_domains,
        start_offset=args.offset,
        concurrency_limit=args.concurrency,
        on_progress=_on_progress,
    )

    # ------------------------------------------------------------------ #
    # Final save (in case domain count was not divisible by save_interval) #
    # ------------------------------------------------------------------ #
    save_toon(toon_data, output_path)

    # ------------------------------------------------------------------ #
    # Report                                                                #
    # ------------------------------------------------------------------ #
    print("\n" + "=" * 70)
    print("SUBDOMAIN SCAN COMPLETE")
    print("=" * 70)
    w = 22
    print(f"{'Apex domains scanned':<{w}}: {stats.domains_scanned}")
    print(f"{'Candidates probed':<{w}}: {stats.candidates_probed}")
    print(f"{'Valid subdomains found':<{w}}: {stats.valid_found}")
    print(f"{'  of which redirected':<{w}}: {stats.redirected}")
    print(f"{'Output written to':<{w}}: {output_path}")

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
