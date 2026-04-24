---
work_package_id: WP01
title: Foundation and Data Contracts
lane: "for_review"
dependencies: []
base_branch: main
base_commit: 798ba6324ea80c93200da3d4a0b2fc8db3c6a2d3
created_at: '2026-02-26T09:24:27.653679+00:00'
subtasks:
- T001
- T002
- T003
- T004
- T005
- T006
phase: Phase 1 - Foundation
assignee: ''
agent: "copilot"
shell_pid: "38647"
review_status: ''
reviewed_by: ''
history:
- timestamp: '2026-02-26T09:14:51Z'
  lane: planned
  agent: system
  shell_pid: ''
  action: Prompt generated via /spec-kitty.tasks
---

# Work Package Prompt: WP01 - Foundation and Data Contracts

## Objectives and Success Criteria

- Deliver backend skeleton, runtime settings, ingestion, canonicalization, persistence schema, and logging foundations.
- Ensure downstream packages can reuse these modules without redefining contracts.
- Success criteria:
  - Project modules and test directories exist and import cleanly.
  - Source ingestion captures provenance URL and normalized hostname.
  - Persistence schema supports `CountryScan` and `DomainRecord` entities.

## Context and Constraints

- Spec path: `/workspaces/eu-plus-government-scans/kitty-specs/001-eu-government-accessibility-statement-discovery/spec.md`
- Plan path: `/workspaces/eu-plus-government-scans/kitty-specs/001-eu-government-accessibility-statement-discovery/plan.md`
- Data model path: `/workspaces/eu-plus-government-scans/kitty-specs/001-eu-government-accessibility-statement-discovery/data-model.md`
- Use Python 3.12 with FastAPI stack defined in plan.
- Canonical uniqueness key must be full hostname per country.

Implementation command for this WP:
- `spec-kitty implement WP01`

## Subtasks and Detailed Guidance

### Subtask T001 - Create backend module skeleton
- Purpose: Establish stable package boundaries used by all other WPs.
- Steps:
  1. Create missing directories under `src/` and `tests/` per plan structure.
  2. Add package initialization files where needed.
  3. Add minimal placeholder modules only where necessary to avoid import failures.
- Files:
  - `src/api/`
  - `src/jobs/`
  - `src/models/`
  - `src/services/`
  - `src/glossary/`
  - `src/storage/`
  - `tests/unit/`, `tests/integration/`, `tests/contract/`
- Parallel: No.

### Subtask T002 - Implement runtime configuration loader
- Purpose: Centralize runtime defaults and environment overrides.
- Steps:
  1. Create `src/lib/settings.py` with typed settings object.
  2. Include scheduler cadence default `monthly` and crawl-limit settings.
  3. Include storage paths for TOON artifacts and metadata DB.
  4. Add validation for required settings and clear startup error messages.
- Files:
  - `src/lib/settings.py`
  - `tests/unit/test_settings.py`
- Parallel: No.

### Subtask T003 - Build source-list ingestion adapters
- Purpose: Normalize upstream source lists into internal records with provenance.
- Steps:
  1. Create adapter interface for source ingestion in `src/services/source_ingest.py`.
  2. Implement CSV parser pathway and URL-list pathway.
  3. Capture `country_code`, `input_hostname`, `source_type`, `source_reference_url`.
  4. Reject rows lacking provenance URL or hostname with actionable error counters.
- Files:
  - `src/services/source_ingest.py`
  - `tests/unit/test_source_ingest.py`
- Parallel: No.

### Subtask T004 - Implement hostname normalization utilities
- Purpose: Ensure canonical identity is consistent across ingestion and scan outputs.
- Steps:
  1. Create `src/services/domain_normalizer.py`.
  2. Normalize host casing/punycode and strip URL path/query fragments.
  3. Produce canonical full hostname and alias list.
  4. Add helper to compare input-host aliases for de-duplication.
- Files:
  - `src/services/domain_normalizer.py`
  - `tests/unit/test_domain_normalizer.py`
- Parallel: No.

### Subtask T005 - Create persistence schema and migrations bootstrap
- Purpose: Persist scan lifecycle and domain state.
- Steps:
  1. Define schema models for `CountryScan` and `DomainRecord` in `src/storage/schema.py`.
  2. Include fields in data-model definitions.
  3. Add migration bootstrap entrypoint and initial migration.
  4. Ensure compatibility with SQLite local and PostgreSQL-compatible deployment.
- Files:
  - `src/storage/schema.py`
  - `src/storage/migrations/`
  - `tests/integration/test_schema_bootstrap.py`
- Parallel: No.

### Subtask T006 - Configure baseline structured logging and error model
- Purpose: Ensure failures are diagnosable from day one.
- Steps:
  1. Implement structured logger factory in `src/lib/logging.py`.
  2. Define error classes for ingestion/config/storage failure categories.
  3. Include correlation fields (`scan_id`, `country_code`, `hostname` where applicable).
- Files:
  - `src/lib/logging.py`
  - `src/lib/errors.py`
  - `tests/unit/test_logging_contract.py`
- Parallel: Yes after T001.

## Test Strategy

- Unit tests for settings, normalization, and ingestion adapters.
- Integration test proving schema bootstrap works on local test DB.
- Smoke test: service startup loads settings and schema without exceptions.

## Risks and Mitigations

- Risk: Conflicting canonicalization rules across modules.
  - Mitigation: all modules import canonicalization from `domain_normalizer.py`.
- Risk: Missing provenance links in imported records.
  - Mitigation: hard validation rule and explicit reject counters.

## Review Guidance

- Confirm all paths are under repository root and match plan structure.
- Verify schema includes fields used by later packages (stale flags, unreachable streak, source references).
- Verify no duplicate normalization logic exists.

## Activity Log

- 2026-02-26T09:14:51Z - system - lane=planned - Prompt created.
- 2026-02-26T09:24:28Z – copilot – shell_pid=38647 – lane=doing – Assigned agent via workflow command
- 2026-02-26T09:29:45Z – copilot – shell_pid=38647 – lane=for_review – Ready for review: foundation skeleton, config, ingestion, normalization, schema, and logging completed with tests
