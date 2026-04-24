# GitHub Copilot Instructions

> **Start here:** The canonical, up-to-date guide for AI coding agents working in this repository
> is [AGENTS.md](../AGENTS.md) at the repository root. Read it fully before making any changes.

## Key Reference Files

| File | Purpose |
| :--- | :--- |
| [`AGENTS.md`](../AGENTS.md) | Primary AI-agent instructions: project overview, repo layout, tech stack, development setup, conventions, dos and don'ts |
| [`ACCESSIBILITY.md`](../ACCESSIBILITY.md) | Accessibility commitment, contributor requirements, severity taxonomy, and known limitations |
| [`README.md`](../README.md) | General project introduction and contribution guidance |
| [`docs/`](../docs/) | User-facing documentation (batched validation, URL scanner, social media scanning, technology scanning, etc.) |

## Quick-Start Summary

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests
python3 -m pytest tests/ -v

# Validate URLs for a specific country
python3 -m src.cli.validate_urls --country ICELAND --rate-limit 2

# Run a batch validation cycle (2 countries per batch)
python3 -m src.cli.validate_urls_batch --batch-mode --batch-size 2

# Generate a validation report
python3 -m src.cli.generate_validation_report --output validation-report.md
```

## Critical Conventions (summary — see AGENTS.md for full details)

- **Country codes:** `UPPER_SNAKE_CASE` with suffix, e.g. `UNITED_KINGDOM_UK`; filenames use `lowercase-hyphenated`, e.g. `united-kingdom-uk.toon` — always use `src/lib/country_utils.py` helpers for conversions
- **URL validation:** tracks failures across sessions; URLs are **removed after 2 consecutive failures**; `httpx` event hooks must be `async`
- **Storage:** validation metadata in `data/metadata.db` (SQLite, **not committed**); schema in `src/storage/schema.py`
- **TOON files:** seed files (`*.toon`) are version-controlled; validated output files (`*_validated.toon`) are excluded via `.gitignore`
- **Accessibility:** all documentation and data outputs must follow **WCAG 2.2 AA** — see [`ACCESSIBILITY.md`](../ACCESSIBILITY.md)

## Do NOT

- Commit `data/metadata.db` or `*_validated.toon` files
- Bypass the two-failure URL-removal policy
- Hardcode country-code or filename formats (use `src/lib/country_utils.py`)
- Push changes unless explicitly asked to do so by a human
- Introduce breaking changes to the TOON file format without updating all parsers and tests
