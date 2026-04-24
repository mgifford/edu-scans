# Work Packages: EU Government Accessibility Statement Discovery

**Inputs**: Design documents from `/kitty-specs/001-eu-government-accessibility-statement-discovery/`  
**Prerequisites**: plan.md (required), spec.md (user stories), research.md, data-model.md, contracts/, quickstart.md

**Tests**: Include unit, integration, and contract coverage as defined in plan.md technical context and quickstart validation scenarios.

**Organization**: Fine-grained subtasks (`Txxx`) roll up into work packages (`WPxx`). Each work package is independently deliverable and testable.

**Prompt Files**: Each work package references a matching prompt file in `/tasks/`.

## Subtask Format: `[Txxx] [P?] Description`
- **[P]** indicates the subtask can proceed in parallel (different files/components).
- Subtasks include precise file paths or modules.

## Path Conventions
- **Single project**: `src/`, `tests/`

---

## Work Package WP01: Foundation and Data Contracts (Priority: P0)

**Goal**: Establish base project structure, configuration, persistence contracts, and source ingestion primitives.
**Independent Test**: Service boots with validated configuration; metadata schema stores `CountryScan` and `DomainRecord`; source list ingestion persists canonical hostnames with provenance.
**Prompt**: `/tasks/WP01-foundation-and-data-contracts.md`

### Included Subtasks
- [x] T001 Create backend module skeleton in `src/api`, `src/jobs`, `src/models`, `src/services`, `src/glossary`, `src/storage`, and mirrored `tests/` directories
- [x] T002 Implement runtime configuration loader for scheduler cadence, crawl limits, and storage paths in `src/lib/settings.py`
- [x] T003 Implement source-list ingestion interfaces and CSV/URL adapters with provenance URL capture in `src/services/source_ingest.py`
- [x] T004 Implement hostname normalization utilities (full-hostname canonical key and alias mapping) in `src/services/domain_normalizer.py`
- [x] T005 Create persistence schema for `CountryScan` and `DomainRecord` plus migration bootstrap in `src/storage/schema.py`
- [x] T006 Configure baseline structured logging and error model in `src/lib/logging.py`

### Implementation Notes
- Build this package first to unblock all downstream work.
- Keep canonical key semantics aligned with spec clarification: uniqueness by full hostname.
- Capture source provenance URL for every imported row.

### Parallel Opportunities
- T003 and T006 can run in parallel after T001; T004 can begin after T003 interface contracts are fixed.

### Dependencies
- None.

### Risks & Mitigations
- Risk: canonicalization drift across modules. Mitigation: centralize canonicalization in `domain_normalizer.py` and prohibit duplicate implementations.

### Estimated Prompt Size
- ~360 lines

---

## Work Package WP02: Multilingual Detection Engine (Priority: P1)

**Goal**: Implement glossary-driven multilingual statement detection with confidence and policy mention hooks.
**Independent Test**: Given multilingual pages, detection returns `found|not_found|uncertain`, confidence `high|medium|low`, statement URL where present, and evidence terms.
**Prompt**: `/tasks/WP02-multilingual-detection-engine.md`

### Included Subtasks
- [ ] T007 Implement translation glossary model and loader for all official EU languages in `src/glossary/glossary_store.py`
- [ ] T008 [P] Implement multilingual term matcher and language tagging helper in `src/services/term_matcher.py`
- [ ] T009 [P] Implement statement evidence extractor for HTML and non-HTML references in `src/services/statement_extractor.py`
- [ ] T010 Implement confidence rubric mapping to `high|medium|low` in `src/services/confidence.py`
- [ ] T011 Implement optional policy mention detection hooks (GDPR, EN 301 549) in `src/services/policy_mentions.py`
- [ ] T012 Add unit tests for glossary coverage, matcher behavior, and confidence rules in `tests/unit/test_detection_engine.py`

### Implementation Notes
- Glossary completeness is required for all official EU languages before this package is considered done.
- Keep policy mention extraction additive and non-blocking.

### Parallel Opportunities
- T008 and T009 are parallel-safe once glossary contracts (T007) are established.

### Dependencies
- Depends on WP01.

### Risks & Mitigations
- Risk: false positives from generic terms. Mitigation: confidence rubric must require multiple evidence signals for `high` confidence.

### Estimated Prompt Size
- ~390 lines

---

## Work Package WP03: Crawl Orchestration and Lifecycle (Priority: P1)

**Goal**: Implement scan execution loop, redirect tracing, URL sampling, stale-domain lifecycle, and monthly scheduler behavior.
**Independent Test**: Monthly scan run processes domains with redirect traces, samples up to 10 URLs, marks first unreachable as stale, and deactivates second consecutive unreachable domain.
**Prompt**: `/tasks/WP03-crawl-orchestration-and-lifecycle.md`

