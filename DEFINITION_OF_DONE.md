# Definition of Done for the Scan Progress Report

This is a filled-in definition of done for the **scan progress report** in this
repository, based on the way the project currently works and the report content
already published under `/docs`.

In short: the report is done when it is current, reproducible, accessible,
clearly explained, and aligned with the actual scanner outputs in
`data/metadata.db` and the workflow artifacts.

## What "done" means in this repository

For this project, a scan progress report is done when all of the following are
true:

1. **The numbers are current.**  
   The report shows a generated timestamp, reflects the latest completed scan
   runs, and uses the current seed inventory as the denominator.

2. **The numbers are independently verifiable.**  
   Any published total, percentage, or average can be traced back to
   machine-readable source data, not just a hand-written Markdown summary.

3. **The report distinguishes coverage from reachability.**  
   This repository already treats those as different concepts. A page can be in
   the seed set, scanned, reachable, unreachable, skipped, or already confirmed
   by another scan. A done report keeps those concepts separate instead of
   collapsing them into one percentage.

4. **The report explains cross-scan differences.**  
   The repository already documents that social scanning, accessibility
   scanning, Lighthouse, technology scanning, third-party JS scanning, and URL
   validation all run at different cadences and with different denominators. A
   done report explains that clearly so readers do not misread the totals.

5. **The report is accessible.**  
   Because the project is explicitly committed to WCAG 2.2 AA, the report must
   also meet that bar: descriptive links, accessible tables, text alternatives
   for visual progress indicators, and keyboard-usable disclosure patterns.

6. **The report matches project conventions.**  
   It must reflect the current workflow model: artifacts are uploaded from
   GitHub Actions, `data/metadata.db` is not committed, and aggregate claims are
   backed by machine-readable outputs.

## What can already be considered part of "done"

The current documentation already makes several expectations clear, so they
should be treated as part of the definition of done rather than optional nice to
have items:

- The report should include a **generated timestamp**.  
  The current `/docs/scan-progress.md` already does this.

- The report should include an **overall coverage summary**.  
  The current report uses **3,863 available pages** as the overall denominator
  and breaks coverage out by scan type.

- The report should explain **Combined Reachability**.  
  The current report already states that a URL is counted once if any scan type
  confirmed it reachable.

- The report should include **per-scan-type breakdowns**.  
  The current report has sections for social media, technology, Lighthouse,
  accessibility statements, and third-party JavaScript.

- The report should explain **why scan totals differ**.  
  The current report already includes a dedicated explanation for why Social
  Media and URL Validation counts are different.

- The report should publish **scan timing information**.  
  The current accessibility and social sections already show scan periods, and
  other sections show last scan dates.

- The report should expose **machine-readable supporting data** where possible.  
  The repository instructions explicitly require JSON and CSV backing data for
  aggregate reports so readers can reproduce totals independently.

## Concrete acceptance criteria

A scan progress report should be treated as done only if it meets these
repository-specific acceptance criteria.

### 1. Data integrity

- The denominator is correct for the unit being reported:
    - page-based scans use total available pages
    - domain-based scans say that they are domain-based
- Coverage percentages do not exceed 100% unless the report explicitly explains
  why a different denominator is being used
- Reachable counts are not presented as if they were total coverage counts
- Aggregated rows and section summaries agree with each other

### 2. Reproducibility

- The published Markdown can be recomputed from scanner output stored in the
  database and/or exported JSON and CSV artifacts
- Any average score, such as Lighthouse metrics, is clearly identified as an
  average over successful audits
- Any percentage states its denominator in plain language

### 3. Reader clarity

- The report tells readers what each scan measures
- The report makes clear when counts are for **pages** versus **domains**
- Differences in scan frequency are explained
- Any surprising result has a note near the table instead of forcing readers to
  infer hidden logic

### 4. Accessibility and usability

- Tables have meaningful headers
- Progress bars include text equivalents such as `aria-label`
- Links have descriptive text
- Hover/focus previews also work with keyboard interaction
- The report does not rely on colour alone to communicate status

### 5. Operational completeness

- The report corresponds to a successful workflow run
- The relevant artifacts were uploaded
- No generated SQLite database or validated TOON files were committed to git
- The documentation still matches the current workflow behavior

## What is not done yet unless corrected

Based on the current published docs, there is at least one issue that should
block calling the report fully done:

- In `/docs/scan-progress.md`, the **Accessibility Statements** row shows
  **3,881 domains** against **3,863 available pages**, resulting in **100.0%**
  coverage in one place and **100.5%** in the trend table. That tells us the
  report is mixing domain-based and page-based denominators. Until that is
  normalized or explicitly explained, the report is informative but not fully
  "done" by a strict definition.

## Practical one-paragraph definition

For this repository, the scan progress report is done when it is generated from
the latest scan data, uses the correct denominator for each metric, explains the
difference between coverage and reachability, includes accessible tables and
progress indicators, and publishes enough machine-readable evidence for a reader
to independently reproduce the report's totals and percentages from workflow
artifacts or database-backed exports.
