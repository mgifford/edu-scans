"""Unit tests for country utility functions."""

from src.lib.country_utils import (
    country_code_to_display_name,
    country_code_to_filename,
    country_filename_to_code,
)


def test_country_filename_to_code():
    """Test converting filename to country code."""
    assert country_filename_to_code("iceland") == "ICELAND"
    assert country_filename_to_code("united-kingdom-uk") == "UNITED_KINGDOM_UK"
    assert country_filename_to_code("republic-of-cyprus") == "REPUBLIC_OF_CYPRUS"


def test_country_code_to_filename():
    """Test converting country code to filename."""
    assert country_code_to_filename("ICELAND") == "iceland"
    assert country_code_to_filename("UNITED_KINGDOM_UK") == "united-kingdom-uk"
    assert country_code_to_filename("REPUBLIC_OF_CYPRUS") == "republic-of-cyprus"


def test_roundtrip_conversion():
    """Test that conversions are reversible."""
    filenames = ["iceland", "france", "united-kingdom-uk", "republic-of-cyprus"]
    
    for filename in filenames:
        code = country_filename_to_code(filename)
        result = country_code_to_filename(code)
        assert result == filename


def test_roundtrip_conversion_from_code():
    """Test that conversions are reversible from code."""
    codes = ["ICELAND", "FRANCE", "UNITED_KINGDOM_UK", "REPUBLIC_OF_CYPRUS"]
    
    for code in codes:
        filename = country_code_to_filename(code)
        result = country_filename_to_code(filename)
        assert result == code


def test_country_code_to_display_name():
    """Test converting country codes to human-friendly display names."""
    assert country_code_to_display_name("ICELAND") == "Iceland"
    assert country_code_to_display_name("REPUBLIC_OF_CYPRUS") == "Cyprus"
    assert country_code_to_display_name("UNITED_KINGDOM_UK") == "United Kingdom"
