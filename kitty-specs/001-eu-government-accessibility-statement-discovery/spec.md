# Feature Specification: EU Government Accessibility Statement Discovery

**Feature Branch**: `001-eu-government-accessibility-statement-discovery`  
**Created**: 2026-02-26  
**Status**: Draft  
**Input**: User description: "I want to find accessibility statements in government websites where they are required. This is mostly Europe and now Canada. The focus will be Europe."

## Clarifications

### Session 2026-02-26

- Q: For domains that are unreachable at scan time, what output behavior should be required? → A: Keep prior cached result and mark as stale; on next run retest stale domains and delete if still unreachable.
- Q: How should statement detection confidence be represented in v1? → A: Three levels: high, medium, low.
- Q: What should be the canonical uniqueness key for a government site record? → A: Full hostname.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Detect Required Accessibility Statements (Priority: P1)

As a government compliance officer, I can review country-level government domains that are in scope of the EU Web Accessibility Directive and see whether an accessibility statement was found for each domain.

**Why this priority**: This is the core compliance outcome and delivers immediate value for legal and policy monitoring.

**Independent Test**: Can be fully tested by running a country scan on an input domain list and verifying the output includes statement presence status and statement URL (when found) for each in-scope domain.

**Acceptance Scenarios**:

1. **Given** a country domain list, **When** the scan runs, **Then** each listed domain receives a statement detection result (found, not found, or uncertain).
2. **Given** a domain with an accessibility statement in a local language, **When** scan results are generated, **Then** the statement is detected and linked in the output.
3. **Given** a domain with no detectable statement, **When** results are produced, **Then** it is clearly flagged for compliance follow-up.

---

### User Story 2 - Validate and Normalize Government Domains (Priority: P2)

As a government compliance officer, I can validate and normalize domain records so redirects, aliases, and primary/secondary pages do not create misleading duplicates in reporting.

**Why this priority**: Reliable domain identity is necessary for trustworthy compliance reporting and country comparisons.

**Independent Test**: Can be tested by providing known redirecting and duplicate domain inputs and confirming canonical domain mapping and redirect chains are consistently represented.

**Acceptance Scenarios**:

1. **Given** a domain that redirects, **When** scan outputs are written, **Then** the canonical destination and redirect chain are recorded.
2. **Given** multiple entries representing the same government site, **When** normalization is applied, **Then** the output identifies a single canonical domain record with associated aliases.

---

### User Story 3 - Produce Country TOON Outputs for Reuse (Priority: P3)

As a compliance officer or accessibility advocate, I can use country-specific cached TOON outputs that include key findings and sample URLs for downstream audits and accessibility spot-checks.

**Why this priority**: Structured country outputs support repeatable monitoring, sharing, and follow-up analysis.

**Independent Test**: Can be tested by generating outputs for one country and verifying required fields are present, complete, and reusable without rerunning the scan immediately.

**Acceptance Scenarios**:

1. **Given** a completed country scan, **When** output is saved, **Then** a country-specific TOON file is created and available for cached reuse.
2. **Given** a domain with crawlable navigation, **When** output is generated, **Then** exactly 10 sampled URLs from navigation are included for that domain.

---

### Edge Cases

- Temporarily unreachable domains keep the prior cached result and are marked as stale for that run.
- If a stale domain remains unreachable on the next scan, it is removed from the active domain set.
- How does the system handle statement pages that exist only in PDF or non-HTML formats?
- How does the system handle multilingual pages where statement terms differ by locale and script?
- What happens when fewer than 10 valid navigational URLs can be discovered for a domain?
- How does the system handle cross-domain redirects (for example from ministry subdomains to centralized government portals)?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST ingest country-organized government domain lists as input for scanning, including lists published by national authorities and curated public-sector repositories.
- **FR-002**: The system MUST support scanning with Europe as the default focus and permit inclusion of Canada in scope.
- **FR-003**: The system MUST classify each scanned domain as in-scope for required accessibility statements based on EU Web Accessibility Directive applicability rules for public-sector entities.
- **FR-004**: The system MUST detect accessibility statement evidence using multilingual term matching suitable for EU languages.
- **FR-005**: The system MUST record statement detection status per domain as found, not found, or uncertain.
- **FR-006**: The system MUST record the detected statement URL when statement evidence is found.
- **FR-007**: The system MUST normalize domains by resolving redirects and associating aliases/secondary entries with a canonical domain, where canonical uniqueness is defined at full hostname level.
- **FR-008**: The system MUST capture and store the redirect chain used to reach a canonical domain.
- **FR-009**: The system MUST include a statement detection confidence level for each domain using exactly three values: high, medium, or low.
- **FR-010**: The system MUST extract up to 10 sampled navigational URLs per canonical domain for downstream accessibility checks.
- **FR-011**: The system MUST produce one cached TOON output file per country scan.
- **FR-012**: The system MUST include, at minimum, canonical domain, statement URL (if any), detection confidence, detected language (if any), redirect chain, and sampled URLs in each country output.
- **FR-013**: The system MUST preserve provenance for domain sources (for example country-published lists vs previously collected scan sources) in output records, including source reference URL for each imported list.
- **FR-014**: The system MUST make it possible to include additional policy-term detections (such as GDPR or EN 301 549 mentions) in later phases without breaking existing output structure.
- **FR-015**: If a domain is unreachable during a scan and a prior cached record exists, the system MUST retain the prior cached record and mark it as stale in the current run output.
- **FR-016**: During the next scan, the system MUST retest stale domains and remove a domain from the active domain set when it remains unreachable again.
- **FR-017**: The system MUST maintain and use a translation glossary for accessibility-related detection terms that covers all official EU languages.

### Key Entities *(include if feature involves data)*

- **Country Scan**: A run scope representing one country, its domain set, timestamp, and cached output artifact.
- **Domain Record**: A government website entry keyed by full hostname, containing original domain, canonical domain, aliases, source provenance, and in-scope status.
- **Statement Detection Result**: Per-domain finding containing detection status, statement URL, language, confidence value, and supporting evidence markers.
- **Translation Glossary**: A managed set of accessibility-related terms and equivalents across all official EU languages used for multilingual detection.
- **Redirect Trace**: Ordered redirect path from input URL to canonical destination.
- **Sample URL Set**: Up to 10 navigational URLs selected for downstream accessibility testing.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a completed country scan, 100% of input domains receive a recorded detection status (found, not found, or uncertain).
- **SC-002**: At least 95% of domains that return reachable content include a completed canonicalization result (canonical domain plus redirect trace when applicable).
- **SC-003**: For domains with accessible navigation, at least 90% include 10 sampled navigational URLs; domains below 10 include an explicit shortfall reason.
- **SC-004**: Country output artifacts are generated successfully for 100% of initiated scans and can be retrieved from cache without rerunning collection.
- **SC-005**: Compliance officers can identify statement presence/absence for any scanned country dataset in under 5 minutes using only the country TOON output.

## Assumptions

- The first release focuses on public-sector entities covered by the EU Web Accessibility Directive; broader legal scopes are out of scope.
- Government-domain confidence scoring beyond source provenance is deferred to a later phase.
- Canada support is enabled in scope handling but Europe remains the primary operational focus for initial rollout.
