# Phase 0 Research - EU Government Accessibility Statement Discovery

## Decision 1: Scheduled server job architecture
- Decision: Use a server-hosted scheduled scanning service with monthly default cadence.
- Rationale: Matches stakeholder preference for recurring cached country outputs without manual invocation.
- Alternatives considered: Batch-only CLI runs (manual operational burden), hybrid CLI plus scheduler (more moving parts in v1).

## Decision 2: Crawl behavior and politeness
- Decision: Apply per-host rate limiting, honor robots directives, and respect retry headers while scanning navigation pages.
- Rationale: Government domains have mixed infrastructure quality and require conservative crawl behavior.
- Alternatives considered: Aggressive global crawling (higher block risk), no robots handling (compliance risk).

## Decision 3: Canonicalization and redirect handling
- Decision: Track full redirect chain and map each input to a canonical full hostname key.
- Rationale: Full hostname uniqueness is a confirmed requirement and avoids over-collapsing ministry/agency sites.
- Alternatives considered: Base-domain key (can merge unrelated entities), first-hop redirect only (misses real endpoint).

## Decision 4: Unreachable host lifecycle
- Decision: If unreachable and prior data exists, keep prior record and mark stale; on next run retest and remove if still unreachable.
- Rationale: Preserves continuity while allowing eventual cleanup of permanently unavailable domains.
- Alternatives considered: Immediate deletion on first failure (high false removals), never remove stale hosts (degraded data quality).

## Decision 5: Confidence model
- Decision: Represent statement detection confidence as `high`, `medium`, or `low`.
- Rationale: Required by stakeholder and suitable for triage workflows by compliance officers.
- Alternatives considered: Numeric 0-100 score (less interpretable for v1), binary confidence (too coarse).

## Decision 6: Multilingual detection and glossary
- Decision: Maintain a detection glossary covering accessibility-related terms across all official EU languages.
- Rationale: Statement detection must work across multilingual government portals.
- Alternatives considered: English-only matching (insufficient), ad hoc translation APIs (low reproducibility).

## Decision 7: Data exposure and contracts
- Decision: Expose a minimal API for triggering scans, checking run status, and retrieving latest or monthly country TOON artifacts.
- Rationale: Supports operations and downstream consumers while keeping API surface small.
- Alternatives considered: File-only access without API (harder operational visibility), broad CRUD API (unnecessary complexity).

## Decision 8: Provenance traceability
- Decision: Preserve source provenance per imported domain list, including source reference URL.
- Rationale: Users ingest both official national lists and curated public repositories and need auditable lineage.
- Alternatives considered: Country-level source only (insufficient traceability), no source URL capture (weaker auditability).

## Resolved Clarification Status
- No unresolved planning clarifications remain for Phase 1 design.
