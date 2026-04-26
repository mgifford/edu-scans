"""Build a deduplicated USA `.edu` institution seed dataset.

This module aggregates several public university-domain sources, normalizes
their records, merges overlapping institutions, and emits both review-friendly
master outputs and TOON-compatible seed data.
"""

from __future__ import annotations

import csv
import io
import json
import re
import tarfile
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


USER_AGENT = "edu-scans/usa-edu-builder (+https://github.com/mgifford/edu-scans)"

SOURCE_URLS = {
    "edu_inventory": "https://raw.githubusercontent.com/nickdenardis/edu-inventory/master/edu-info.csv",
    "hipo": "https://raw.githubusercontent.com/Hipo/university-domains-list/master/world_universities_and_domains.json",
    "swot_tarball": "https://codeload.github.com/abadojack/swot/tar.gz/refs/heads/master",
    "node_university_domains": "https://raw.githubusercontent.com/matlin/node-university-domains/master/university_domains.js",
    "academic_domains": "https://raw.githubusercontent.com/mohsennazari/academic-domains-dataset/master/world_academic_domains.json",
}

_POSITIVE_NAME_HINTS = (
    "university",
    "college",
    "institute",
    "polytechnic",
    "seminary",
    "conservatory",
)

_NEGATIVE_NAME_HINTS = (
    "high school",
    "middle school",
    "elementary school",
    "school district",
    "day school",
    "prep school",
    "preparatory school",
)

_CAMPUS_SPLIT_MARKERS = (
    " campus",
    " school of ",
    " college of ",
    " branch",
    " extension",
)

_GENERIC_PARENT_NAMES = {
    "the",
    "community",
    "american",
    "national",
    "trinity",
    "central",
}


@dataclass(slots=True)
class SourceRecord:
    """Normalized source row prior to institution merging."""

    source_id: str
    source_type: str
    name: str | None
    domains: set[str] = field(default_factory=set)
    web_pages: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class InstitutionRecord:
    """Deduplicated institution entry."""

    name: str
    normalized_name: str
    domains: set[str] = field(default_factory=set)
    web_pages: set[str] = field(default_factory=set)
    source_ids: set[str] = field(default_factory=set)
    source_types: set[str] = field(default_factory=set)
    parent_institution: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BuildResult:
    """Outputs of the USA `.edu` aggregation process."""

    institutions: list[InstitutionRecord]
    orphan_domains: list[dict[str, str]]
    source_counts: dict[str, int]


def _fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response:
        payload = response.read()
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        # Some legacy CSVs include cp1252-style characters.
        return payload.decode("latin-1")


def _fetch_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response:
        return response.read()


