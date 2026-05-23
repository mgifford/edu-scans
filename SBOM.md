# SBOM and Dependency License Register

This file tracks the project software bill of materials (SBOM) at the direct-dependency level, with version and license-review checkpoints to support legal and security risk management.

## Scope

- Direct Python dependencies from `requirements.txt`
- Direct Node.js dependencies from `package.json`
- Core build/runtime tooling used in CI and local development

## Dependency Inventory

### Python dependencies (`requirements.txt`)

| Package | Version spec | Purpose | License review status |
|---|---:|---|---|
| setuptools | >=68.0,<81.0 | Packaging/runtime compatibility (`pkg_resources`) | Pending verification |
| PyYAML | >=6.0.1 | YAML parsing | Pending verification |
| fastapi | 0.115.6 | API framework | Pending verification |
| httpx | 0.28.1 | Async HTTP client for URL validation | Pending verification |
| pydantic | 2.10.5 | Data validation/models | Pending verification |
| pydantic-settings | 2.7.1 | Settings management | Pending verification |
| apscheduler | 3.10.4 | Scheduling/batch jobs | Pending verification |
| tldextract | 5.1.3 | Domain parsing | Pending verification |
| beautifulsoup4 | 4.12.3 | HTML parsing | Pending verification |
| tenacity | 9.0.0 | Retry logic | Pending verification |
| python-Wappalyzer | 0.3.1 | Technology detection | Pending verification |
| pytest | 9.0.3 | Test runner | Pending verification |
| pytest-asyncio | 1.3.0 | Async test support | Pending verification |
| pytest-mock | 3.14.0 | Mocking for tests | Pending verification |
| ruff | 0.9.10 | Linting | Pending verification |

### Node.js dependencies (`package.json`)

| Package | Version spec | Purpose | License review status |
|---|---:|---|---|
| @axe-core/playwright | ^4.10.2 | Accessibility smoke tests | Pending verification |
| @cucumber/cucumber | ^12.9.0 | BDD test execution | Pending verification |
| playwright | ^1.54.2 | Browser automation tests | Pending verification |

## Toolchain / Platform Components

| Component | Version/source | Purpose | License review status |
|---|---|---|---|
| Python | 3.12 (project standard) | Runtime | Pending verification |
| Node.js / npm | CI + local tooling (version per runner/environment) | JS test tooling | Pending verification |
| uv | CI and local dependency install tooling | Python env/dependency management | Pending verification |
| GitHub Actions | `.github/workflows/*` | CI/CD orchestration | Pending verification |
| SQLite | `data/metadata.db` | Local metadata storage | Pending verification |

## Change Tracking (Version + Licensing)

Use this log whenever dependency versions, dependency sets, or license decisions change.

| Date (UTC) | Changed files | Version changes summary | License review summary | Reviewer |
|---|---|---|---|---|
| 2026-05-23 | `requirements.txt`, `package.json`, `AGENTS.md`, `SBOM.md` | Initial SBOM baseline captured from manifests | Initial status set to Pending verification | Copilot Task Agent |

## Verification Workflow

1. Update this file in the same PR when dependency manifests or CI tooling dependencies change.
2. Verify declared licenses using package metadata and upstream repositories before marking entries as approved.
3. Run dependency vulnerability checks during upgrade work and record major risk decisions in PR notes.
4. Keep this markdown register aligned with any machine-readable SBOM artifacts produced in CI (for example CycloneDX or SPDX exports, if introduced).
