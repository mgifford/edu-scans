"""Subdomain scanner for discovering active sub-sites under apex .edu domains.

Reads a YAML file of common subdomain prefixes, constructs candidate URLs for
every apex domain found in a TOON file, validates each candidate, tracks
redirects, and returns page entries suitable for inserting into the TOON
domain records — without introducing duplicates.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.services.url_validator import UrlValidator, ValidationResult


# Default location for the subdomain-patterns YAML file.
DEFAULT_PATTERNS_FILE = Path("data/common-subdomains.yml")


@dataclass(slots=True)
class SubdomainResult:
    """Result of probing a single candidate subdomain URL."""

    subdomain: str
    """The full subdomain hostname, e.g. ``library.mit.edu``."""
    url: str
    """The candidate URL that was probed, e.g. ``https://library.mit.edu/``."""
    apex_domain: str
    """The parent apex domain, e.g. ``mit.edu``."""
    prefix: str
    """The subdomain prefix used, e.g. ``library``."""
    is_valid: bool
    """``True`` when the URL returned a non-4xx/5xx HTTP status."""
    redirected_to: str | None = None
    """Final URL when the candidate redirected elsewhere."""
    status_code: int | None = None
    error_message: str | None = None
    validated_at: str | None = None


@dataclass
class SubdomainScanStats:
    """Aggregate statistics for a subdomain scan run."""

    domains_scanned: int = 0
    candidates_probed: int = 0
    valid_found: int = 0
    redirected: int = 0
    duplicates_skipped: int = 0
    results: list[SubdomainResult] = field(default_factory=list)


def load_subdomain_patterns(patterns_file: Path = DEFAULT_PATTERNS_FILE) -> list[str]:
    """Load and flatten subdomain prefixes from the YAML patterns file.

    The YAML file groups prefixes into categories (e.g. ``academic``,
    ``administrative``).  This function returns a single flat list with all
    prefixes regardless of category, preserving the order they appear in the
    file.

    Args:
        patterns_file: Path to the ``common-subdomains.yml`` file.

    Returns:
        List of subdomain prefix strings (e.g. ``["library", "admissions", …]``).

    Raises:
        FileNotFoundError: When *patterns_file* does not exist.
        ValueError: When the file does not contain a mapping of lists.
    """
    if not patterns_file.exists():
        raise FileNotFoundError(f"Subdomain patterns file not found: {patterns_file}")

    with patterns_file.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise ValueError(
            f"Expected a YAML mapping in {patterns_file}, got {type(data).__name__}"
        )

    prefixes: list[str] = []
    seen: set[str] = set()
    for category, items in data.items():
        if not isinstance(items, list):
            raise ValueError(
                f"Expected a list under category '{category}' in {patterns_file}"
            )
        for item in items:
            prefix = str(item).strip().lower()
            if prefix and prefix not in seen:
                prefixes.append(prefix)
                seen.add(prefix)

    return prefixes


def _extract_apex_domains_from_toon(toon_data: dict[str, Any]) -> list[str]:
    """Return apex (non-subdomain) .edu domains from a TOON data dict.

    Only domains with exactly two labels are included (e.g. ``mit.edu``).
    Subdomain entries that are already present as canonical domains are
    excluded because they are specific sites rather than root institutions.

    Args:
        toon_data: Parsed TOON JSON object.

    Returns:
        Deduplicated list of apex .edu domain strings.
    """
    apex: list[str] = []
    seen: set[str] = set()
    for entry in toon_data.get("domains", []):
        domain = entry.get("canonical_domain", "")
        parts = domain.split(".")
        if len(parts) == 2 and parts[-1] == "edu" and domain not in seen:
            apex.append(domain)
            seen.add(domain)
    return apex


def _existing_urls_for_domain(toon_domain_entry: dict[str, Any]) -> set[str]:
    """Return the set of URLs already recorded for a single TOON domain entry.

    Args:
        toon_domain_entry: A single domain object from ``toon_data["domains"]``.

    Returns:
        Set of URL strings.
    """
    return {page["url"] for page in toon_domain_entry.get("pages", []) if "url" in page}


def _make_candidate_url(prefix: str, apex_domain: str) -> tuple[str, str]:
    """Build a subdomain hostname and root URL from a prefix and apex domain.

    Args:
        prefix: Subdomain prefix string, e.g. ``"library"``.
        apex_domain: Apex .edu domain, e.g. ``"mit.edu"``.

    Returns:
        Tuple of ``(subdomain, url)`` where *subdomain* is the full hostname
        and *url* is the HTTPS root URL.
    """
    subdomain = f"{prefix}.{apex_domain}"
    url = f"https://{subdomain}/"
    return subdomain, url


