#!/usr/bin/env python3
"""Split the USA EDU master TOON seed file into per-state TOON files.

Reads ``data/toon-seeds/usa-edu-master.toon`` and writes one TOON file per
US state under ``data/toon-seeds/``.  Each output file is named using the
lowercase-hyphenated convention (e.g. ``usa-edu-california.toon``) and
carries ``"country": "USA_EDU_<STATE_CODE>"`` so it is automatically picked
up by the existing ``--all`` scan mode and the report generator.

State assignment uses a multi-tier strategy:

1. **Domain → state mapping**: a curated dict of well-known institution
   domains to their home state, covering major public and private universities.
2. **Institution name patterns**: regex matching for "University of <State>",
   "<State> State University / College", "<State> Community College", etc.
3. **City/campus suffixes**: common campus identifiers appended to names
   (e.g. "Michigan State – Lansing" → Michigan).
4. **Unknown fallback**: institutions that cannot be resolved are written to
   a special ``data/toon-seeds/usa-edu-unknown-state.toon`` file for manual
   review rather than being silently dropped.

Usage::

    python3 scripts/split_toon_by_state.py [--master <toon>] [--output-dir <dir>]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_MASTER_TOON = REPO_ROOT / "data" / "toon-seeds" / "usa-edu-master.toon"
_DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "toon-seeds"

# ---------------------------------------------------------------------------
# State abbreviation ↔ full-name mappings
# ---------------------------------------------------------------------------

STATE_ABBR_TO_NAME: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
    # Territories (treated as separate groups)
    "DC": "District of Columbia", "PR": "Puerto Rico", "GU": "Guam",
    "VI": "Virgin Islands", "AS": "American Samoa", "MP": "Northern Mariana Islands",
}

STATE_NAME_TO_ABBR: dict[str, str] = {v.lower(): k for k, v in STATE_ABBR_TO_NAME.items()}

# All full state names (lower-cased) for fast membership testing
_STATE_NAMES_LOWER: frozenset[str] = frozenset(STATE_NAME_TO_ABBR)

# ---------------------------------------------------------------------------
# Curated domain → state mapping for well-known institutions
# ---------------------------------------------------------------------------

DOMAIN_TO_STATE: dict[str, str] = {
    # Ivy League & top private universities
    "harvard.edu": "Massachusetts",
    "mit.edu": "Massachusetts",
    "stanford.edu": "California",
    "yale.edu": "Connecticut",
    "princeton.edu": "New Jersey",
    "columbia.edu": "New York",
    "upenn.edu": "Pennsylvania",
    "brown.edu": "Rhode Island",
    "dartmouth.edu": "New Hampshire",
    "cornell.edu": "New York",
    "carnegiemellon.edu": "Pennsylvania",
    "cmu.edu": "Pennsylvania",
    "nyu.edu": "New York",
    "tufts.edu": "Massachusetts",
    "boston.edu": "Massachusetts",
    "bu.edu": "Massachusetts",
    "bc.edu": "Massachusetts",
    "brandeis.edu": "Massachusetts",
    "northeastern.edu": "Massachusetts",
    "caltech.edu": "California",
    "uchicago.edu": "Illinois",
    "northwestern.edu": "Illinois",
    "nd.edu": "Indiana",
    "notredame.edu": "Indiana",
    "jh.edu": "Maryland",
    "jhu.edu": "Maryland",
    "jhuapl.edu": "Maryland",
    "vanderbilt.edu": "Tennessee",
    "rice.edu": "Texas",
    "duke.edu": "North Carolina",
    "wakeforest.edu": "North Carolina",
    "emory.edu": "Georgia",
    "tulane.edu": "Louisiana",
    "georgetown.edu": "District of Columbia",
    "american.edu": "District of Columbia",
    "gwu.edu": "District of Columbia",
    "cua.edu": "District of Columbia",
    "howard.edu": "District of Columbia",
    "gallaudet.edu": "District of Columbia",
    "rochester.edu": "New York",
    "case.edu": "Ohio",
    "lehigh.edu": "Pennsylvania",
    "drexel.edu": "Pennsylvania",
    "villanova.edu": "Pennsylvania",
    "fordham.edu": "New York",
    "stjohns.edu": "New York",
    "stonybrook.edu": "New York",
    "marquette.edu": "Wisconsin",
    "scu.edu": "California",
    "usc.edu": "California",
    "isi.edu": "California",
    "pepperdine.edu": "California",
    "lmu.edu": "California",
    "usfca.edu": "California",
    "sandiego.edu": "California",
    "csus.edu": "California",
    "du.edu": "Colorado",
    "regis.edu": "Colorado",
    "mines.edu": "Colorado",
    "tcu.edu": "Texas",
    "smu.edu": "Texas",
    "baylor.edu": "Texas",
    "miami.edu": "Florida",
    "rollins.edu": "Florida",
    "stetson.edu": "Florida",
    "wm.edu": "Virginia",
    "rmc.edu": "Virginia",
    "vmi.edu": "Virginia",
    "hampden-sydney.edu": "Virginia",
    "washu.edu": "Missouri",
    "rockhurst.edu": "Missouri",
    "denison.edu": "Ohio",
    "oberlin.edu": "Ohio",
    "kenyon.edu": "Ohio",
    "wooster.edu": "Ohio",
    "grinnell.edu": "Iowa",
    "lawrence.edu": "Wisconsin",
    "beloit.edu": "Wisconsin",
    "carleton.edu": "Minnesota",
    "macalester.edu": "Minnesota",
    "hamline.edu": "Minnesota",
    "stthomas.edu": "Minnesota",
    "middlebury.edu": "Vermont",
    "norwich.edu": "Vermont",
    "amherst.edu": "Massachusetts",
    "wellesley.edu": "Massachusetts",
    "smith.edu": "Massachusetts",
    "mtholyoke.edu": "Massachusetts",
    "holycross.edu": "Massachusetts",
    "williams.edu": "Massachusetts",
    "bowdoin.edu": "Maine",
    "bates.edu": "Maine",
    "colby.edu": "Maine",
    "colgate.edu": "New York",
    "hamilton.edu": "New York",
    "skidmore.edu": "New York",
    "vassar.edu": "New York",
    "barnard.edu": "New York",
    "brynmawr.edu": "Pennsylvania",
    "haverford.edu": "Pennsylvania",
    "swarthmore.edu": "Pennsylvania",
    "gettysburg.edu": "Pennsylvania",
    "dickinson.edu": "Pennsylvania",
    "bucknell.edu": "Pennsylvania",
    "ursinus.edu": "Pennsylvania",
    "muhlenberg.edu": "Pennsylvania",
    "depauw.edu": "Indiana",
    "wabash.edu": "Indiana",
    "butler.edu": "Indiana",
    "earlham.edu": "Indiana",
    "ohio-state.edu": "Ohio",
    "osu.edu": "Ohio",
    "miami.muohio.edu": "Ohio",
    "miamioh.edu": "Ohio",
    "xavier.edu": "Ohio",
    "dayton.edu": "Ohio",
    "fisk.edu": "Tennessee",
    "meharry.edu": "Tennessee",
    "tuskegee.edu": "Alabama",
    "aamu.edu": "Alabama",
    "udc.edu": "District of Columbia",
    "umd.edu": "Maryland",
    "umbc.edu": "Maryland",
    "towson.edu": "Maryland",
    "salisbury.edu": "Maryland",
    "usna.edu": "Maryland",
    "usma.edu": "New York",
    "usafa.edu": "Colorado",
    "uscga.edu": "Connecticut",
    "nps.edu": "California",
    "nmt.edu": "New Mexico",
}

# ---------------------------------------------------------------------------
# Pattern-based state inference from institution names
# ---------------------------------------------------------------------------

# These patterns are checked in order.  Each is a (pattern_str, state_name)
# pair.  Matching is case-insensitive.  We check specific multi-word state
# names before single-word names to avoid ambiguity (e.g. "West Virginia"
# before "Virginia", "New York" before "York").

_NAME_PATTERNS: list[tuple[str, str]] = []

# Explicit multi-word state patterns first
_MULTI_WORD_STATES = [
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Rhode Island",
    "South Carolina", "South Dakota", "West Virginia",
    "District of Columbia",
]
for _state in _MULTI_WORD_STATES:
    _NAME_PATTERNS.append((_state, _state))

# Single-word states
_SINGLE_WORD_STATES = [s for s in STATE_ABBR_TO_NAME.values() if " " not in s]
for _state in _SINGLE_WORD_STATES:
    _NAME_PATTERNS.append((_state, _state))

# Additional campus-location suffixes that unambiguously identify a state
_CITY_PATTERNS: list[tuple[str, str]] = [
    (r"\bAnn Arbor\b", "Michigan"),
    (r"\bBaton Rouge\b", "Louisiana"),
    (r"\bLos Angeles\b", "California"),
    (r"\bSan Diego\b", "California"),
    (r"\bSan Francisco\b", "California"),
    (r"\bSan Jose\b", "California"),
    (r"\bSanta Barbara\b", "California"),
    (r"\bSanta Cruz\b", "California"),
    (r"\bSacramento\b", "California"),
    (r"\bFresno\b", "California"),
    (r"\bBerkeley\b", "California"),
    (r"\bIrvine\b", "California"),
    (r"\bRiverside\b", "California"),
    (r"\bStanislaus\b", "California"),
    (r"\bChico\b", "California"),
    (r"\bLong Beach\b", "California"),
    (r"\bFullerton\b", "California"),
    (r"\bPomona\b", "California"),
    (r"\bDominguez Hills\b", "California"),
    (r"\bEast Bay\b", "California"),
    (r"\bSan Bernardino\b", "California"),
    (r"\bSan Luis Obispo\b", "California"),
    (r"\bChicago\b", "Illinois"),
    (r"\bSpringfield\b", "Illinois"),
    (r"\bCarbondale\b", "Illinois"),
    (r"\bEdwardsville\b", "Illinois"),
    (r"\bDeKalb\b", "Illinois"),
    (r"\bAtlanta\b", "Georgia"),
    (r"\bSavannah\b", "Georgia"),
    (r"\bAugusta\b", "Georgia"),
    (r"\bDallas\b", "Texas"),
    (r"\bHouston\b", "Texas"),
    (r"\bSan Antonio\b", "Texas"),
    (r"\bAustin\b", "Texas"),
    (r"\bLubbock\b", "Texas"),
    (r"\bEl Paso\b", "Texas"),
    (r"\bDenton\b", "Texas"),
    (r"\bArlington\b", "Texas"),
    (r"\bSeattle\b", "Washington"),
    (r"\bSpokane\b", "Washington"),
    (r"\bBellingham\b", "Washington"),
    (r"\bTacoma\b", "Washington"),
    (r"\bPortland\b", "Oregon"),
    (r"\bEugene\b", "Oregon"),
    (r"\bCorvallis\b", "Oregon"),
    (r"\bDenver\b", "Colorado"),
    (r"\bBoulder\b", "Colorado"),
    (r"\bFort Collins\b", "Colorado"),
    (r"\bPueblo\b", "Colorado"),
    (r"\bPhoenix\b", "Arizona"),
    (r"\bTucson\b", "Arizona"),
    (r"\bTempe\b", "Arizona"),
    (r"\bFlagstaff\b", "Arizona"),
    (r"\bMinneapolis\b", "Minnesota"),
    (r"\bSt\. Paul\b", "Minnesota"),
    (r"\bDuluth\b", "Minnesota"),
    (r"\bMankato\b", "Minnesota"),
    (r"\bMoorhead\b", "Minnesota"),
    (r"\bColumbus\b", "Ohio"),
    (r"\bCleveland\b", "Ohio"),
    (r"\bCincinnati\b", "Ohio"),
    (r"\bToledo\b", "Ohio"),
    (r"\bYoungstown\b", "Ohio"),
    (r"\bAkron\b", "Ohio"),
    (r"\bBowling Green\b", "Ohio"),
    (r"\bKent\b", "Ohio"),
    (r"\bMiami\b", "Florida"),
    (r"\bTampa\b", "Florida"),
    (r"\bOrlando\b", "Florida"),
    (r"\bJacksonville\b", "Florida"),
    (r"\bGainesville\b", "Florida"),
    (r"\bTallahassee\b", "Florida"),
    (r"\bPensacola\b", "Florida"),
    (r"\bLakeland\b", "Florida"),
    (r"\bFort Lauderdale\b", "Florida"),
    (r"\bNew Orleans\b", "Louisiana"),
    (r"\bShreve[pP]ort\b", "Louisiana"),
    (r"\bNashville\b", "Tennessee"),
    (r"\bKnoxville\b", "Tennessee"),
    (r"\bMemphis\b", "Tennessee"),
    (r"\bChattanooga\b", "Tennessee"),
    (r"\bMurfreesboro\b", "Tennessee"),
    (r"\bDetroit\b", "Michigan"),
    (r"\bLansing\b", "Michigan"),
    (r"\bFlint\b", "Michigan"),
    (r"\bGrand Rapids\b", "Michigan"),
    (r"\bKalamazoo\b", "Michigan"),
    (r"\bMarquette\b", "Michigan"),
    (r"\bMadison\b", "Wisconsin"),
    (r"\bMilwaukee\b", "Wisconsin"),
    (r"\bGreen Bay\b", "Wisconsin"),
    (r"\bOshkosh\b", "Wisconsin"),
    (r"\bStout\b", "Wisconsin"),
    (r"\bLa Crosse\b", "Wisconsin"),
    (r"\bPlatteville\b", "Wisconsin"),
    (r"\bRiver Falls\b", "Wisconsin"),
    (r"\bWhitewater\b", "Wisconsin"),
    (r"\bIndianapolis\b", "Indiana"),
    (r"\bSouth Bend\b", "Indiana"),
    (r"\bTerre Haute\b", "Indiana"),
    (r"\bFort Wayne\b", "Indiana"),
    (r"\bMuncie\b", "Indiana"),
    (r"\bBloomington\b", "Indiana"),
    (r"\bPittsburgh\b", "Pennsylvania"),
    (r"\bPhiladelphia\b", "Pennsylvania"),
    (r"\bHarrisburg\b", "Pennsylvania"),
    (r"\bAllentown\b", "Pennsylvania"),
    (r"\bReadingPA\b", "Pennsylvania"),
    (r"\bScranton\b", "Pennsylvania"),
    (r"\bWilkes-Barre\b", "Pennsylvania"),
    (r"\bWilliamsport\b", "Pennsylvania"),
    (r"\bEdinboro\b", "Pennsylvania"),
    (r"\bSlippery Rock\b", "Pennsylvania"),
    (r"\bBaltimore\b", "Maryland"),
    (r"\bAnnapolis\b", "Maryland"),
    (r"\bRichmond\b", "Virginia"),
    (r"\bCharlottesville\b", "Virginia"),
    (r"\bNorfolk\b", "Virginia"),
    (r"\bBlacksburg\b", "Virginia"),
    (r"\bHarrisonburg\b", "Virginia"),
    (r"\bRoanoke\b", "Virginia"),
    (r"\bLynchburg\b", "Virginia"),
    (r"\bRaleigh\b", "North Carolina"),
    (r"\bCharlotte\b", "North Carolina"),
    (r"\bDurham\b", "North Carolina"),
    (r"\bGreensboro\b", "North Carolina"),
    (r"\bWinston-Salem\b", "North Carolina"),
    (r"\bWilmington\b", "North Carolina"),
    (r"\bColumbia\b.*South Carolina", "South Carolina"),
    (r"\bGreenville\b", "South Carolina"),
    (r"\bCharleston\b.*South Carolina", "South Carolina"),
    (r"\bSt\. Louis\b", "Missouri"),
    (r"\bKansas City\b", "Missouri"),
    (r"\bSpringfield\b.*Missouri", "Missouri"),
    (r"\bOmaha\b", "Nebraska"),
    (r"\bLincoln\b.*Nebraska", "Nebraska"),
    (r"\bDes Moines\b", "Iowa"),
    (r"\bIowa City\b", "Iowa"),
    (r"\bCedar Rapids\b", "Iowa"),
    (r"\bLittle Rock\b", "Arkansas"),
    (r"\bFayetteville\b.*Arkansas", "Arkansas"),
    (r"\bAlbuquerque\b", "New Mexico"),
    (r"\bSalt Lake\b", "Utah"),
    (r"\bProvo\b", "Utah"),
    (r"\bLas Vegas\b", "Nevada"),
    (r"\bReno\b", "Nevada"),
    (r"\bBoise\b", "Idaho"),
    (r"\bPocatello\b", "Idaho"),
    (r"\bBillings\b", "Montana"),
    (r"\bMissoula\b", "Montana"),
    (r"\bHelena\b", "Montana"),
    (r"\bBozeman\b", "Montana"),
    (r"\bFargo\b", "North Dakota"),
    (r"\bBismarck\b", "North Dakota"),
    (r"\bSioux Falls\b", "South Dakota"),
    (r"\bRapid City\b", "South Dakota"),
    (r"\bCheyenne\b", "Wyoming"),
    (r"\bLaramie\b", "Wyoming"),
    (r"\bAnchorage\b", "Alaska"),
    (r"\bJuneau\b", "Alaska"),
    (r"\bFairbanks\b", "Alaska"),
    (r"\bHonolulu\b", "Hawaii"),
    (r"\bHilo\b", "Hawaii"),
    (r"\bManoa\b", "Hawaii"),
    (r"\bBurlington\b.*Vermont", "Vermont"),
    (r"\bMontpelier\b", "Vermont"),
    (r"\bProvidence\b", "Rhode Island"),
    (r"\bKingston\b.*Rhode Island", "Rhode Island"),
    (r"\bHartford\b", "Connecticut"),
    (r"\bNew Haven\b", "Connecticut"),
    (r"\bBridgeport\b", "Connecticut"),
    (r"\bStamford\b", "Connecticut"),
    (r"\bNewark\b", "New Jersey"),
    (r"\bNew Brunswick\b", "New Jersey"),
    (r"\bTrenton\b", "New Jersey"),
    (r"\bDover\b.*Delaware", "Delaware"),
    (r"\bWilmington\b.*Delaware", "Delaware"),
    (r"\bConcord\b.*New Hampshire", "New Hampshire"),
    (r"\bManchester\b.*New Hampshire", "New Hampshire"),
    (r"\bPortland\b.*Maine", "Maine"),
    (r"\bBangor\b", "Maine"),
    (r"\bOrono\b", "Maine"),
    (r"\bBuffalo\b", "New York"),
    (r"\bAlbany\b", "New York"),
    (r"\bSyracuse\b", "New York"),
    (r"\bBinghamton\b", "New York"),
    (r"\bBrooklyn\b", "New York"),
    (r"\bBronx\b", "New York"),
    (r"\bQueens\b", "New York"),
    (r"\bManhattan\b", "New York"),
    (r"\bBoston\b", "Massachusetts"),
    (r"\bCambridge\b.*Massachusetts", "Massachusetts"),
    (r"\bSpringfield\b.*Massachusetts", "Massachusetts"),
    (r"\bLowell\b", "Massachusetts"),
    (r"\bAmherst\b", "Massachusetts"),
    (r"\bWorcester\b", "Massachusetts"),
    (r"\bWashington.*DC\b", "District of Columbia"),
    (r"\bWashington, D\.?C\b", "District of Columbia"),
    (r"\bAtlantic City\b", "New Jersey"),
    (r"\bBirmingham\b", "Alabama"),
    (r"\bMontgomery\b", "Alabama"),
    (r"\bMobile\b", "Alabama"),
    (r"\bHuntsville\b", "Alabama"),
    (r"\bTuscaloosa\b", "Alabama"),
    (r"\bAuburn\b", "Alabama"),
    (r"\bJackson\b.*Mississippi", "Mississippi"),
    (r"\bHattiesburg\b", "Mississippi"),
    (r"\bOxford\b.*Mississippi", "Mississippi"),
    (r"\bLexington\b.*Kentucky", "Kentucky"),
    (r"\bLouisville\b", "Kentucky"),
    (r"\bBowling Green\b.*Kentucky", "Kentucky"),
    (r"\bMorgantown\b", "West Virginia"),
    (r"\bHuntington\b.*West Virginia", "West Virginia"),
    (r"\bCharles[t]?on\b.*West Virginia", "West Virginia"),
    (r"\bOklahoma City\b", "Oklahoma"),
    (r"\bTulsa\b", "Oklahoma"),
    (r"\bNorman\b.*Oklahoma", "Oklahoma"),
    (r"\bStillwater\b.*Oklahoma", "Oklahoma"),
    (r"\bWichita\b", "Kansas"),
    (r"\bManhattan\b.*Kansas", "Kansas"),
    (r"\bLawrence\b.*Kansas", "Kansas"),
    (r"\bTopeka\b", "Kansas"),
]


def _infer_state_from_name(institution_name: str) -> str | None:
    """Infer the US state from an institution name using pattern matching.

    Tries multi-word state names before single-word names to avoid false
    positives, then falls back to city-location patterns.

    Args:
        institution_name: Raw institution name string.

    Returns:
        Full state name string (e.g. ``"California"``) or ``None`` if the
        state cannot be determined.
    """
    name_up = institution_name.upper()

    # Check name patterns (state names)
    for pattern_str, state in _NAME_PATTERNS:
        if re.search(pattern_str, institution_name, re.IGNORECASE):
            return state

    # Check city patterns
    for pattern_str, state in _CITY_PATTERNS:
        if re.search(pattern_str, institution_name, re.IGNORECASE):
            return state

    # Check state abbreviations at end of name, e.g. "Some College, TX"
    abbr_match = re.search(r",\s*([A-Z]{2})\s*$", institution_name)
    if abbr_match:
        abbr = abbr_match.group(1).upper()
        if abbr in STATE_ABBR_TO_NAME:
            return STATE_ABBR_TO_NAME[abbr]

    return None


def infer_state(domain_entry: dict) -> str:
    """Return the inferred US state for a TOON domain entry.

    Checks the curated domain mapping first, then tries name-pattern
    inference.

    Args:
        domain_entry: A single domain dict from the master TOON ``domains``
            array.

    Returns:
        Full state name string (e.g. ``"California"``), or ``"Unknown"`` when
        inference fails.
    """
    domain = domain_entry.get("canonical_domain", "").lower()
    if domain in DOMAIN_TO_STATE:
        return DOMAIN_TO_STATE[domain]

    name = domain_entry.get("institution_name", "")
    inferred = _infer_state_from_name(name)
    return inferred if inferred else "Unknown"


def _state_to_country_code(state: str) -> str:
    """Convert a state name to a country code string.

    Args:
        state: Full state name or ``"Unknown"``.

    Returns:
        Uppercase underscored code, e.g. ``"USA_EDU_CALIFORNIA"`` or
        ``"USA_EDU_UNKNOWN_STATE"``.
    """
    if state == "Unknown":
        return "USA_EDU_UNKNOWN_STATE"
    normalized = state.upper().replace(" ", "_").replace(".", "")
    return f"USA_EDU_{normalized}"


def _state_to_filename(state: str) -> str:
    """Convert a state name to a TOON filename stem.

    Args:
        state: Full state name or ``"Unknown"``.

    Returns:
        Lowercase hyphenated filename stem, e.g. ``"usa-edu-california"`` or
        ``"usa-edu-unknown-state"``.
    """
    if state == "Unknown":
        return "usa-edu-unknown-state"
    normalized = state.lower().replace(" ", "-").replace(".", "")
    return f"usa-edu-{normalized}"


def split_toon_by_state(
    master_toon: Path = _DEFAULT_MASTER_TOON,
    output_dir: Path = _DEFAULT_OUTPUT_DIR,
    dry_run: bool = False,
) -> dict[str, int]:
    """Split the master TOON into per-state TOON files.

    Args:
        master_toon: Path to the master TOON seed file.
        output_dir: Directory in which to write per-state TOON files.
        dry_run: When ``True``, print what would be written without
            creating any files.

    Returns:
        Dict mapping state name → number of institutions assigned to that
        state, sorted descending by count.
    """
    master_data = json.loads(master_toon.read_text(encoding="utf-8"))
    all_domains = master_data.get("domains", [])
    print(f"Loaded {len(all_domains)} domain entries from {master_toon}")

    # Assign each domain entry to a state bucket
    state_buckets: dict[str, list[dict]] = {}
    for entry in all_domains:
        state = infer_state(entry)
        state_buckets.setdefault(state, []).append(entry)

    # Report coverage
    known = sum(len(v) for k, v in state_buckets.items() if k != "Unknown")
    unknown = len(state_buckets.get("Unknown", []))
    total = len(all_domains)
    print(
        f"State assignment: {known}/{total} resolved "
        f"({known / total * 100:.1f}%), {unknown} unknown"
    )

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    written_counts: dict[str, int] = {}

    for state, entries in sorted(state_buckets.items()):
        country_code = _state_to_country_code(state)
        filename = _state_to_filename(state) + ".toon"
        out_path = output_dir / filename

        page_count = sum(len(e.get("pages", [])) for e in entries)
        toon_data = {
            "version": "0.1-seed",
            "country": country_code,
            "dataset_scope": (
                f"United States higher-education institutions in {state} on .edu domains"
                if state != "Unknown"
                else (
                    "United States higher-education institutions with undetermined "
                    "state on .edu domains"
                )
            ),
            "institution_count": len(entries),
            "parent_group_count": 0,
            "page_count": page_count,
            "domains": entries,
        }

        written_counts[state] = len(entries)

        if dry_run:
            print(
                f"  [DRY RUN] Would write {filename} "
                f"({len(entries)} institutions, {page_count} pages)"
            )
        else:
            out_path.write_text(
                json.dumps(toon_data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(
                f"  Written {filename} "
                f"({len(entries)} institutions, {page_count} pages)"
            )

    sorted_counts = dict(
        sorted(written_counts.items(), key=lambda kv: -kv[1])
    )
    print(f"\nTotal: {len(state_buckets)} state files")
    print("Top 10 states by institution count:")
    for state, count in list(sorted_counts.items())[:10]:
        print(f"  {state}: {count}")

    return sorted_counts


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Split the USA EDU master TOON seed file into per-state TOON files."
    )
    parser.add_argument(
        "--master",
        type=Path,
        default=_DEFAULT_MASTER_TOON,
        help=f"Master TOON seed file (default: {_DEFAULT_MASTER_TOON})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR,
        help=f"Output directory for per-state TOON files (default: {_DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without creating any files.",
    )
    args = parser.parse_args()
    split_toon_by_state(args.master, args.output_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
