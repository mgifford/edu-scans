"""Tests for validation report generation."""

import sqlite3
from pathlib import Path

import pytest

from src.cli.generate_validation_report import generate_report, _country_anchor
from src.storage.schema import initialize_schema


@pytest.fixture
def test_db(tmp_path):
    """Create a test database with sample data."""
    db_path = tmp_path / "test.db"
    initialize_schema(f"sqlite:///{db_path}")
    
    conn = sqlite3.connect(db_path)
    try:
        # Insert sample validation results
        conn.execute(
            """
            INSERT INTO url_validation_results
            (url, country_code, scan_id, status_code, error_message,
             redirected_to, redirect_chain, is_valid, failure_count, validated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "https://example.com/page1",
                "ICELAND",
                "ICELAND-20240101-000000000000-test1234",
                200,
                None,
                None,
                None,
                1,
                0,
                "2024-01-01T00:00:00+00:00",
            ),
        )
        
        conn.execute(
            """
            INSERT INTO url_validation_results
            (url, country_code, scan_id, status_code, error_message,
             redirected_to, redirect_chain, is_valid, failure_count, validated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "https://example.com/broken",
                "ICELAND",
                "ICELAND-20240101-000000000000-test1234",
                404,
                "Not Found",
                None,
                None,
                0,
                1,
                "2024-01-01T00:00:00+00:00",
            ),
        )
        
        conn.execute(
            """
            INSERT INTO url_validation_results
            (url, country_code, scan_id, status_code, error_message,
             redirected_to, redirect_chain, is_valid, failure_count, validated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "https://example.com/removed",
                "ICELAND",
                "ICELAND-20240101-000000000000-test1234",
                None,
                "Connection timeout",
                None,
                None,
                0,
                2,
                "2024-01-01T00:00:00+00:00",
            ),
        )
        
        conn.commit()
    finally:
        conn.close()
    
    return db_path


def test_generate_report_creates_file(test_db, tmp_path):
    """Test that report generation creates a markdown file."""
    output_path = tmp_path / "report.md"
    
    generate_report(test_db, output_path)
    
    assert output_path.exists()
    content = output_path.read_text()
    assert "# URL Validation Report" in content
    assert "ICELAND" in content


def test_generate_report_includes_statistics(test_db, tmp_path):
    """Test that report includes correct statistics."""
    output_path = tmp_path / "report.md"
    
    generate_report(test_db, output_path)
    
    content = output_path.read_text()
    # Should show: 3 total, 1 valid, 2 invalid, 0 redirected, 1 removed
    # Format: | Country | Total | Valid | Invalid | Redirected | Removed | Success Rate |
    assert "| ICELAND | 3 | 1 | 2 | 0 | 1 |" in content
    assert "33.3%" in content  # Success rate should be ~33.3% (1 valid out of 3)


def test_generate_report_shows_errors(test_db, tmp_path):
    """Test that report shows error details."""
    output_path = tmp_path / "report.md"
    
    generate_report(test_db, output_path)
    
    content = output_path.read_text()
    assert "https://example.com/broken" in content
    assert "https://example.com/removed" in content
    assert "⚠️ **REMOVED**" in content  # URL that failed twice


def test_generate_report_handles_empty_database(tmp_path):
    """Test that report handles empty database gracefully."""
    db_path = tmp_path / "empty.db"
    initialize_schema(f"sqlite:///{db_path}")
    
    output_path = tmp_path / "report.md"
    
    generate_report(db_path, output_path)
    
    assert output_path.exists()
    content = output_path.read_text()
    assert "No validation data available" in content


def test_generate_report_handles_missing_database(tmp_path):
    """Test that report handles missing database gracefully."""
    db_path = tmp_path / "nonexistent.db"
    output_path = tmp_path / "report.md"
    
    # Should not raise an exception
    generate_report(db_path, output_path)


# ---------------------------------------------------------------------------
# Anchor link / navigation tests
# ---------------------------------------------------------------------------

def test_country_anchor_simple():
    """_country_anchor should lowercase and prefix with 'errors-'."""
    assert _country_anchor("ICELAND") == "errors-iceland"


def test_country_anchor_with_underscores():
    """_country_anchor should replace underscores with hyphens."""
    assert _country_anchor("UNITED_KINGDOM_UK") == "errors-united-kingdom-uk"


def test_generate_report_has_explicit_top_anchor(test_db, tmp_path):
    """Report should begin with an explicit anchor id for back-to-top links."""
    output_path = tmp_path / "report.md"

    generate_report(test_db, output_path)

    content = output_path.read_text()
    assert '<a id="url-validation-report"></a>' in content


def test_generate_report_has_table_of_contents(test_db, tmp_path):
    """Report should include a Contents/TOC section with anchor links."""
    output_path = tmp_path / "report.md"

    generate_report(test_db, output_path)

    content = output_path.read_text()
    assert "## Contents" in content
    assert "[Summary by Country](#summary-by-country)" in content
    assert "[Legend](#legend)" in content


def test_generate_report_toc_includes_errors_section(test_db, tmp_path):
    """TOC should list 'Errors by Country' when errors exist."""
    output_path = tmp_path / "report.md"

    generate_report(test_db, output_path)

    content = output_path.read_text()
    assert "[Errors by Country](#errors-by-country)" in content


def test_generate_report_toc_includes_country_links(test_db, tmp_path):
    """TOC should contain per-country anchor links for countries with errors."""
    output_path = tmp_path / "report.md"

    generate_report(test_db, output_path)

    content = output_path.read_text()
    # ICELAND has 2 errors in the fixture
    assert "(#errors-iceland)" in content


def test_generate_report_country_anchor_ids(test_db, tmp_path):
    """Each country with errors should have a stable HTML anchor id."""
    output_path = tmp_path / "report.md"

    generate_report(test_db, output_path)

    content = output_path.read_text()
    assert '<a id="errors-iceland"></a>' in content


def test_generate_report_back_to_top_links(test_db, tmp_path):
    """Each country error section should end with a back-to-top link."""
    output_path = tmp_path / "report.md"

    generate_report(test_db, output_path)

    content = output_path.read_text()
    assert "[↑ Back to top](#url-validation-report)" in content


def test_generate_report_no_toc_when_no_errors(tmp_path):
    """When there are no errors, the TOC should not include an Errors section."""
    db_path = tmp_path / "valid_only.db"
    initialize_schema(f"sqlite:///{db_path}")

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO url_validation_results
            (url, country_code, scan_id, status_code, error_message,
             redirected_to, redirect_chain, is_valid, failure_count, validated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "https://example.com/ok",
                "NORWAY",
                "NORWAY-20240101-000000000000-test0001",
                200,
                None,
                None,
                None,
                1,
                0,
                "2024-01-01T00:00:00+00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    output_path = tmp_path / "report.md"
    generate_report(db_path, output_path)

    content = output_path.read_text()
    assert "## Contents" in content
    assert "Errors by Country" not in content
    assert "#errors-" not in content
