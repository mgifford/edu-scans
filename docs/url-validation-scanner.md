# URL Validation Scanner

## Overview

The URL validation scanner validates government website URLs from TOON files, tracking failures, redirects, and error codes. It supports quarterly validation runs and removes URLs that fail validation twice.

## Features

- **Fast URL validation** - Asynchronously validates URLs with configurable rate limiting
- **Redirect tracking** - Detects and records URL redirects, updating the canonical URL for future scans
- **Error tracking** - Records HTTP status codes and error messages for failed validations
- **Failure tracking** - Tracks failure counts across scans:
  - First failure: URL is noted but kept in the dataset
  - Second failure: URL is removed from the TOON file
- **No retry in same session** - URLs are validated once per scan session
- **Batch processing** - Can scan individual countries or all countries at once

## Installation

Install dependencies:

```bash
pip install -r requirements.txt
```

## Usage

### CLI Interface

Validate URLs for a specific country:

```bash
python3 -m src.cli.validate_urls --country iceland --rate-limit 2
```

Validate all countries:

```bash
python3 -m src.cli.validate_urls --all --rate-limit 2
```

Options:
- `--country <name>` - Specific country to scan (e.g., iceland, france)
- `--all` - Scan all countries in the TOON directory
- `--toon-dir <path>` - Directory containing TOON files (default: data/toon-seeds/countries)
- `--rate-limit <float>` - Maximum requests per second (default: 2.0)

## Output

The scanner creates updated TOON files with the suffix `_validated.toon` that:
- Contain validation metadata for each page URL
- Have URLs updated to redirect targets when applicable
- Exclude URLs that failed validation twice

## Quarterly Validation Workflow

1. Run the scanner on all countries:
   ```bash
   python3 -m src.cli.validate_urls --all --rate-limit 2
   ```

2. Review the statistics printed for each country

3. Use the validated TOON files for continued evaluation

4. Archive validated TOON files with a timestamp for historical tracking

See the full documentation for more details on database schema, failure tracking logic, and programmatic usage.
