@workflow @docs-contract
Feature: Batched validation behavior contracts

  @batch_001 @smoke
  Scenario: [BATCH-001] Batched validation is resumable across workflow runs
    Given the documentation file "docs/batched-validation.md"
    Then it should include "The system is fully resumable"

  @batch_002 @workflow
  Scenario: [BATCH-002] Batch progress is tracked in GitHub issues
    Given the documentation file "docs/batched-validation.md"
    Then it should include each of:
      | GitHub issue shows: |
      | ✅ Completed:        |
      | ⏳ Pending:          |
