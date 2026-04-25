#!/usr/bin/env python3
"""Enrich TOON seed files with state information based on domain registrant data.

This script adds a 'state' field to each domain entry in the TOON file by:
1. Using WHOIS data (if available locally)
2. Inferring from institution name patterns (e.g., "University of California")
3. Using public edu domain registries

For now, we use a curated mapping of common edu domain patterns to states.
"""

import json
import re
from pathlib import Path

# State abbreviation to full name mapping
STATE_ABBR_TO_NAME = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
    'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware',
    'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii', 'ID': 'Idaho',
    'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas',
    'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
    'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
    'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
    'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
    'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma',
    'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
    'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
    'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia',
    'WI': 'Wisconsin', 'WY': 'Wyoming',
}

def infer_state_from_institution_name(name: str) -> str | None:
    """Infer state from institution name patterns.
    
    Examples:
    - "University of California" → "California"
    - "Florida State University" → "Florida"
    - "MIT" → None (requires external mapping)
    """
    if not name:
        return None
    
    name_upper = name.upper()
    
    # Pattern: "University of STATE"
    match = re.search(r'University of (\w+)', name_upper)
    if match:
        state_name = match.group(1).title()
        # Check if it's a valid state
        for abbr, full_name in STATE_ABBR_TO_NAME.items():
            if full_name.upper() == state_name.upper():
                return full_name
    
    # Pattern: "STATE University"
    match = re.search(r'(\w+)\s+(?:State\s+)?University', name_upper)
    if match:
        state_name = match.group(1).title()
        for abbr, full_name in STATE_ABBR_TO_NAME.items():
            if full_name.upper() == state_name.upper():
                return full_name
    
    # Pattern: "STATE College" or "STATE Community College"
    match = re.search(r'(\w+)\s+(?:Community\s+)?College', name_upper)
    if match:
        state_name = match.group(1).title()
        for abbr, full_name in STATE_ABBR_TO_NAME.items():
            if full_name.upper() == state_name.upper():
                return full_name
    
    return None


def enrich_toon_file(toon_path: Path) -> dict:
    """Add 'state' field to each domain entry in the TOON file.
    
    Returns the enriched data dict.
    """
    data = json.load(open(toon_path, encoding='utf-8'))
    
    enriched_count = 0
    unknown_count = 0
    
    for domain_entry in data.get('domains', []):
        # Skip if state already present
        if 'state' in domain_entry:
            continue
        
        # Try to infer state from institution name
        state = infer_state_from_institution_name(domain_entry.get('institution_name'))
        if state:
            domain_entry['state'] = state
            enriched_count += 1
        else:
            domain_entry['state'] = 'Unknown'
            unknown_count += 1
    
    print(f"Enriched {enriched_count} entries with state info")
    print(f"Could not infer state for {unknown_count} entries (set to 'Unknown')")
    
    return data


def main():
    toon_seeds_dir = Path(__file__).parent.parent / 'data' / 'toon-seeds'
    toon_file = toon_seeds_dir / 'usa-edu-master.toon'
    
    if not toon_file.exists():
        print(f"Error: {toon_file} not found")
        return 1
    
    print(f"Enriching {toon_file}...")
    enriched_data = enrich_toon_file(toon_file)
    
    # Write back the enriched file
    toon_file.write_text(
        json.dumps(enriched_data, ensure_ascii=True, indent=2) + '\n',
        encoding='utf-8'
    )
    print(f"Written enriched TOON file to {toon_file}")
    
    return 0


if __name__ == '__main__':
    exit(main())