class SubdomainScanner:
    """Discover active sub-sites under apex .edu domains.

    The scanner reads a flat list of common subdomain prefixes, constructs one
    candidate URL per (prefix × apex domain) pair, validates each URL, and
    returns ``SubdomainResult`` objects for the valid ones only.

    Redirects are tracked: when a candidate redirects to a different host
    entirely, the redirect destination is recorded so callers can decide
    whether to use the final URL or the canonical subdomain URL.

    Duplicate detection compares the candidate URL against the page URLs
    already present in the corresponding TOON domain entry; candidates whose
    URL (or whose redirect target) already appears are silently skipped.

    Args:
        timeout_seconds: HTTP request timeout in seconds.
        user_agent: User-Agent header sent with every request.
    """

    def __init__(
        self,
        timeout_seconds: int = 15,
        user_agent: str = "edu-scans/subdomain-scanner (+https://github.com/mgifford/edu-scans)",
    ) -> None:
        self._validator = UrlValidator(
            timeout_seconds=timeout_seconds,
            user_agent=user_agent,
        )

    async def scan_domain(
        self,
        apex_domain: str,
        prefixes: list[str],
        existing_urls: set[str],
        rate_limit_per_second: float = 2.0,
    ) -> tuple[list[SubdomainResult], int]:
        """Probe all prefix candidates for a single apex domain.

        Args:
            apex_domain: Apex .edu hostname, e.g. ``"mit.edu"``.
            prefixes: Ordered list of subdomain prefixes to probe.
            existing_urls: URLs already recorded in the TOON entry for this
                domain; candidates whose URL matches (after normalisation) are
                skipped without making a network request.
            rate_limit_per_second: Maximum HTTP requests per second.

        Returns:
            A 2-tuple of ``(valid_results, candidates_probed)`` where
            *valid_results* is a list of ``SubdomainResult`` objects for valid
            (non-duplicate) candidates, and *candidates_probed* is the number
            of candidate URLs actually sent to the validator.
        """
        valid_results: list[SubdomainResult] = []
        # Normalise existing URLs to bare strings for fast membership tests.
        existing_normalised = {u.rstrip("/").lower() for u in existing_urls}

        # Build candidate list, skipping prefixes whose URL already exists.
        candidates: list[tuple[str, str, str]] = []
        for prefix in prefixes:
            subdomain, url = _make_candidate_url(prefix, apex_domain)
            if url.rstrip("/").lower() in existing_normalised:
                continue
            candidates.append((prefix, subdomain, url))

        if not candidates:
            return valid_results, 0

        # Validate candidates with rate limiting.
        urls_to_validate = [c[2] for c in candidates]
        results: dict[str, ValidationResult] = await self._validator.validate_urls_batch(
            urls_to_validate,
            rate_limit_per_second=rate_limit_per_second,
            verbose=False,
        )

        for prefix, subdomain, url in candidates:
            result = results.get(url)
            if result is None or not result.is_valid:
                continue

            # Skip if the redirect destination is already in the TOON.
            final_url = result.redirected_to or url
            if final_url.rstrip("/").lower() in existing_normalised:
                continue

            valid_results.append(
                SubdomainResult(
                    subdomain=subdomain,
                    url=url,
                    apex_domain=apex_domain,
                    prefix=prefix,
                    is_valid=True,
                    redirected_to=result.redirected_to,
                    status_code=result.status_code,
                    validated_at=result.validated_at,
                )
            )

        return valid_results, len(candidates)

    async def scan_toon(
        self,
        toon_data: dict[str, Any],
        prefixes: list[str],
        rate_limit_per_second: float = 2.0,
        max_domains: int | None = None,
        start_offset: int = 0,
        concurrency_limit: int = 1,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> SubdomainScanStats:
        """Scan all apex domains in a TOON file for active subdomains.

        For each apex domain entry the method probes every prefix, collects
        valid results, and updates the ``toon_data`` dict **in-place** in two
        ways:

        1. A new **domain entry** is appended to ``toon_data["domains"]`` for
           each discovered subdomain (with ``is_subdomain: True`` and
           ``parent_domain`` set to the apex domain).  This makes subdomains
           visible in the domains report.
        2. A **page entry** is also appended to the apex domain's ``pages``
           list so that URL-validation workflows continue to see the subdomain
           URL in context.

        Duplicate detection prevents the same subdomain from being added twice
        across repeated scan runs.

        Args:
            toon_data: Parsed TOON JSON object (mutated in-place).
            prefixes: Flat list of subdomain prefixes to probe.
            rate_limit_per_second: Maximum HTTP requests per second *per
                concurrent domain*.  With ``concurrency_limit > 1`` the
                overall outgoing rate is approximately
                ``rate_limit_per_second × concurrency_limit``.
            max_domains: When set, only *max_domains* apex domains are probed
                after applying *start_offset*.  Useful for incremental runs.
            start_offset: Skip the first *start_offset* apex domains before
                selecting *max_domains*.  Combine with *max_domains* to process
                the domain list in batches across multiple runs.
            concurrency_limit: Maximum number of apex domains scanned
                concurrently.  Values above 1 multiply effective throughput at
                the cost of higher total outgoing request rate.  Each
                concurrently-running domain still honours its own
                *rate_limit_per_second*; the combined rate seen by the network
                is roughly ``rate_limit_per_second × concurrency_limit``.
            on_progress: Optional callback invoked after each domain completes.
                Receives ``(domains_completed, total_domains)`` as positional
                integers.  Use this to save incremental progress so partial
                results survive a timeout.

        Returns:
            ``SubdomainScanStats`` with counts and the full result list.
        """
        stats = SubdomainScanStats()

        # Build a quick lookup from canonical_domain → entry dict so we can
        # update pages in-place and detect duplicates efficiently.
        domain_entries: dict[str, dict[str, Any]] = {
            entry["canonical_domain"]: entry
            for entry in toon_data.get("domains", [])
            if "canonical_domain" in entry
        }

        apex_domains = _extract_apex_domains_from_toon(toon_data)
        if start_offset:
            apex_domains = apex_domains[start_offset:]
        if max_domains is not None:
            apex_domains = apex_domains[:max_domains]

        stats.domains_scanned = len(apex_domains)
        total_domains = len(apex_domains)

        semaphore = asyncio.Semaphore(concurrency_limit)

        async def _scan_one(
            apex_domain: str,
        ) -> tuple[str, list[SubdomainResult], int]:
            """Probe one apex domain under the shared concurrency semaphore."""
            entry = domain_entries.get(apex_domain)
            if entry is None:
                return apex_domain, [], 0
            existing_urls = _existing_urls_for_domain(entry)
            async with semaphore:
                found, probed = await self.scan_domain(
                    apex_domain,
                    prefixes,
                    existing_urls,
                    rate_limit_per_second=rate_limit_per_second,
                )
            return apex_domain, found, probed

        # Create tasks for all apex domains and await them as they complete so
        # on_progress can be called (and the TOON mutated) promptly after each
        # domain finishes — even when running concurrently.
        tasks = [asyncio.create_task(_scan_one(d)) for d in apex_domains]
        completed = 0

        for coro in asyncio.as_completed(tasks):
            apex_domain, found, probed_count = await coro
            completed += 1

            stats.candidates_probed += probed_count

            entry = domain_entries.get(apex_domain)
            if entry is not None:
                for result in found:
                    # Use the redirect target as the recorded URL when the
                    # subdomain root redirected to a different URL.
                    recorded_url = (
                        result.redirected_to if result.redirected_to else result.url
                    )

                    page_record: dict[str, Any] = {
                        "url": recorded_url,
                        "is_root_page": False,
                        "subdomain": result.subdomain,
                        "subdomain_prefix": result.prefix,
                        "discovered_via": "subdomain-scan",
                        "validation_status": "valid",
                        "status_code": result.status_code,
                        "validated_at": result.validated_at,
                    }

                    # 1. Append a page reference to the apex domain entry so
                    #    that URL-validation workflows can re-validate the URL.
                    entry.setdefault("pages", []).append(page_record)

                    # 2. Add a first-class domain entry for the subdomain so
                    #    it appears as its own row in the domains report.
                    if result.subdomain not in domain_entries:
                        subdomain_entry: dict[str, Any] = {
                            "canonical_domain": result.subdomain,
                            "is_subdomain": True,
                            "parent_domain": apex_domain,
                            "institution_name": entry.get("institution_name"),
                            "subdomain_prefix": result.prefix,
                            "pages": [
                                {
                                    "url": recorded_url,
                                    "is_root_page": True,
                                    "discovered_via": "subdomain-scan",
                                    "validation_status": "valid",
                                    "status_code": result.status_code,
                                    "validated_at": result.validated_at,
                                }
                            ],
                        }
                        toon_data.setdefault("domains", []).append(subdomain_entry)
                        domain_entries[result.subdomain] = subdomain_entry
                    else:
                        stats.duplicates_skipped += 1

                stats.valid_found += len(found)
                stats.redirected += sum(1 for r in found if r.redirected_to)
                stats.results.extend(found)

            if on_progress is not None:
                on_progress(completed, total_domains)

        return stats


def load_toon(toon_path: Path) -> dict[str, Any]:
    """Load and return parsed TOON JSON from *toon_path*.

    Args:
        toon_path: Path to the ``.toon`` seed file.

    Returns:
        Parsed JSON object.

    Raises:
        FileNotFoundError: When the file does not exist.
        json.JSONDecodeError: When the file exists but contains invalid JSON.
    """
    if not toon_path.exists():
        raise FileNotFoundError(f"TOON file not found: {toon_path}")
    with toon_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_toon(toon_data: dict[str, Any], output_path: Path) -> None:
    """Serialise *toon_data* to *output_path* as formatted JSON.

    Args:
        toon_data: TOON data dict to serialise.
        output_path: Destination file path.  Parent directories must exist.
    """
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(toon_data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
