"""Tests for the domains report generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.cli.generate_domains_report import generate_domains_report


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def toon_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with sample TOON files."""
    countries_dir = tmp_path / "countries"
    countries_dir.mkdir()

    # Iceland TOON
    iceland = {
        "version": "0.1-seed",
        "country": "Iceland",
        "domain_count": 2,
        "page_count": 4,
        "domains": [
            {
                "canonical_domain": "example.is",
                "pages": [
                    {"url": "https://example.is/", "is_root_page": True},
                    {"url": "https://example.is/about", "is_root_page": False},
                ],
            },
            {
                "canonical_domain": "gov.is",
                "pages": [
                    {"url": "https://gov.is/", "is_root_page": True},
                    {"url": "https://gov.is/services", "is_root_page": False},
                ],
            },
        ],
    }
    (countries_dir / "iceland.toon").write_text(
        json.dumps(iceland), encoding="utf-8"
    )

    # France TOON
    france = {
        "version": "0.1-seed",
        "country": "France",
        "domain_count": 1,
        "page_count": 1,
        "domains": [
            {
                "canonical_domain": "gouvernement.fr",
                "pages": [
                    {"url": "https://www.gouvernement.fr/", "is_root_page": True},
                ],
            },
        ],
    }
    (countries_dir / "france.toon").write_text(
        json.dumps(france), encoding="utf-8"
    )

    return countries_dir


@pytest.fixture
def empty_toon_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with no TOON files."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    return empty_dir


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_generate_domains_report_creates_file(toon_dir: Path, tmp_path: Path):
    """Report file should be created."""
    output_path = tmp_path / "domains.md"
    generate_domains_report(toon_dir, output_path)
    assert output_path.exists()


def test_generate_domains_report_empty_dir(empty_toon_dir: Path, tmp_path: Path):
    """Report should be created gracefully when no TOON files exist."""
    output_path = tmp_path / "domains.md"
    generate_domains_report(empty_toon_dir, output_path)
    assert output_path.exists()
    content = output_path.read_text()
    assert "title: Government Domains" in content
    assert "layout: page" in content
    assert "No TOON seed files found" in content


def test_generate_domains_report_has_expected_sections(
    toon_dir: Path, tmp_path: Path
):
    """Report should contain country sections and domain tables."""
    output_path = tmp_path / "domains.md"
    generate_domains_report(toon_dir, output_path)
    content = output_path.read_text()

    assert "title: Government Domains" in content
    assert "layout: page" in content
    assert "## Countries" in content
    assert "## France" in content
    assert "## Iceland" in content


def test_generate_domains_report_domain_entries(toon_dir: Path, tmp_path: Path):
    """Each domain should appear in the report."""
    output_path = tmp_path / "domains.md"
    generate_domains_report(toon_dir, output_path)
    content = output_path.read_text()

    assert "example.is" in content
    assert "gov.is" in content
    assert "gouvernement.fr" in content


def test_generate_domains_report_totals(toon_dir: Path, tmp_path: Path):
    """Report header should show correct totals."""
    output_path = tmp_path / "domains.md"
    generate_domains_report(toon_dir, output_path)
    content = output_path.read_text()

    # 2 countries, 3 domains total, 5 pages total
    assert "2 countries" in content
    assert "3 domains" in content
    assert "5 pages" in content


def test_generate_domains_report_sorted_alphabetically(
    toon_dir: Path, tmp_path: Path
):
    """Countries should appear in alphabetical order."""
    output_path = tmp_path / "domains.md"
    generate_domains_report(toon_dir, output_path)
    content = output_path.read_text()

    france_pos = content.index("## France")
    iceland_pos = content.index("## Iceland")
    assert france_pos < iceland_pos, "France should appear before Iceland alphabetically"


def test_generate_domains_report_page_links(toon_dir: Path, tmp_path: Path):
    """Domain entries should include page links."""
    output_path = tmp_path / "domains.md"
    generate_domains_report(toon_dir, output_path)
    content = output_path.read_text()

    assert "https://example.is/" in content
    assert "https://www.gouvernement.fr/" in content
    assert "Visit example.is homepage" in content
    assert "[https://example.is/](https://example.is/)" not in content


def test_generate_domains_report_has_frontmatter(toon_dir: Path, tmp_path: Path):
    """Report should include Jekyll front matter."""
    output_path = tmp_path / "domains.md"
    generate_domains_report(toon_dir, output_path)
    content = output_path.read_text()

    assert content.startswith("---\n")
    assert "title: Government Domains" in content


def test_generate_domains_report_many_pages_truncated(
    tmp_path: Path,
):
    """Pages list should be truncated to 3 entries with a '+N more' note."""
    countries_dir = tmp_path / "countries"
    countries_dir.mkdir()
    toon = {
        "version": "0.1-seed",
        "country": "Testland",
        "domain_count": 1,
        "page_count": 10,
        "domains": [
            {
                "canonical_domain": "big.tl",
                "pages": [
                    {"url": f"https://big.tl/page{i}", "is_root_page": i == 0}
                    for i in range(10)
                ],
            }
        ],
    }
    (countries_dir / "testland.toon").write_text(
        json.dumps(toon), encoding="utf-8"
    )

    output_path = tmp_path / "domains.md"
    generate_domains_report(countries_dir, output_path)
    content = output_path.read_text()

    # Should mention "+7 more" (10 pages - 3 shown = 7)
    assert "+7 more" in content