### Included Subtasks
- [ ] T013 Implement polite HTTP crawl client with retries/rate limits in `src/services/crawl_client.py`
- [ ] T014 [P] Implement redirect trace capture and canonical destination recording in `src/services/redirect_tracker.py`
- [ ] T015 [P] Implement navigation sampling (max 10 URLs plus shortfall reason) in `src/services/navigation_sampler.py`
- [ ] T016 Implement stale/unreachable lifecycle transitions in `src/services/stale_lifecycle.py`
- [ ] T017 Implement monthly scheduler job orchestration with one-active-run-per-country guard in `src/jobs/monthly_scan_job.py`
- [ ] T018 Add integration tests for lifecycle and sampling flows in `tests/integration/test_scan_lifecycle.py`

### Implementation Notes
- Respect monthly cadence default from planning alignment.
- Ensure first unreachable keeps stale record and second unreachable removes from active set.

### Parallel Opportunities
- T014 and T015 can proceed in parallel after T013 interfaces are in place.

### Dependencies
- Depends on WP01.

### Risks & Mitigations
- Risk: scheduler overlap per country. Mitigation: lock by country and reject concurrent run with deterministic status.

### Estimated Prompt Size
- ~410 lines

---

## Work Package WP04: TOON Artifact and Cache Delivery (Priority: P1)

**Goal**: Produce country/month TOON artifacts with required fields and robust cache retrieval semantics.
**Independent Test**: Completed scan writes country TOON artifact containing required domain fields; latest and monthly retrieval resolve deterministically.
**Prompt**: `/tasks/WP04-toon-artifact-and-cache-delivery.md`

### Included Subtasks
- [ ] T019 Implement TOON artifact schema serializer/validator in `src/storage/toon_schema.py`
- [ ] T020 Implement country/month artifact writer and loader in `src/storage/toon_cache.py`
- [ ] T021 [P] Implement artifact metadata linkage to `CountryScan` (checksum/path/timestamps) in `src/storage/artifact_registry.py`
- [ ] T022 Implement latest-snapshot resolver for each country in `src/storage/latest_resolver.py`
- [ ] T023 [P] Implement CLI utility to generate/replay country artifacts in `src/cli/generate_country_artifact.py`
- [ ] T024 Add integration tests for artifact generation and retrieval in `tests/integration/test_toon_artifacts.py`

### Implementation Notes
- Required artifact fields: canonical hostname, statement URL, confidence, language, redirect chain, sampled URLs, source reference URL, stale flag.
- Keep file layout stable by country and run month to support cache keys.

### Parallel Opportunities
- T021 and T023 can run in parallel after T020 storage interfaces exist.

### Dependencies
- Depends on WP02 and WP03.

### Risks & Mitigations
- Risk: schema drift between runtime and contract. Mitigation: validate serialized artifact against shared schema before write.

### Estimated Prompt Size
- ~360 lines

---

## Work Package WP05: API Endpoints and Contract Compliance (Priority: P2)

**Goal**: Implement API endpoints defined in OpenAPI for scan trigger/status and artifact retrieval.
**Independent Test**: Endpoints match contract behavior (`202`, `409`, `404`, payload schema) and return consistent run/artifact data.
**Prompt**: `/tasks/WP05-api-endpoints-and-contract-compliance.md`

### Included Subtasks
- [ ] T025 Implement `POST /v1/countries/{countryCode}/scans` with idempotent monthly trigger semantics in `src/api/scans.py`
- [ ] T026 [P] Implement `GET /v1/scans/{scanId}` status endpoint in `src/api/scans.py`
- [ ] T027 [P] Implement country artifact retrieval endpoints (`latest`, `runMonth`) in `src/api/artifacts.py`
- [ ] T028 [P] Implement host detail endpoint in `src/api/hosts.py`
- [ ] T029 Implement API wiring, dependency injection, and error mappers in `src/api/app.py`
- [ ] T030 Add contract tests for OpenAPI schema and status codes in `tests/contract/test_scan_api_contract.py`

### Implementation Notes
- Keep endpoint behavior aligned with `contracts/openapi.yaml`.
- Ensure API reads from cache/metadata components, not from ad hoc file parsing.

### Parallel Opportunities
- T026, T027, and T028 are parallel once shared app wiring contracts are set.

### Dependencies
- Depends on WP03 and WP04.

### Risks & Mitigations
- Risk: contract mismatch after endpoint implementation. Mitigation: enforce contract tests in CI and block merge on failures.

### Estimated Prompt Size
- ~400 lines

---

## Work Package WP06: Observability, Performance, and Release Hardening (Priority: P2)

