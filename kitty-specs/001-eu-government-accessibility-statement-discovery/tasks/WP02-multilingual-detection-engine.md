---
work_package_id: "WP02"
subtasks:
  - "T007"
  - "T008"
  - "T009"
  - "T010"
  - "T011"
  - "T012"
title: "Multilingual Detection Engine"
phase: "Phase 2 - Detection Core"
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

# Work Package Prompt: WP02 - Multilingual Detection Engine

## Objectives and Success Criteria

- Build glossary-driven statement detection across official EU languages.
- Emit statement status, URL, confidence tier, language tag, and evidence terms.
- Success criteria:
  - Glossary contains complete official EU language coverage.
  - Detection status is one of `found`, `not_found`, `uncertain`.
  - Confidence output is one of `high`, `medium`, `low`.

## Context and Constraints

- Depends on WP01 foundations.
- Must align with FR-004, FR-009, FR-014, FR-017 from spec.
- Keep policy mentions additive; they should not block main statement detection.

Implementation command for this WP:
- `spec-kitty implement WP02 --base WP01`

## Subtasks and Detailed Guidance

### Subtask T007 - Implement EU glossary store
- Purpose: Provide canonical multilingual term source for detection.
- Steps:
  1. Create glossary data model in `src/glossary/glossary_store.py`.
  2. Add loader API from static resources or managed data input.
  3. Validate presence of all official EU language codes.
  4. Add duplicate-key guard on `term_key + language_code`.
- Files:
  - `src/glossary/glossary_store.py`
  - `src/glossary/data/`
  - `tests/unit/test_glossary_store.py`
- Parallel: No.

### Subtask T008 - Build multilingual term matcher
- Purpose: Detect statement phrases robustly across locales.
- Steps:
  1. Implement matcher in `src/services/term_matcher.py`.
  2. Normalize whitespace/diacritics/casing consistently.
  3. Return matched terms with language hints.
  4. Expose interface consumable by extractor and confidence modules.
- Files:
  - `src/services/term_matcher.py`
  - `tests/unit/test_term_matcher.py`
- Parallel: Yes after T007 contracts.

### Subtask T009 - Build statement evidence extractor
- Purpose: Extract statement candidates from page content and references.
- Steps:
  1. Implement extractor in `src/services/statement_extractor.py`.
  2. Parse HTML anchors/headings/title and detect likely statement links.
  3. Handle non-HTML statement references (for example PDF links) as evidence.
  4. Return candidate URL list and supporting evidence terms.
- Files:
  - `src/services/statement_extractor.py`
  - `tests/unit/test_statement_extractor.py`
- Parallel: Yes after T007 contracts.

### Subtask T010 - Implement confidence rubric
- Purpose: Convert evidence richness into required confidence levels.
- Steps:
  1. Add `src/services/confidence.py` with deterministic rubric.
  2. Define high-confidence criteria requiring multiple strong signals.
  3. Map ambiguous cases to medium/low appropriately.
  4. Provide explanatory reason codes for debugging and review.
- Files:
  - `src/services/confidence.py`
  - `tests/unit/test_confidence.py`
- Parallel: No.

### Subtask T011 - Implement policy mention hooks
- Purpose: Support optional future signals without breaking v1 output shape.
- Steps:
  1. Add `src/services/policy_mentions.py`.
  2. Detect mentions for GDPR and EN 301 549 terms.
  3. Return optional annotations that can be included in result records.
- Files:
  - `src/services/policy_mentions.py`
  - `tests/unit/test_policy_mentions.py`
- Parallel: Yes after T008.

### Subtask T012 - Add detection unit test suite
- Purpose: Lock expected behavior before orchestration integration.
- Steps:
  1. Build comprehensive suite in `tests/unit/test_detection_engine.py`.
  2. Include multilingual examples and edge cases for false positives.
  3. Include confidence mapping assertions.
  4. Include policy mention non-regression checks.
- Files:
  - `tests/unit/test_detection_engine.py`
- Parallel: No.

## Test Strategy

- Unit-first package with fixture-based multilingual examples.
- Include negative tests (generic accessibility words not tied to statements).
- Verify deterministic confidence outputs.

## Risks and Mitigations

- Risk: low-quality translations causing misses.
  - Mitigation: enforce glossary completeness checks and test fixtures per language family.
- Risk: over-detection on unrelated pages.
  - Mitigation: confidence rubric requires multi-signal validation for high confidence.

## Review Guidance

- Reviewers should spot-check at least three language families.
- Confirm extractor and matcher produce explainable evidence fields.
- Confirm policy mention support is optional and non-blocking.

## Activity Log

- 2026-02-26T09:14:51Z - system - lane=planned - Prompt created.
