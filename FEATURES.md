# FEATURES.md

This file is the living source of truth for product behavior in `edu-scans`.

## Behavior-Spec Chain (required)

Every behavior change must update this chain end-to-end:

1. **Capability** in `FEATURES.md`
2. **User story** (in the capability section)
3. **Gherkin** scenario in `tests/bdd/features/*.feature`
4. **Step definitions** in `tests/bdd/steps/*.js`
5. **Cucumber execution** via `npm run test:bdd:docs-contract` (and Playwright-backed scenarios as they are added)

Pull requests that change scanner/workflow behavior are expected to update this chain.

## Capability Map

| Capability ID | Area | Status | Owner / Reviewer | Primary code areas |
|---|---|---|---|---|
| VAL | URL validation | Active | Validation maintainers | `src/services/url_validator.py`, `src/cli/validate_urls.py` |
| BATCH | Batch validation | Active | Validation maintainers | `src/services/batch_coordinator.py`, `src/cli/validate_urls_batch.py` |
| ISSUE | Issue-triggered validation | Active | Validation maintainers | `src/services/issue_trigger_handler.py`, `src/cli/issue_triggered_validation.py` |
| ACC | Accessibility scan | Active | Scanner maintainers | `src/services/accessibility_scanner.py`, `src/cli/scan_accessibility.py` |
| LH | Lighthouse scan | Active | Scanner maintainers | `src/services/lighthouse_scanner.py`, `src/cli/scan_lighthouse.py` |
| SOC | Social media scan | Active | Scanner maintainers | `src/services/social_media_scanner.py`, `src/cli/scan_social_media.py` |
| TECH | Technology scan | Active | Scanner maintainers | `src/services/tech_detector.py`, `src/cli/scan_technology.py` |
| TPJS | Third-party JavaScript scan | Active | Scanner maintainers | `src/services/third_party_js_scanner.py`, `src/cli/scan_third_party_js.py` |
| SUB | Subdomain scanning | Active | Scanner maintainers | `src/services/subdomain_scanner.py`, `src/cli/scan_subdomains.py` |
| REP | Reporting and progress publishing | Active | Reporting maintainers | `src/cli/generate_*_report.py`, `src/cli/generate_scan_progress.py` |

## User Stories by Capability

### VAL — URL validation
- **VAL-US-001:** As a maintainer, I need failed URLs removed after two consecutive failures so the dataset stays healthy.
- **VAL-US-002:** As a maintainer, I need validation to avoid same-session retries so each run is predictable.

### BATCH — Batch validation
- **BATCH-US-001:** As an operator, I need resumable validation cycles so long scans can continue across workflow runs.
- **BATCH-US-002:** As an operator, I need progress tracked in GitHub issues for visibility.

### ISSUE — Issue-triggered validation
- **ISSUE-US-001:** As a maintainer, I need title-prefix schedules so issue titles can control scan cadence.
- **ISSUE-US-002:** As an operator, I need validation workflows serialized to protect shared artifacts.

### ACC — Accessibility scanning
- **ACC-US-001:** As a stakeholder, I need accessibility statement scanning represented in published project behavior.

### LH — Lighthouse scanning
- **LH-US-001:** As a stakeholder, I need Lighthouse scanning represented in published project behavior.

### SOC — Social media scanning
- **SOC-US-001:** As a stakeholder, I need social media scanning represented in published project behavior.

### TECH — Technology scanning
- **TECH-US-001:** As a stakeholder, I need technology scanning represented in published project behavior.

### TPJS — Third-party JavaScript scanning
- **TPJS-US-001:** As a stakeholder, I need third-party JavaScript scanning represented in published project behavior.

### SUB — Subdomain scanning
- **SUB-US-001:** As a maintainer, I need subdomain scanning represented in project behavior and workflows.

### REP — Reporting
- **REP-US-001:** As a reader, I need scan progress and domain/report pages published clearly.

## Traceability Matrix

| Capability | Story ID | Feature file | Scenario IDs | Step definitions | Cucumber/Playwright status |
|---|---|---|---|---|---|
| VAL | VAL-US-001, VAL-US-002 | `tests/bdd/features/url-validation.feature` | VAL-001, VAL-002 | `tests/bdd/steps/docs_contract.steps.js` | Automated (Cucumber docs-contract) |
| BATCH | BATCH-US-001, BATCH-US-002 | `tests/bdd/features/batch-validation.feature` | BATCH-001, BATCH-002 | `tests/bdd/steps/docs_contract.steps.js` | Automated (Cucumber docs-contract) |
| ISSUE | ISSUE-US-001, ISSUE-US-002 | `tests/bdd/features/issue-triggered-validation.feature` | ISSUE-001, ISSUE-002 | `tests/bdd/steps/docs_contract.steps.js` | Automated (Cucumber docs-contract) |
| ACC | ACC-US-001 | `tests/bdd/features/accessibility-scan.feature` | ACC-001 | `tests/bdd/steps/docs_contract.steps.js` | Automated (Cucumber docs-contract) |
| LH | LH-US-001 | `tests/bdd/features/lighthouse-scan.feature` | LH-001 | `tests/bdd/steps/docs_contract.steps.js` | Automated (Cucumber docs-contract) |
| SOC | SOC-US-001 | `tests/bdd/features/social-media-scan.feature` | SOC-001 | `tests/bdd/steps/docs_contract.steps.js` | Automated (Cucumber docs-contract) |
| TECH | TECH-US-001 | `tests/bdd/features/technology-scan.feature` | TECH-001 | `tests/bdd/steps/docs_contract.steps.js` | Automated (Cucumber docs-contract) |
| TPJS | TPJS-US-001 | `tests/bdd/features/third-party-js-scan.feature` | TPJS-001 | `tests/bdd/steps/docs_contract.steps.js` | Automated (Cucumber docs-contract) |
| SUB | SUB-US-001 | `tests/bdd/features/subdomains-scan.feature` | SUB-001 | `tests/bdd/steps/docs_contract.steps.js` | Automated (Cucumber docs-contract) |
| REP | REP-US-001 | `tests/bdd/features/reporting.feature` | REP-001 | `tests/bdd/steps/docs_contract.steps.js` | Automated (Cucumber docs-contract) |

## Governance

- **Review ownership:** each capability is reviewed by the owner listed in the capability map.
- **PR expectation:** behavior-changing PRs update `FEATURES.md`, relevant user stories, and Gherkin scenarios.
- **Periodic review:** maintainers should review this file and related feature files regularly to remove stale scenarios, clarify wording, and keep tests readable for non-engineers.
