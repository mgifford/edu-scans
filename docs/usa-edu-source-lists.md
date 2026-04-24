---
title: USA EDU Source Lists
layout: page
---

# USA EDU Source Lists

This repository is building a deduplicated master list of USA higher-education institutions on
`.edu` domains from several public upstream datasets.

## Sources

### `nickdenardis/edu-inventory`

- Format: CSV
- Main fields used: `URL`, `Final URL`, `Title`, `HTTP Code`
- Strengths: broad `.edu` inventory, useful for root-domain discovery and homepage evidence
- Limitations: not institution-curated, includes non-university `.edu` sites, and names are derived from page titles
- Current use here: low-confidence supporting evidence only when the title looks like higher education

### `Hipo/university-domains-list`

- Format: JSON
- Main fields used: `name`, `domains[]`, `web_pages[]`, `country`, `alpha_two_code`, `state-province`
- Strengths: maintained institution-first dataset with explicit country labels
- Limitations: can include stale or non-root domains, and the US subset still needs validation
- Current use here: primary named-source input for USA institutions

### `abadojack/swot`

- Format: repository tree of one-text-file-per-domain under `domains/edu/`
- Main fields used: domain inferred from file path, institution name from file contents
- Strengths: wide coverage of academic domains and institution names
- Limitations: no explicit country field for `.edu` entries and no homepage URLs
- Current use here: named supporting source and review evidence for `.edu` domains

### `matlin/node-university-domains`

- Format: JavaScript array export
- Main fields used: `name`, `domain`, `web_page`, `country`
- Strengths: straightforward USA institution records and homepages
- Limitations: appears older and contains known stale or incorrect entries
- Current use here: secondary named-source input

### `mohsennazari/academic-domains-dataset`

- Format: JSON
- Main fields used: `domain`, `country`, `country_alpha_2`
- Strengths: broad domain-level academic coverage with country codes
- Limitations: no institution names in the main-domain file
- Current use here: domain-only evidence and orphan-domain review list

## Merge Rules

The current builder uses conservative rules:

- Keep only USA rows when the source provides country metadata.
- Keep only root `.edu` domains.
- Prefer named institution sources for the master institution list.
- Use domain overlap first, then exact normalized institution name, to merge records.
- Keep domain-only rows that cannot be matched in a separate orphan-domain review file.

## Generated Outputs

The builder currently writes:

- `data/imports/usa-edu-master.json`
- `data/imports/usa-edu-master.csv`
- `data/imports/usa-edu-parent-groups.json`
- `data/imports/usa-edu-parent-groups.csv`
- `data/imports/usa-edu-orphan-domains.json`
- `data/imports/usa-edu-orphan-domains.csv`
- `data/toon-seeds/usa-edu-master.toon`
- `data/toon-seeds/index.json`

Parent-group outputs are inferred metadata that help organize campuses and
affiliated domains under likely umbrella systems (for example,
`University of California`).

## Review Notes

This is a migration-phase dataset. The outputs are intended to be reproducible and reviewable,
not final authoritative higher-education registries. Expect follow-up passes for:

- institution-name corrections
- mergers and alias handling
- exclusion of stale or non-institution `.edu` domains
- splitting the master TOON into smaller seed groups once the grouping model is finalized