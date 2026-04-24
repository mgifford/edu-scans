---
work_package_id: "WP03"
subtasks:
  - "T013"
  - "T014"
  - "T015"
  - "T016"
  - "T017"
  - "T018"
title: "Crawl Orchestration and Lifecycle"
phase: "Phase 2 - Scan Runtime"
lane: "planned"
assignee: ""
agent: ""
shell_pid: ""
review_status: ""
reviewed_by: ""
dependencies: ["WP01"]
history:
  - timestamp: "2026-02-26T09:14:51Z"
    lane: "planned"
    agent: "system"
    shell_pid: ""
    action: "Prompt generated via /spec-kitty.tasks"
---

# Work Package Prompt: WP03 - Crawl Orchestration and Lifecycle

## Objectives and Success Criteria

- Implement monthly scan execution runtime with crawl politeness, redirects, URL sampling, and stale lifecycle logic.
- Success criteria:
  - Per-country run lock prevents concurrent active scans.
  - Redirect chain is captured per canonical hostname.
  - First unreachable keeps stale record; second consecutive unreachable deactivates domain.

## Context and Constraints

- Depends on WP01 data contracts and persistence.
- Must satisfy FR-008, FR-010, FR-015, and FR-016.
- Follow monthly cadence default from planning alignment.

Implementation command for this WP:
- `spec-kitty implement WP03 --base WP01`

## Subtasks and Detailed Guidance

### Subtask T013 - Implement polite crawl client
- Purpose: Execute network fetches safely against public-sector domains.
- Steps:
  1. Build `src/services/crawl_client.py`.
  2. Apply per-host rate limits and retry/backoff strategy.
  3. Respect robots directives and retry headers where applicable.
  4. Return typed fetch outcomes (success, unreachable, timeout, blocked).
- Files:
  - `src/services/crawl_client.py`
  - `tests/unit/test_crawl_client.py`
- Parallel: No.

### Subtask T014 - Add redirect trace capture
- Purpose: Record full redirect chain for canonicalization and auditability.
- Steps:
  1. Build `src/services/redirect_tracker.py`.
  2. Capture ordered hops with `from_url`, `to_url`, status code.
  3. Persist final canonical hostname and alias candidates.
- Files:
  - `src/services/redirect_tracker.py`
  - `tests/unit/test_redirect_tracker.py`
- Parallel: Yes after T013 interfaces.

### Subtask T015 - Implement navigation sampler
- Purpose: Collect up to 10 navigational URLs for downstream audits.
- Steps:
  1. Build `src/services/navigation_sampler.py`.
  2. Extract internal navigational links and deduplicate.
  3. Enforce max 10 sampled URLs.
  4. Populate shortfall reason when fewer than 10 valid URLs exist.
- Files:
  - `src/services/navigation_sampler.py`
  - `tests/unit/test_navigation_sampler.py`
- Parallel: Yes after T013 interfaces.

### Subtask T016 - Implement stale lifecycle service
- Purpose: Enforce clarified unreachable-domain behavior.
- Steps:
  1. Build `src/services/stale_lifecycle.py`.
  2. On first unreachable with prior record: set `stale=true`, increment streak, keep active.
  3. On second consecutive unreachable: set `active=false`, remove from active scan set.
  4. Reset stale state/streak on successful reachability.
- Files:
  - `src/services/stale_lifecycle.py`
  - `tests/unit/test_stale_lifecycle.py`
- Parallel: No.

### Subtask T017 - Implement monthly scheduler orchestration
- Purpose: Execute country scan jobs at monthly cadence with guarded concurrency.
- Steps:
  1. Implement `src/jobs/monthly_scan_job.py`.
  2. Enforce one-active-run-per-country lock semantics.
  3. Create run records (`queued`, `running`, `completed`, `failed`).
  4. Integrate crawl client, redirect tracker, sampler, and stale lifecycle services.
- Files:
  - `src/jobs/monthly_scan_job.py`
  - `tests/integration/test_monthly_scan_job.py`
- Parallel: No.

### Subtask T018 - Add lifecycle and sampling integration tests
- Purpose: Verify end-to-end runtime behavior for critical edge cases.
- Steps:
  1. Add `tests/integration/test_scan_lifecycle.py`.
  2. Cover stale-first and stale-second-unreachable transitions.
  3. Cover redirect chain persistence and max-10 URL sampling.
  4. Cover run-lock conflict behavior.
- Files:
  - `tests/integration/test_scan_lifecycle.py`
- Parallel: No.

## Test Strategy

- Integration suite validates lifecycle transitions against persisted state.
- Include fixtures for redirected hosts and partial-navigation sites.
- Add deterministic retry behavior for test runtime stability.

## Risks and Mitigations

- Risk: scheduler overlap causing duplicate scan writes.
  - Mitigation: explicit per-country lock with conflict status handling.
- Risk: crawl aggressiveness impacting public-sector hosts.
  - Mitigation: conservative defaults and policy assertion tests.

## Review Guidance

- Confirm stale behavior exactly matches clarified rules.
- Confirm monthly cadence is default, configurable via settings.
- Confirm redirect trace model persists ordered hops.

## Activity Log

- 2026-02-26T09:14:51Z - system - lane=planned - Prompt created.
