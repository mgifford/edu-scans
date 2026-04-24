"""CLI entry point for multi-scanner: fetch a URL once, apply multiple tests.

Runs accessibility, social-media, technology and third-party JS analyses
against each URL with a single HTTP request per URL.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from src.services.multi_scanner import MultiScanner


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch each URL once and apply multiple analyses (accessibility "
            "statement detection, social media links, technology fingerprinting, "
            "third-party JS detection) in a single HTTP request per URL."
        )
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="One or more URLs to scan.",
    )
    parser.add_argument(
        "--url-file",
        help="Path to a plain-text file with one URL per line.",
        type=Path,
        dest="url_file",
    )
    parser.add_argument(
        "--rate-limit",
        help="Maximum requests per second (default: 1.0).",
        type=float,
        default=1.0,
    )
    parser.add_argument(
        "--timeout",
        help="Per-request timeout in seconds (default: 20).",
        type=int,
        default=20,
    )
    parser.add_argument(
        "--no-accessibility",
        help="Skip accessibility statement detection.",
        action="store_true",
        dest="no_accessibility",
    )
    parser.add_argument(
        "--no-social-media",
        help="Skip social media link detection.",
        action="store_true",
        dest="no_social_media",
    )
    parser.add_argument(
        "--no-tech",
        help="Skip technology fingerprinting.",
        action="store_true",
        dest="no_tech",
    )
    parser.add_argument(
        "--no-third-party-js",
        help="Skip third-party JavaScript detection.",
        action="store_true",
        dest="no_third_party_js",
    )
    return parser


def main() -> None:
    """Main CLI entry point for the multi-scanner."""
    parser = _build_parser()
    args = parser.parse_args()

    # Collect URLs from positional arguments and optional file
    urls: list[str] = list(args.urls)
    if args.url_file:
        url_file = Path(args.url_file)
        if not url_file.exists():
            print(f"Error: URL file not found: {url_file}")
            sys.exit(1)
        for line in url_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)

    if not urls:
        print("Error: No URLs provided.  Pass URLs as arguments or use --url-file.")
        parser.print_help()
        sys.exit(1)

    scanner = MultiScanner(
        timeout_seconds=args.timeout,
        run_accessibility=not args.no_accessibility,
        run_social_media=not args.no_social_media,
        run_tech=not args.no_tech,
        run_third_party_js=not args.no_third_party_js,
    )

    enabled = []
    if not args.no_accessibility:
        enabled.append("accessibility")
    if not args.no_social_media:
        enabled.append("social-media")
    if not args.no_tech:
        enabled.append("technology")
    if not args.no_third_party_js:
        enabled.append("third-party-js")

    print(f"Scanning {len(urls)} URL(s) with: {', '.join(enabled)}")
    print(f"Rate limit: {args.rate_limit} req/s")
    print()

    try:
        results = asyncio.run(
            scanner.scan_urls_batch(urls, rate_limit_per_second=args.rate_limit)
        )
    except KeyboardInterrupt:
        print("\nScan interrupted by user")
        sys.exit(1)
    except Exception as exc:
        print(f"Error: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    # Summary
    print()
    print("=" * 80)
    print("MULTI-SCAN SUMMARY")
    print("=" * 80)
    reachable = sum(1 for r in results.values() if r.is_reachable)
    print(f"Total URLs:   {len(results)}")
    print(f"Reachable:    {reachable}")
    print(f"Unreachable:  {len(results) - reachable}")

    if not args.no_accessibility:
        has_stmt = sum(
            1
            for r in results.values()
            if r.accessibility and r.accessibility.has_statement
        )
        print(f"With accessibility statement: {has_stmt}")

    if not args.no_social_media:
        from collections import Counter

        tier_counts: Counter = Counter(
            r.social_media.social_tier
            for r in results.values()
            if r.social_media is not None
        )
        print("Social media tiers:")
        for tier, count in sorted(tier_counts.items()):
            print(f"  {tier}: {count}")

    if not args.no_tech:
        has_tech = sum(
            1 for r in results.values() if r.tech and r.tech.technologies
        )
        print(f"With detected technologies: {has_tech}")

    if not args.no_third_party_js:
        has_3pjs = sum(
            1
            for r in results.values()
            if r.third_party_js and r.third_party_js.third_party_count > 0
        )
        print(f"With third-party JS: {has_3pjs}")


if __name__ == "__main__":
    main()
