"""Helpers for organization-level reporting.

Provides functions to map URLs and domains to organizational groupings
(parent institutions, system affiliations, etc.) based on TOON seed data.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse


def load_domain_to_parent_map(toon_seeds_dir: Path | None) -> dict[str, str]:
    """Build domain → parent_institution mapping from TOON seed files.

    Each entry may have a parent_institution field that groups affiliated
    institutions under a parent (e.g., "University of California" for all
    UC campus domains).

    Args:
        toon_seeds_dir: Directory containing .toon seed files.

    Returns:
        Mapping of canonical_domain → parent_institution. If no parent
        is specified, uses institution_name as fallback. Domains with no
        institution name are mapped to "Other".
    """
    mapping: dict[str, str] = {}
    if not toon_seeds_dir or not toon_seeds_dir.is_dir():
        return mapping

    for toon_file in toon_seeds_dir.glob("*.toon"):
        try:
            data = json.loads(toon_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        domains = data.get("domains", [])
        for domain_entry in domains:
            canonical_domain = domain_entry.get("canonical_domain", "").strip()
            if not canonical_domain:
                continue

            # Prefer parent_institution, fall back to institution_name
            parent = domain_entry.get("parent_institution")
            if parent:
                parent = parent.strip()
                # Clean up delimiter characters used in some entries
                parent = parent.replace("::", " ").replace(":", " ").strip()
            if not parent:
                parent = domain_entry.get("institution_name", "").strip()
                parent = parent.replace("::", " ").replace(":", " ").strip()
            if not parent:
                parent = "Other"

            mapping[canonical_domain] = parent

    return mapping


def extract_domain_from_url(url: str) -> str | None:
    """Extract the domain from a URL.

    Converts "https://jefferson.edu/path" → "jefferson.edu"
    Removes "www." prefix to normalize variants.

    Returns None if the URL cannot be parsed.
    """
    if not url:
        return None
    try:
        parsed = urlparse(str(url))
        domain = (parsed.netloc or "").lower().strip()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain if domain else None
    except Exception:
        return None
