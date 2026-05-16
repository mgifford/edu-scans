"""Helpers for selecting TOON seed files."""

from __future__ import annotations

from pathlib import Path

_SUBDOMAINS_SUFFIX = "_subdomains"


def list_effective_toon_seed_files(toon_seeds_dir: Path) -> list[Path]:
    """Return TOON files preferring ``*_subdomains.toon`` over base seeds."""
    all_toon_files = sorted(toon_seeds_dir.glob("*.toon"))
    stems_with_subdomains: set[str] = {
        f.stem[: -len(_SUBDOMAINS_SUFFIX)]
        for f in all_toon_files
        if f.stem.endswith(_SUBDOMAINS_SUFFIX)
    }
    return [
        f for f in all_toon_files
        if f.stem.endswith(_SUBDOMAINS_SUFFIX) or f.stem not in stems_with_subdomains
    ]
