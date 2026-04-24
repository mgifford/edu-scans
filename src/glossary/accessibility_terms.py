"""Multilingual terms for 'accessibility statement' across EU languages.

Covers all 24 official EU languages plus Norwegian and Icelandic (EEA members).
Terms are used by the accessibility scanner to detect footer links pointing to
an accessibility statement as required by the EU Web Accessibility Directive
(Directive 2016/2102) — see https://web-directive.eu/#toc20
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# ACCESSIBILITY_TERMS
# Maps ISO 639-1 language code → list of term variants (lower-case) that
# appear in the visible link text or href of an accessibility statement link.
# Each language includes both the full phrase and common abbreviations or
# alternative phrasings found in the wild.
# ---------------------------------------------------------------------------

ACCESSIBILITY_TERMS: dict[str, list[str]] = {
    # Bulgarian
    "bg": [
        "декларация за достъпност",
        "достъпност",
    ],
    # Croatian
    "hr": [
        "izjava o pristupačnosti",
        "pristupačnost",
    ],
    # Czech
    "cs": [
        "prohlášení o přístupnosti",
        "přístupnost",
    ],
    # Danish
    "da": [
        "tilgængelighedserklæring",
        "tilgængelighed",
    ],
    # Dutch
    "nl": [
        "toegankelijkheidsverklaring",
        "toegankelijkheid",
    ],
    # English
    "en": [
        "accessibility statement",
        "accessibility",
    ],
    # Estonian
    "et": [
        "ligipääsetavuse teave",
        "juurdepääsetavuse deklaratsioon",
        "ligipääsetavus",
        "juurdepääsetavus",
    ],
    # Finnish
    "fi": [
        "saavutettavuusseloste",
        "saavutettavuus",
    ],
    # French
    "fr": [
        "déclaration d'accessibilité",
        "accessibilité",
    ],
    # German
    "de": [
        "erklärung zur barrierefreiheit",
        "barrierefreiheitserklärung",
        "barrierefreiheit",
    ],
    # Greek
    "el": [
        "δήλωση προσβασιμότητας",
        "προσβασιμότητα",
    ],
    # Hungarian
    "hu": [
        "akadálymentesítési nyilatkozat",
        "akadálymentesség",
    ],
    # Icelandic (EEA)
    "is": [
        "aðgengisyfirlýsing",
        "aðgengi",
    ],
    # Irish
    "ga": [
        "ráiteas inrochtaineachta",
        "inrochtaineacht",
    ],
    # Italian
    "it": [
        "dichiarazione di accessibilità",
        "accessibilità",
    ],
    # Latvian
    "lv": [
        "piekļūstamības paziņojums",
        "piekļūstamība",
    ],
    # Lithuanian
    "lt": [
        "prieinamumo deklaracija",
        "prieinamumas",
    ],
    # Maltese
    "mt": [
        "dikjarazzjoni ta' aċċessibbiltà",
        "aċċessibbiltà",
    ],
    # Norwegian (EEA)
    "no": [
        "tilgjengelighetserklæring",
        "tilgjengelighet",
    ],
    # Polish
    "pl": [
        "deklaracja dostępności",
        "dostępność",
    ],
    # Portuguese
    "pt": [
        "declaração de acessibilidade",
        "acessibilidade",
    ],
    # Romanian
    "ro": [
        "declarație de accesibilitate",
        "accesibilitate",
    ],
    # Slovak
    "sk": [
        "vyhlásenie o prístupnosti",
        "prístupnosť",
    ],
    # Slovenian
    "sl": [
        "izjava o dostopnosti",
        "dostopnost",
    ],
    # Spanish
    "es": [
        "declaración de accesibilidad",
        "accesibilidad",
    ],
    # Swedish
    "sv": [
        "tillgänglighetsredogörelse",
        "tillgänglighetsutlåtande",
        "tillgänglighet",
    ],
}

# Flat list of all terms (lower-case) for quick membership tests.
ALL_TERMS: frozenset[str] = frozenset(
    term for terms in ACCESSIBILITY_TERMS.values() for term in terms
)

# Common URL path fragments that appear in accessibility statement URLs across
# EU government websites, regardless of the page language.
ACCESSIBILITY_URL_PATTERNS: tuple[str, ...] = (
    "accessibility",
    "accessibility-statement",
    "accessibilite",
    "accessibilidad",
    "accessibilita",
    "barrierefreiheit",
    "barrierefreiheitserklaerung",
    "dostupnost",
    "dostepnosc",
    "dostupnosti",
    "przystepnosc",
    "prieinamumas",
    "pieklijstamiba",
    "saavutettavuus",
    "tilgaengelighed",
    "tilgjengelighet",
    "toegankelijkheid",
    "pristupacnost",
    "dostopnost",
    "acessibilidade",
    "akadalymentesseg",
    "prohlaseni-o-pristupnosti",
    "deklaracja-dostepnosci",
    "adgengisyfirlysing",
)
