"""Helpers for selecting TOON seed files."""

from __future__ import annotations

from pathlib import Path

_SUBDOMAINS_SUFFIX = "_subdomains"


def _should_include_seed_file(path: Path, stems_with_subdomains: set[str]) -> bool:
    """Return True when a TOON seed should be included in effective processing.

    Subdomain variants are always included. Base seeds are only included when
    they do not have a matching ``*_subdomains.toon`` counterpart.

    Args:
        path: TOON seed file path.
        stems_with_subdomains: Base stems that have subdomain variants.
    """
    return path.stem.endswith(_SUBDOMAINS_SUFFIX) or path.stem not in stems_with_subdomains


def list_effective_toon_seed_files(toon_seeds_dir: Path) -> list[Path]:
    """Return filtered TOON seed paths preferring ``*_subdomains.toon`` variants.

    Args:
        toon_seeds_dir: Directory containing ``*.toon`` seed files.

    Returns:
        List of seed file paths where each base seed is replaced by its matching
        ``*_subdomains.toon`` file when that richer variant exists (for example,
        ``foo.toon`` is excluded when ``foo_subdomains.toon`` is present).
    """
    all_toon_files = sorted(toon_seeds_dir.glob("*.toon"))
    stems_with_subdomains: set[str] = {
        f.stem[: -len(_SUBDOMAINS_SUFFIX)]
        for f in all_toon_files
        if f.stem.endswith(_SUBDOMAINS_SUFFIX)
    }
    return [
        f
        for f in all_toon_files
        if _should_include_seed_file(f, stems_with_subdomains)
    ]
