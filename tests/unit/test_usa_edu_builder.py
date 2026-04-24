"""Focused tests for the USA `.edu` dataset builder."""

from __future__ import annotations

from src.services.usa_edu_builder import (
    SourceRecord,
    build_parent_groups,
    infer_parent_institution,
    is_likely_higher_ed_name,
    merge_source_records,
    normalize_domain,
    normalize_name,
    normalize_web_page,
    slugify,
)


def test_normalize_domain_reduces_to_root_edu() -> None:
    assert normalize_domain("https://www.law.harvard.edu/about") == "harvard.edu"
    assert normalize_domain("student.eit.edu.au") is None


def test_normalize_web_page_uses_https_root_domain() -> None:
    assert normalize_web_page("http://www.mit.edu/", "mit.edu") == "https://mit.edu/"
    assert normalize_web_page("", "mit.edu") == "https://mit.edu/"


def test_name_helpers_are_stable() -> None:
    assert normalize_name("The University of Michigan") == "university of michigan"
    assert slugify("University of Michigan") == "university-of-michigan"


def test_higher_ed_name_filter_rejects_k12_titles() -> None:
    assert is_likely_higher_ed_name("University of Michigan") is True
    assert is_likely_higher_ed_name("Albuquerque Academy Day School") is False


def test_merge_source_records_joins_by_domain_then_name() -> None:
    records = [
        SourceRecord(
            source_id="hipo:Example University",
            source_type="hipo",
            name="Example University",
            domains={"example.edu"},
            web_pages={"https://example.edu/"},
        ),
        SourceRecord(
            source_id="node:Example University",
            source_type="node",
            name="Example University",
            domains={"example.edu"},
            web_pages={"https://example.edu/"},
        ),
        SourceRecord(
            source_id="swot:second.edu",
            source_type="swot",
            name="Second College",
            domains={"second.edu"},
            web_pages={"https://second.edu/"},
        ),
    ]

    institutions, unmatched = merge_source_records(records)

    assert len(institutions) == 2
    assert unmatched == set()
    merged = next(item for item in institutions if item.normalized_name == "example university")
    assert merged.domains == {"example.edu"}
    assert merged.source_types == {"hipo", "node"}


def test_infer_parent_institution_from_campus_style_name() -> None:
    parent = infer_parent_institution("University of California, Berkeley")
    assert parent == "University of California"


def test_infer_parent_institution_rejects_generic_single_word() -> None:
    parent = infer_parent_institution("The - Main Campus")
    assert parent is None


def test_build_parent_groups_collects_domains_and_children() -> None:
    payload = [
        {
            "name": "University of California, Berkeley",
            "parent_institution": "University of California",
            "domains": ["berkeley.edu"],
            "source_types": ["hipo"],
        },
        {
            "name": "University of California, Davis",
            "parent_institution": "University of California",
            "domains": ["ucdavis.edu"],
            "source_types": ["node_university_domains"],
        },
    ]

    grouped = build_parent_groups(payload)

    assert len(grouped) == 1
    uc_group = grouped[0]
    assert uc_group["parent_institution"] == "University of California"
    assert uc_group["institution_count"] == 2
    assert "berkeley.edu" in uc_group["domains"]
    assert "ucdavis.edu" in uc_group["domains"]