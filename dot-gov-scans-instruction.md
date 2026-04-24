# dot-gov-scans Instruction

This checklist captures items to port from `edu-scans` into `dot-gov-scans` where `edu-scans` is currently ahead.

## 1) Path And Naming Migration Hardening

- Update workflow text from "country/countries" language to seed-oriented wording where appropriate (keep legacy CLI flags for compatibility).
- Ensure all workflow seed directory paths use `data/toon-seeds` (flat layout), not `data/toon-seeds/states`.
- Align helper imports and naming from `jurisdiction_*` to `country_*` where the codebase has already standardized on that.

Files to align (dot-gov-scans):
- `.github/workflows/generate-scan-progress.yml`
- `.github/workflows/scan-social-media.yml`
- `.github/workflows/scan-technology.yml`
- `.github/workflows/scan-accessibility.yml`
- `.github/workflows/scan-lighthouse.yml`
- `.github/workflows/scan-third-party-js.yml`
- `.github/workflows/scan-overlays.yml`
- `.github/workflows/validate-urls.yml`
- `.github/workflows/validate-urls-batch.yml`
- `src/jobs/accessibility_scanner.py`
- `src/cli/scan_social_media.py`
- `src/cli/generate_scan_progress.py`

## 2) Deploy Workflow Resilience Improvements

- Improve GitHub Pages data-file validation output with actionable guidance:
  - emit `::error` annotations per missing file
  - print explicit workflow run order required to generate missing files
  - include fallback guidance for placeholder JSON files

File:
- `.github/workflows/deploy-pages.yml`

## 3) Workflow Security Fix

- Avoid directly interpolating untrusted PR branch refs in shell scripts.
- Move `${{ github.event.pull_request.head.ref }}` to an environment variable and consume that variable in shell logic.

File:
- `.github/workflows/delete-merged-branches.yml`

## 4) Dependency Compatibility Fix

- Update test dependency pair to a compatible set:
  - `pytest==9.0.3`
  - `pytest-asyncio==1.3.0`

File:
- `requirements.txt`

## 5) Ignore Rules Modernization

- Replace stale ignores tied to `data/toon-seeds/states/*` with flat `data/toon-seeds/*` patterns.
- Include `_accessibility.toon` generated-file ignore pattern.
- Decide which docs JSON placeholders are committed vs artifact-only and update `.gitignore` accordingly.

File:
- `.gitignore`

## 6) Accessibility Candidate Path Seeding (Optional But Useful)

- Add optional domain-level `candidate_paths` entries to seed records.
- Expand scanner input URL extraction to probe those candidate paths in addition to existing page URLs.

Files:
- seed `.toon` files
- `src/jobs/accessibility_scanner.py`

## 7) Data Hygiene Guardrails

- Ensure committed docs data JSON does not include legacy dataset content when migrating scope.
- Keep placeholder JSON stubs for first deploy experience (pending state with guidance).

Files:
- `docs/*-data.json`

## Suggested Execution Order

1. Security fix (`delete-merged-branches.yml`)
2. Dependency fix (`requirements.txt`)
3. Path/naming migration in workflows + CLI/jobs
4. Deploy workflow diagnostics improvements
5. `.gitignore` updates
6. Optional candidate-path enhancement
7. Data hygiene scrub + stubs

## Validation

- `python3 -m pytest tests/ -v`
- workflow lint (`actionlint`) against `.github/workflows/*.yml`
- one manual run each of scanner + report workflows
- verify Pages deployment succeeds and links/artifacts resolve correctly
