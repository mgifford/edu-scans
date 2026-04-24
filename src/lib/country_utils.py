"""Utility functions for URL validation scanner."""

from __future__ import annotations


_COUNTRY_DISPLAY_NAMES = {
    "REPUBLIC_OF_CYPRUS": "Cyprus",
    "UNITED_KINGDOM_UK": "United Kingdom",
}


def country_filename_to_code(filename: str) -> str:
    """
    Convert a country filename to a country code.

    Transforms lowercase hyphenated filenames to uppercase underscored codes.
    Example: "united-kingdom-uk" -> "UNITED_KINGDOM_UK"

    Args:
        filename: Lowercase hyphenated country name (without .toon extension)

    Returns:
        Uppercase underscored country code
    """
    return filename.upper().replace("-", "_")


def country_code_to_filename(country_code: str) -> str:
    """
    Convert a country code to a filename-safe format.

    Transforms uppercase underscored codes to lowercase hyphenated names.
    Example: "UNITED_KINGDOM_UK" -> "united-kingdom-uk"

    Args:
        country_code: Uppercase underscored country code

    Returns:
        Lowercase hyphenated filename (without extension)
    """
    return country_code.lower().replace("_", "-")


def country_code_to_display_name(country_code: str) -> str:
    """Return a human-friendly display label for a country code."""
    if country_code in _COUNTRY_DISPLAY_NAMES:
        return _COUNTRY_DISPLAY_NAMES[country_code]
    return country_code.replace("_", " ").title()
