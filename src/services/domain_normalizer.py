"""Hostname normalization and alias helper utilities."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(slots=True)
class NormalizedDomain:
    canonical_hostname: str
    aliases: list[str]


def _to_hostname(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if "://" in text:
        parsed = urlparse(text)
        host = parsed.hostname or ""
    else:
        host = text.split("/")[0]
    host = host.strip().strip(".").lower()
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        pass
    return host


def normalize_domain(value: str, aliases: list[str] | None = None) -> NormalizedDomain:
    """Normalize a domain or URL to canonical full hostname + deduped aliases."""
    canonical = _to_hostname(value)
    alias_values = aliases or []
    normalized_aliases = []
    seen = set()
    for alias in [value, *alias_values]:
        host = _to_hostname(alias)
        if not host or host == canonical or host in seen:
            continue
        seen.add(host)
        normalized_aliases.append(host)
    return NormalizedDomain(canonical_hostname=canonical, aliases=normalized_aliases)


def are_same_host(left: str, right: str) -> bool:
    """Compare two URL/domain values as normalized hostnames."""
    return _to_hostname(left) == _to_hostname(right)
