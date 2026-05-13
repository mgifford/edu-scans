# Definition of Done — edu-scans Reports

This file defines the criteria that must be met before any scan report produced
by this project is considered complete and ready to publish.

---

## 1. Data Coverage & Freshness

- [ ] All seed files for the relevant scan type have been attempted; overall coverage is ≥ 95% of available URLs
- [ ] Scan data is no older than the documented refresh interval for that scan type (e.g. ≤ 30 days for Lighthouse; ≤ 4 hours for accessibility statements)
- [ ] Unreachable URLs are accounted for (distinct from "not yet scanned"); reachability % is reported separately from coverage %
- [ ] The two-failure URL-removal policy has been applied so dead links do not inflate the denominator

---

## 2. Accuracy & Independent Verifiability

- [ ] Every aggregate number in the Markdown report (totals, percentages, averages) is mathematically reproducible from the accompanying machine-readable data
- [ ] A backing JSON file (e.g. `*-data.json`) with per-URL rows is uploaded as a GitHub Actions artifact
- [ ] A backing CSV file (UTF-8 BOM, 0–100 scale where applicable) is uploaded as a GitHub Actions artifact alongside the JSON
- [ ] The report's timestamp matches the actual scan completion time, not a hardcoded or stale value

---

## 3. Report Content & Structure

- [ ] A summary section states total pages available, total scanned, and coverage %
- [ ] Per-seed-group breakdown table is present with scanned count, reachable count, and the key metric(s) for that scan type
- [ ] Footnotes or callout blocks explain any counter-intuitive numbers (e.g. why social-media and URL-validation counts differ)
- [ ] Scan period (date range) is shown in the table, not just "last scan" date
- [ ] Links to related reports and to the machine-readable data files are present

---

## 4. Accessibility (WCAG 2.2 AA)

- [ ] All tables have meaningful column headers (`<th>` / proper Markdown header rows)
- [ ] All progress-bar or visual indicators carry a text equivalent (e.g. `aria-label="75% complete"`)
- [ ] Tooltip/details widgets for per-country URL lists follow the patterns in [ACCESSIBILITY.md §11](ACCESSIBILITY.md) (ARIA roles, keyboard dismiss, persistent hover)
- [ ] No colour is used as the sole means of conveying information
- [ ] All links use descriptive text (not "click here" or a bare URL)
- [ ] Images or icons carry `alt` text or `aria-label`

---

## 5. Code & Pipeline Quality

- [ ] The report generator (`src/cli/generate_*_report.py`) passes `ruff check` with no errors
- [ ] All public functions in the generator have type annotations and docstrings
- [ ] `python3 -m pytest tests/ -v` passes with no regressions
- [ ] The workflow YAML (`generate-*.yml`) successfully completes in CI without timeouts
- [ ] No `data/metadata.db` or `*_validated.toon` files are committed to the repository

---

## 6. Documentation

- [ ] The corresponding `docs/*.md` methodology page accurately describes what is checked, how tiers/outcomes are classified, and where artifacts are stored
- [ ] Any change to the scan methodology or output schema is reflected in [`src/storage/schema.py`](src/storage/schema.py) with a migration comment
- [ ] The [README.md](README.md) AI Disclosure section is updated if AI tooling was used to produce or modify the report generator

---

## Definition of "Not Done"

A report is **not** done if any of the following are true:

- Any aggregate total cannot be independently reproduced from the per-URL backing data
- Coverage is below 95% without a documented reason (e.g. newly added seed files mid-cycle)
- Any WCAG 2.2 AA violation is knowingly left in the published HTML
- The backing JSON/CSV files are missing or inconsistent with the Markdown summary table
