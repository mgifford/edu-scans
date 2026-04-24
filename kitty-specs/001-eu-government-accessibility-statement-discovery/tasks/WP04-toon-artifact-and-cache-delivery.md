---
work_package_id: WP04
title: TOON Artifact and Cache Delivery
lane: planned
dependencies:
- WP02
subtasks:
- T019
- T020
- T021
- T022
- T023
- T024
phase: Phase 3 - Artifact Layer
assignee: ''
agent: ''
shell_pid: ''
review_status: ''
reviewed_by: ''
history:
- timestamp: '2026-02-26T09:14:51Z'
  lane: planned
  agent: system
  shell_pid: ''
  action: Prompt generated via /spec-kitty.tasks
---

# Work Package Prompt: WP04 - TOON Artifact and Cache Delivery

## Objectives and Success Criteria

- Generate country/month TOON artifacts with complete required fields.
- Provide deterministic latest and month-specific cache retrieval.
- Success criteria:
  - Artifact schema includes all required domain-level fields.
  - Artifact write/read flows are deterministic and validated.
  - Latest resolver returns most recent completed monthly artifact.

## Context and Constraints

- Depends on WP02 and WP03 outputs.
- Must satisfy FR-011, FR-012, and provenance/redirect/sample requirements.
- Keep artifact structure stable for downstream consumers.

Implementation command for this WP:
- `spec-kitty implement WP04 --base WP02`

## Subtasks and Detailed Guidance

### Subtask T019 - Implement TOON schema validator
- Purpose: Guarantee output shape and field completeness before persistence.
- Steps:
  1. Build `src/storage/toon_schema.py` for serialization and validation.
  2. Validate required per-domain fields and value enums.
  3. Validate sampled URL length and shortfall reason behavior.
- Files:
  - `src/storage/toon_schema.py`
  - `tests/unit/test_toon_schema.py`
- Parallel: No.

### Subtask T020 - Build TOON writer and loader cache
- Purpose: Persist and retrieve country/month artifacts.
- Steps:
  1. Implement writer/loader in `src/storage/toon_cache.py`.
  2. Path convention should be country then run month.
  3. Ensure atomic writes to avoid partial artifacts.
- Files:
  - `src/storage/toon_cache.py`
  - `tests/integration/test_toon_cache.py`
- Parallel: No.

### Subtask T021 - Link artifact metadata to scan records
- Purpose: Keep artifact provenance and integrity attached to scan lifecycle.
- Steps:
  1. Implement `src/storage/artifact_registry.py`.
  2. Store artifact path, checksum, generated timestamp against `CountryScan`.
  3. Expose lookup by scan ID and country/month.
- Files:
  - `src/storage/artifact_registry.py`
  - `tests/unit/test_artifact_registry.py`
- Parallel: Yes after T020 contracts.

### Subtask T022 - Implement latest snapshot resolver
- Purpose: Retrieve current artifact without caller month lookup logic.
- Steps:
  1. Build `src/storage/latest_resolver.py`.
  2. Resolve latest completed monthly snapshot per country.
  3. Handle missing-country artifacts with explicit not-found result.
- Files:
  - `src/storage/latest_resolver.py`
  - `tests/unit/test_latest_resolver.py`
- Parallel: No.

### Subtask T023 - Add artifact replay CLI command
- Purpose: Support regeneration/replay workflows for operations.
- Steps:
  1. Implement `src/cli/generate_country_artifact.py`.
  2. Accept country code and run month arguments.
  3. Trigger rebuild from stored run outputs when possible.
- Files:
  - `src/cli/generate_country_artifact.py`
  - `tests/integration/test_generate_country_artifact_cli.py`
- Parallel: Yes after T020.

### Subtask T024 - Add artifact integration test suite
- Purpose: Validate complete serialization and retrieval behavior.
- Steps:
  1. Create `tests/integration/test_toon_artifacts.py`.
  2. Verify required fields for each domain record.
  3. Verify monthly and latest retrieval consistency.
  4. Verify checksum and metadata linkage.
- Files:
  - `tests/integration/test_toon_artifacts.py`
- Parallel: No.

## Test Strategy

- Unit tests for schema, resolver, registry modules.
- Integration tests for write/read and replay flows.
- Validate artifacts against OpenAPI response shape for compatibility.

## Risks and Mitigations

- Risk: partial file writes in interrupted runs.
  - Mitigation: atomic temp-write then move strategy.
- Risk: schema mismatch after detection changes.
  - Mitigation: schema validation at write-time and CI tests.

## Review Guidance

- Verify artifact contains source reference URLs and stale flag per domain.
- Verify latest resolver behavior is deterministic across repeated runs.
- Verify CLI replay does not bypass schema validation.

## Activity Log

- 2026-02-26T09:14:51Z - system - lane=planned - Prompt created.