**Goal**: Add operational visibility, benchmark checks, documentation updates, and end-to-end readiness gates.
**Independent Test**: Operators can monitor run health, benchmark target is validated, and quickstart scenarios execute successfully end-to-end.
**Prompt**: `/tasks/WP06-observability-performance-and-release-hardening.md`

### Included Subtasks
- [ ] T031 Implement scan and API observability metrics/log fields in `src/lib/observability.py`
- [ ] T032 [P] Add operational alerts/checks for failed runs, stale spikes, and artifact generation failures in `src/jobs/health_checks.py`
- [ ] T033 [P] Implement benchmark harness for monthly run target validation in `tests/integration/test_performance_targets.py`
- [ ] T034 Implement crawl compliance guardrails (robots/retry policy assertions) in `tests/integration/test_crawl_compliance.py`
- [ ] T035 Update operator and developer docs in `README.md` and `kitty-specs/001-eu-government-accessibility-statement-discovery/quickstart.md`
- [ ] T036 Execute end-to-end regression checklist and release readiness report in `tests/integration/test_e2e_readiness.py`

### Implementation Notes
- Focus this package on cross-cutting quality outcomes and release confidence.
- Preserve monthly cadence defaults and Europe-first scope in docs and checks.

### Parallel Opportunities
- T032 and T033 can run in parallel after T031 interfaces are stable.

### Dependencies
- Depends on WP02, WP03, WP04, and WP05.

### Risks & Mitigations
- Risk: unobserved runtime failures in production scheduler. Mitigation: expose run-level and domain-level failure metrics with threshold alerts.

### Estimated Prompt Size
- ~340 lines

---

## Dependency and Execution Summary

- **Sequence**: WP01 -> (WP02 + WP03 in parallel) -> WP04 -> WP05 -> WP06.
- **Parallelization**: Core parallel lane opens after WP01 for detection and orchestration tracks.
- **MVP Scope**: WP01 + WP02 + WP03 + WP04 (first end-to-end country scan and TOON artifact).

---

## Subtask Index (Reference)

| Subtask ID | Summary | Work Package | Priority | Parallel? |
|------------|---------|--------------|----------|-----------|
| T001 | Create backend module skeleton | WP01 | P0 | No |
| T002 | Implement runtime configuration loader | WP01 | P0 | No |
| T003 | Build source-list ingestion adapters | WP01 | P0 | No |
| T004 | Implement hostname normalization utilities | WP01 | P0 | No |
| T005 | Create persistence schema and migrations | WP01 | P0 | No |
| T006 | Configure logging and error model | WP01 | P0 | No |
| T007 | Implement EU glossary store | WP02 | P1 | No |
| T008 | Build multilingual term matcher | WP02 | P1 | Yes |
| T009 | Build statement evidence extractor | WP02 | P1 | Yes |
| T010 | Implement confidence rubric | WP02 | P1 | No |
| T011 | Implement policy mention hooks | WP02 | P1 | No |
| T012 | Add detection unit tests | WP02 | P1 | No |
| T013 | Implement polite crawl client | WP03 | P1 | No |
| T014 | Add redirect trace capture | WP03 | P1 | Yes |
| T015 | Implement navigation sampler | WP03 | P1 | Yes |
| T016 | Implement stale lifecycle logic | WP03 | P1 | No |
| T017 | Implement monthly scheduler orchestration | WP03 | P1 | No |
| T018 | Add lifecycle integration tests | WP03 | P1 | No |
| T019 | Implement TOON schema validator | WP04 | P1 | No |
| T020 | Build TOON writer/loader cache | WP04 | P1 | No |
| T021 | Link artifact metadata to scans | WP04 | P1 | Yes |
| T022 | Implement latest snapshot resolver | WP04 | P1 | No |
| T023 | Add artifact replay CLI command | WP04 | P1 | Yes |
| T024 | Add artifact integration tests | WP04 | P1 | No |
| T025 | Implement scan trigger endpoint | WP05 | P2 | No |
| T026 | Implement scan status endpoint | WP05 | P2 | Yes |
| T027 | Implement artifact retrieval endpoints | WP05 | P2 | Yes |
| T028 | Implement host details endpoint | WP05 | P2 | Yes |
| T029 | Wire app dependencies and errors | WP05 | P2 | No |
| T030 | Add API contract tests | WP05 | P2 | No |
| T031 | Add observability metrics/log fields | WP06 | P2 | No |
| T032 | Add scheduler health checks/alerts | WP06 | P2 | Yes |
| T033 | Add performance benchmark harness | WP06 | P2 | Yes |
| T034 | Add crawl compliance assertions | WP06 | P2 | No |
| T035 | Update docs and quickstart | WP06 | P2 | No |
| T036 | Add end-to-end readiness regression | WP06 | P2 | No |
