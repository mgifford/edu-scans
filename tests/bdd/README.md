# BDD Catalog

This directory defines behavior-driven development assets for `edu-scans`.

## Structure

- `tests/bdd/features/*.feature` — capability-level Gherkin specifications
- `tests/bdd/steps/*.js` — executable Cucumber step definitions

## Tag conventions

- `@smoke` — high-signal checks
- `@regression` — broader behavior rules
- `@workflow` — workflow/operational behavior
- `@docs-contract` — behavior asserted from repository docs/contracts

## Running

```bash
npm run test:bdd:docs-contract
npm run test:bdd
```
