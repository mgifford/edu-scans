---
work_package_id: WP06
title: Observability Performance and Release Hardening
lane: planned
dependencies:
- WP02
- WP03
- WP04
subtasks:
- T031
- T032
- T033
- T034
- T035
- T036
phase: Phase 5 - Cross-Cutting Quality
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

# Work Package Prompt: WP06 - Observability Performance and Release Hardening

## Objectives and Success Criteria

- Add production-readiness controls for monitoring, performance, compliance checks, and final documentation.
- Success criteria:
  - Operators can detect failed runs, stale spikes, and artifact errors quickly.
  - Benchmark checks validate monthly run performance target.
  - End-to-end readiness suite passes with documented operational runbook steps.

## Context and Constraints

- Depends on functional completion of WP02-WP05.
- Must preserve Europe-first monthly scan semantics.
- Should not alter contract payload shape while adding observability fields.

Implementation command for this WP:
- `spec-kitty implement WP06 --base WP05`

## Subtasks and Detailed Guidance

### Subtask T031 - Add observability metrics and logs
- Purpose: Make run-level and domain-level behavior measurable.
- Steps:
  1. Create `src/lib/observability.py`.
  2. Emit metrics for scan duration, host processed count, detection outcomes, stale transitions, and failures.
  3. Standardize structured logging fields for correlation.
- Files:
  - `src/lib/observability.py`
  - `tests/unit/test_observability_metrics.py`
- Parallel: No.

### Subtask T032 - Add scheduler health checks and alerts
- Purpose: Surface operational anomalies early.
- Steps:
  1. Build health-check module in `src/jobs/health_checks.py`.
  2. Add checks for repeated failed runs, artifact write failures, and unusual stale spikes.
  3. Expose alert-friendly output for operations integration.
- Files:
  - `src/jobs/health_checks.py`
  - `tests/integration/test_health_checks.py`
- Parallel: Yes after T031.

### Subtask T033 - Add performance benchmark harness
- Purpose: Verify planning performance objective under realistic load.
- Steps:
  1. Implement benchmark integration test in `tests/integration/test_performance_targets.py`.
  2. Measure monthly country run timing and throughput with representative fixture sizes.
  3. Fail test when benchmark exceeds agreed threshold.
- Files:
  - `tests/integration/test_performance_targets.py`
- Parallel: Yes after core runtime is stable.

### Subtask T034 - Add crawl compliance assertions
- Purpose: Enforce crawl etiquette and policy behavior continuously.
- Steps:
  1. Build assertions in `tests/integration/test_crawl_compliance.py`.
  2. Validate robots handling, retry behavior, and polite rate-limiting semantics.
  3. Validate unreachable lifecycle transitions remain compliant.
- Files:
  - `tests/integration/test_crawl_compliance.py`
- Parallel: No.

### Subtask T035 - Update docs and quickstart flows
- Purpose: Make operational and implementation usage clear for maintainers.
- Steps:
  1. Update root `README.md` with run, schedule, and artifact retrieval instructions.
  2. Update feature quickstart with final command paths and validation sequence.
  3. Include guidance for importing additional country sheets and provenance tracking.
- Files:
  - `README.md`
  - `/workspaces/eu-plus-government-scans/kitty-specs/001-eu-government-accessibility-statement-discovery/quickstart.md`
- Parallel: No.

### Subtask T036 - Add end-to-end readiness regression
- Purpose: Gate release readiness with full-system verification.
- Steps:
  1. Add `tests/integration/test_e2e_readiness.py`.
  2. Execute source ingestion through scan, artifact write, API retrieval, and readiness checks.
  3. Produce machine-readable readiness summary for review.
- Files:
  - `tests/integration/test_e2e_readiness.py`
- Parallel: No.

## Test Strategy

- Integration-heavy package covering observability and run quality gates.
- Ensure benchmark fixtures are deterministic and reproducible.
- Include final regression command sequence in quickstart docs.

## Risks and Mitigations

- Risk: performance benchmark too environment-sensitive.
  - Mitigation: define fixture sizes and tolerance bands explicitly.
- Risk: alert noise from transient issues.
  - Mitigation: threshold and window-based health checks.

## Review Guidance

- Verify observability outputs include scan and hostname context fields.
- Verify documentation references real file paths and implemented commands.
- Verify end-to-end readiness suite covers all core success criteria.

## Activity Log

- 2026-02-26T09:14:51Z - system - lane=planned - Prompt created.