def normalize_name(name: str) -> str:
    """Return a stable comparison key for institution names."""
    value = unescape(name).strip().lower()
    value = re.sub(r"^the\s+", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def display_name(name: str) -> str:
    """Return a clean institution label for output files."""
    return re.sub(r"\s+", " ", unescape(name)).strip()


def slugify(value: str) -> str:
    """Convert an institution name into a filename-safe slug."""
    slug = normalize_name(value).replace(" ", "-")
    return slug or "institution"


def infer_parent_institution(name: str | None) -> str | None:
    """Infer a parent institution/system name when a campus qualifier exists."""
    if not name:
        return None
    clean = display_name(name)
    lowered = clean.lower()

    def _validated(candidate: str | None) -> str | None:
        if not candidate:
            return None
        normalized = normalize_name(candidate)
        tokens = normalized.split()
        if len(tokens) < 2:
            return None
        if normalized in _GENERIC_PARENT_NAMES:
            return None
        if not any(hint in normalized for hint in ("university", "college", "institute", "system")):
            return None
        return display_name(candidate)

    if "," in clean:
        left, right = [chunk.strip() for chunk in clean.split(",", 1)]
        if right and any(token in right.lower() for token in _CAMPUS_SPLIT_MARKERS):
            return _validated(left)
        # Common pattern: "University of California, Berkeley"
        if right and len(right.split()) <= 4:
            return _validated(left)

    if " - " in clean:
        left, right = [chunk.strip() for chunk in clean.split(" - ", 1)]
        if right and any(token in right.lower() for token in _CAMPUS_SPLIT_MARKERS):
            return _validated(left)

    for marker in _CAMPUS_SPLIT_MARKERS:
        if marker in lowered:
            idx = lowered.index(marker)
            candidate = clean[:idx].strip(" ,-")
            return _validated(candidate)

    return None


def normalize_domain(value: str) -> str | None:
    """Normalize a host/domain string to a valid `.edu` hostname.

    Subdomains are preserved as-is (e.g. ``library.harvard.edu`` stays
    ``library.harvard.edu``).  Only the ``www.`` prefix is stripped, since
    it is a technical alias rather than a distinct service domain.

    Args:
        value: A raw domain name, URL, or hostname string.

    Returns:
        The normalized hostname (possibly a subdomain), or ``None`` when the
        input does not resolve to a ``.edu`` domain.
    """
    candidate = unescape(value).strip().lower()
    if not candidate:
        return None
    if "://" in candidate:
        candidate = urlparse(candidate).hostname or ""
    candidate = candidate.strip("./")
    if candidate.startswith("www."):
        candidate = candidate[4:]
    if not candidate:
        return None
    parts = candidate.split(".")
    if len(parts) >= 2 and parts[-1] == "edu":
        return candidate
    return None


def is_subdomain(domain: str) -> bool:
    """Return ``True`` when *domain* is a subdomain of an apex ``.edu`` domain.

    An apex ``.edu`` domain has exactly two labels (e.g. ``mit.edu``).
    Anything with three or more labels is a subdomain
    (e.g. ``library.mit.edu``).

    Args:
        domain: A normalized ``.edu`` hostname.

    Returns:
        ``True`` for subdomains, ``False`` for apex domains.
    """
    parts = domain.split(".")
    return len(parts) > 2 and parts[-1] == "edu"


def normalize_web_page(value: str, domain: str | None = None) -> str | None:
    """Normalize an institution homepage URL."""
    raw = unescape(value).strip()
    if not raw and domain:
        return f"https://{domain}/"
    if not raw:
        return None
    parsed = urlparse(raw)
    if not parsed.scheme:
        raw = f"https://{raw.lstrip('/')}"
        parsed = urlparse(raw)
    hostname = parsed.hostname or ""
    normalized = normalize_domain(hostname) or domain
    if not normalized:
        return None
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    return f"https://{normalized}{path}"


def is_likely_higher_ed_name(name: str | None) -> bool:
    """Return whether a source label looks like higher education."""
    if not name:
        return False
    normalized = normalize_name(name)
    if any(token in normalized for token in _NEGATIVE_NAME_HINTS):
        return False
    if any(token in normalized for token in _POSITIVE_NAME_HINTS):
        return True
    return "academy" in normalized and "military" in normalized


def _extract_name_from_inventory_title(title: str) -> str | None:
    text = display_name(title)
    if not text:
        return None
    head = re.split(r"\s*(?:\||-|:)+\s*", text, maxsplit=1)[0].strip()
    return head or text


def load_edu_inventory_records() -> list[SourceRecord]:
    """Load the legacy `.edu` inventory CSV as low-confidence evidence rows."""
    rows: list[SourceRecord] = []
    content = _fetch_text(SOURCE_URLS["edu_inventory"])
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        domain = normalize_domain(row.get("URL", ""))
        if not domain:
            continue
        title = row.get("Title", "")
        name = _extract_name_from_inventory_title(title)
        if not is_likely_higher_ed_name(name):
            continue
        web_page = normalize_web_page(row.get("Final URL", ""), domain)
        rows.append(
            SourceRecord(
                source_id=f"edu_inventory:{domain}",
                source_type="edu_inventory",
                name=name,
                domains={domain},
                web_pages={web_page} if web_page else set(),
                notes=["Derived from edu-inventory title metadata."],
            )
        )
    return rows


def load_hipo_records() -> list[SourceRecord]:
    """Load USA institution rows from Hipo's university domain dataset."""
    rows: list[SourceRecord] = []
    data = json.loads(_fetch_text(SOURCE_URLS["hipo"]))
    for entry in data:
        if entry.get("alpha_two_code") != "US" and entry.get("country") != "United States":
            continue
        domains = {domain for raw in entry.get("domains") or [] if (domain := normalize_domain(raw))}
        if not domains:
            continue
        web_pages = {
            page
            for raw in entry.get("web_pages") or []
            if (page := normalize_web_page(raw))
        }
        name = display_name(entry.get("name") or "")
        if not is_likely_higher_ed_name(name):
            continue
        rows.append(
            SourceRecord(
                source_id=f"hipo:{name}",
                source_type="hipo",
                name=name,
                domains=domains,
                web_pages=web_pages,
            )
        )
    return rows


def load_node_records() -> list[SourceRecord]:
    """Load USA institution rows from the node-university-domains dataset."""
    rows: list[SourceRecord] = []
    content = _fetch_text(SOURCE_URLS["node_university_domains"])
    payload = content.split("=", 1)[1].strip().rstrip(";")
    data = json.loads(payload)
    for entry in data:
        if entry.get("country") not in {"USA", "United States"}:
            continue
        domain = normalize_domain(entry.get("domain", ""))
        if not domain:
            continue
        name = display_name(entry.get("name") or "")
        if not is_likely_higher_ed_name(name):
            continue
        page = normalize_web_page(entry.get("web_page", ""), domain)
        rows.append(
            SourceRecord(
                source_id=f"node:{name}",
                source_type="node_university_domains",
                name=name,
                domains={domain},
                web_pages={page} if page else set(),
            )
        )
    return rows


def load_academic_domain_records() -> tuple[list[SourceRecord], list[dict[str, str]]]:
    """Load USA `.edu` domains from the academic-domains dataset.

    The dataset has domains but no institution names, so unmatched domains are
    tracked separately for review instead of being force-labeled as institutions.
    """
    rows: list[SourceRecord] = []
    orphans: list[dict[str, str]] = []
    data = json.loads(_fetch_text(SOURCE_URLS["academic_domains"]))
    for entry in data:
        if entry.get("country_alpha_2") != "US":
            continue
        domain = normalize_domain(entry.get("domain", ""))
        if not domain:
            continue
        record = SourceRecord(
            source_id=f"academic:{domain}",
            source_type="academic_domains",
            name=None,
            domains={domain},
            web_pages={normalize_web_page("", domain)},
            notes=["Domain-only evidence from world_academic_domains.json."],
        )
        rows.append(record)
        orphans.append({"domain": domain, "source": "academic_domains"})
    return rows, orphans


def load_swot_records() -> tuple[list[SourceRecord], list[dict[str, str]]]:
    """Load `.edu` institution rows from SWOT's domain tree tarball."""
    rows: list[SourceRecord] = []
    orphans: list[dict[str, str]] = []
    payload = _fetch_bytes(SOURCE_URLS["swot_tarball"])
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile() or "/domains/edu/" not in member.name or not member.name.endswith(".txt"):
                continue
            domain_slug = Path(member.name).stem
            domain = normalize_domain(f"{domain_slug}.edu")
            if not domain:
                continue
            file_obj = archive.extractfile(member)
            if file_obj is None:
                continue
            name = display_name(file_obj.read().decode("utf-8").strip())
            if not is_likely_higher_ed_name(name):
                continue
            record = SourceRecord(
                source_id=f"swot:{domain}",
                source_type="swot",
                name=name,
                domains={domain},
                web_pages={normalize_web_page("", domain)},
            )
            rows.append(record)
            orphans.append({"domain": domain, "source": "swot", "name": name})
    return rows, orphans


def merge_source_records(records: list[SourceRecord]) -> tuple[list[InstitutionRecord], set[str]]:
    """Merge overlapping source records into institution records."""
    institutions: list[InstitutionRecord] = []
    domain_index: dict[str, int] = {}
    name_index: dict[str, int] = {}
    matched_name_less_domains: set[str] = set()

    for record in records:
        target_idx: int | None = None
        for domain in sorted(record.domains):
            if domain in domain_index:
                target_idx = domain_index[domain]
                break
        if target_idx is None and record.name:
            target_idx = name_index.get(normalize_name(record.name))

        if target_idx is None:
            if not record.name:
                matched_name_less_domains.update(record.domains)
                continue
            institution = InstitutionRecord(
                name=display_name(record.name),
                normalized_name=normalize_name(record.name),
                domains=set(record.domains),
                web_pages=set(record.web_pages),
                source_ids={record.source_id},
                source_types={record.source_type},
                parent_institution=infer_parent_institution(record.name),
                notes=list(record.notes),
            )
            institutions.append(institution)
            target_idx = len(institutions) - 1
        else:
            institution = institutions[target_idx]
            if record.name and len(display_name(record.name)) > len(institution.name):
                institution.name = display_name(record.name)
                institution.normalized_name = normalize_name(record.name)
            if record.name and institution.parent_institution is None:
                institution.parent_institution = infer_parent_institution(record.name)
            institution.domains.update(record.domains)
            institution.web_pages.update(record.web_pages)
            institution.source_ids.add(record.source_id)
            institution.source_types.add(record.source_type)
            institution.notes.extend(record.notes)

        institution = institutions[target_idx]
        for domain in institution.domains:
            domain_index[domain] = target_idx
        name_index[institution.normalized_name] = target_idx

    return institutions, matched_name_less_domains


def build_usa_edu_dataset() -> BuildResult:
    """Aggregate all configured source datasets into a deduplicated master list."""
    source_counts: dict[str, int] = {}

    hipo_records = load_hipo_records()
    source_counts["hipo"] = len(hipo_records)

    node_records = load_node_records()
    source_counts["node_university_domains"] = len(node_records)

    edu_inventory_records = load_edu_inventory_records()
    source_counts["edu_inventory"] = len(edu_inventory_records)

    swot_records, swot_orphans = load_swot_records()
    source_counts["swot"] = len(swot_records)

    academic_records, academic_orphans = load_academic_domain_records()
    source_counts["academic_domains"] = len(academic_records)

    named_records = hipo_records + node_records + edu_inventory_records + swot_records
    institutions, unmatched_domains = merge_source_records(named_records + academic_records)

    institutions.sort(key=lambda item: item.name.lower())

    matched_domains = {domain for item in institutions for domain in item.domains}
    orphan_domains = [
        row
        for row in (swot_orphans + academic_orphans)
        if row["domain"] not in matched_domains or row["domain"] in unmatched_domains
    ]
    orphan_domains.sort(key=lambda item: (item["domain"], item["source"]))

    return BuildResult(
        institutions=institutions,
        orphan_domains=orphan_domains,
        source_counts=source_counts,
    )


def _institution_to_json(institution: InstitutionRecord) -> dict[str, Any]:
    domains = sorted(institution.domains)
    web_pages = sorted(institution.web_pages)
    primary_domain = domains[0] if domains else ""
    return {
        "name": institution.name,
        "slug": slugify(institution.name),
        "parent_institution": institution.parent_institution,
        "primary_domain": primary_domain,
        "domains": domains,
        "web_pages": web_pages,
        "source_ids": sorted(institution.source_ids),
        "source_types": sorted(institution.source_types),
        "source_count": len(institution.source_types),
        "notes": sorted(set(institution.notes)),
    }


def build_parent_groups(institutions_payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group institutions under inferred parent institutions/systems."""
    grouped: dict[str, dict[str, Any]] = {}
    for institution in institutions_payload:
        parent = institution.get("parent_institution")
        if not parent:
            continue
        bucket = grouped.setdefault(
            parent,
            {
                "parent_institution": parent,
                "institution_count": 0,
                "institutions": [],
                "domains": set(),
                "source_types": set(),
            },
        )
        bucket["institution_count"] += 1
        bucket["institutions"].append(institution["name"])
        bucket["domains"].update(institution.get("domains") or [])
        bucket["source_types"].update(institution.get("source_types") or [])

    rows: list[dict[str, Any]] = []
    for parent, payload in grouped.items():
        rows.append(
            {
                "parent_institution": parent,
                "institution_count": payload["institution_count"],
                "institutions": sorted(payload["institutions"]),
                "domains": sorted(payload["domains"]),
                "source_types": sorted(payload["source_types"]),
            }
        )
    rows.sort(key=lambda item: item["parent_institution"].lower())
    return rows


def write_master_outputs(result: BuildResult, imports_dir: Path, toon_dir: Path) -> None:
    """Write JSON, CSV, and TOON outputs for the built dataset."""
    imports_dir.mkdir(parents=True, exist_ok=True)
    toon_dir.mkdir(parents=True, exist_ok=True)

    institutions_payload = [_institution_to_json(item) for item in result.institutions]
    parent_groups_payload = build_parent_groups(institutions_payload)
    summary_payload = {
        "institution_count": len(result.institutions),
        "parent_group_count": len(parent_groups_payload),
        "orphan_domain_count": len(result.orphan_domains),
        "source_counts": result.source_counts,
        "institutions": institutions_payload,
    }
    (imports_dir / "usa-edu-master.json").write_text(
        json.dumps(summary_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with (imports_dir / "usa-edu-master.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "name",
                "slug",
                "parent_institution",
                "primary_domain",
                "domain_count",
                "source_count",
                "source_types",
                "web_pages",
            ]
        )
        for institution in institutions_payload:
            writer.writerow(
                [
                    institution["name"],
                    institution["slug"],
                    institution.get("parent_institution") or "",
                    institution["primary_domain"],
                    len(institution["domains"]),
                    institution["source_count"],
                    ";".join(institution["source_types"]),
                    ";".join(institution["web_pages"]),
                ]
            )

    (imports_dir / "usa-edu-parent-groups.json").write_text(
        json.dumps(parent_groups_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with (imports_dir / "usa-edu-parent-groups.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["parent_institution", "institution_count", "institution_names", "domains", "source_types"])
        for row in parent_groups_payload:
            writer.writerow(
                [
                    row["parent_institution"],
                    row["institution_count"],
                    ";".join(row["institutions"]),
                    ";".join(row["domains"]),
                    ";".join(row["source_types"]),
                ]
            )

    (imports_dir / "usa-edu-orphan-domains.json").write_text(
        json.dumps(result.orphan_domains, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with (imports_dir / "usa-edu-orphan-domains.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["domain", "source", "name"])
        writer.writeheader()
        for row in result.orphan_domains:
            writer.writerow({"domain": row.get("domain", ""), "source": row.get("source", ""), "name": row.get("name", "")})

    toon_payload = {
        "version": "0.1-seed",
        "country": "USA_EDU_MASTER",
        "dataset_scope": "United States higher-education institutions on .edu domains",
        "institution_count": len(institutions_payload),
        "parent_group_count": len(parent_groups_payload),
        "page_count": len(institutions_payload),
        "domains": [],
    }
    for institution in institutions_payload:
        homepage = institution["web_pages"][0] if institution["web_pages"] else f"https://{institution['primary_domain']}/"
        toon_payload["domains"].append(
            {
                "canonical_domain": institution["primary_domain"],
                "is_subdomain": is_subdomain(institution["primary_domain"]),
                "institution_name": institution["name"],
                "parent_institution": institution.get("parent_institution"),
                "affiliated_domains": institution["domains"],
                "source_types": institution["source_types"],
                "pages": [
                    {
                        "url": homepage,
                        "is_root_page": True,
                    }
                ],
            }
        )

    (toon_dir / "usa-edu-master.toon").write_text(
        json.dumps(toon_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    index_payload = {
        "version": "0.1-index",
        "files": [
            {
                "filename": "usa-edu-master.toon",
                "label": "USA EDU Master",
                "institution_count": len(institutions_payload),
            }
        ],
    }
    (toon_dir / "index.json").write_text(
        json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
