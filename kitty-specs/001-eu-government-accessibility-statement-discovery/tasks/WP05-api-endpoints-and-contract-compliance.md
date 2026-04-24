---
work_package_id: WP05
title: API Endpoints and Contract Compliance
lane: planned
dependencies:
- WP03
subtasks:
- T025
- T026
- T027
- T028
- T029
- T030
phase: Phase 4 - API Layer
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

# Work Package Prompt: WP05 - API Endpoints and Contract Compliance

## Objectives and Success Criteria

- Deliver API endpoints defined in contract for scan triggering, status checks, artifact retrieval, and host details.
- Ensure payloads and status codes conform to `contracts/openapi.yaml`.
- Success criteria:
  - Trigger endpoint returns `202` or `409` correctly.
  - Retrieval endpoints return `200` with schema-conformant payloads or `404` when absent.
  - Contract tests pass against implemented API.

## Context and Constraints

- Depends on WP03 runtime and WP04 artifact/cache layers.
- API surface must remain minimal and aligned with existing contract.
- Avoid introducing endpoints not documented by contract.

Implementation command for this WP:
- `spec-kitty implement WP05 --base WP03`

## Subtasks and Detailed Guidance

### Subtask T025 - Implement scan trigger endpoint
- Purpose: Start country-month scan runs with idempotent behavior.
- Steps:
  1. Implement `POST /v1/countries/{countryCode}/scans` in `src/api/scans.py`.
  2. Accept optional `runMonth` and `includeCanada` payload fields.
  3. Return `202` for accepted run and `409` if active run exists.
- Files:
  - `src/api/scans.py`
  - `tests/contract/test_trigger_scan_contract.py`
- Parallel: No.

### Subtask T026 - Implement scan status endpoint
- Purpose: Expose lifecycle and summary metadata for a run.
- Steps:
  1. Implement `GET /v1/scans/{scanId}` in `src/api/scans.py`.
  2. Return `CountryScan` payload fields required by contract.
  3. Return `404` for unknown scan IDs.
- Files:
  - `src/api/scans.py`
  - `tests/contract/test_scan_status_contract.py`
- Parallel: Yes after app wiring contracts.

### Subtask T027 - Implement artifact retrieval endpoints
- Purpose: Provide latest and month-specific country artifact retrieval.
- Steps:
  1. Implement `GET /v1/countries/{countryCode}/toon/latest` in `src/api/artifacts.py`.
  2. Implement `GET /v1/countries/{countryCode}/toon/{runMonth}` in same module.
  3. Return `404` when no artifact exists.
- Files:
  - `src/api/artifacts.py`
  - `tests/contract/test_artifact_endpoints_contract.py`
- Parallel: Yes.

### Subtask T028 - Implement host details endpoint
- Purpose: Provide host-level details for operational debugging and follow-up.
- Steps:
  1. Implement `GET /v1/countries/{countryCode}/hosts/{hostname}` in `src/api/hosts.py`.
  2. Include detection status, confidence, sampled URLs, and stale flag.
  3. Return `404` for missing host record.
- Files:
  - `src/api/hosts.py`
  - `tests/contract/test_host_endpoint_contract.py`
- Parallel: Yes.

### Subtask T029 - Wire app dependencies and error mappers
- Purpose: Keep endpoint behavior consistent across modules.
- Steps:
  1. Add FastAPI app composition in `src/api/app.py`.
  2. Register routers for scans, artifacts, and hosts.
  3. Add error mappers for validation conflicts and not-found conditions.
- Files:
  - `src/api/app.py`
  - `tests/integration/test_api_wiring.py`
- Parallel: No.

### Subtask T030 - Add contract test suite
- Purpose: Enforce OpenAPI schema and status-code conformance.
- Steps:
  1. Create `tests/contract/test_scan_api_contract.py`.
  2. Validate contract examples and required response fields.
  3. Include negative-path checks (`404`, `409`).
- Files:
  - `tests/contract/test_scan_api_contract.py`
- Parallel: No.

## Test Strategy

- Contract tests for each route plus consolidated contract suite.
- Integration test verifies dependency injection and module wiring.
- Add schema assertion helpers to avoid duplicative checks.

## Risks and Mitigations

- Risk: mismatch between endpoint payload and contract schema.
  - Mitigation: contract-first assertions in CI.
- Risk: endpoint behavior divergence across modules.
  - Mitigation: centralized error mapping and shared response models.

## Review Guidance

- Confirm route paths and statuses exactly match `contracts/openapi.yaml`.
- Verify endpoints do not bypass cache/services abstractions.
- Verify errors are deterministic and typed.

## Activity Log

- 2026-02-26T09:14:51Z - system - lane=planned - Prompt created.
