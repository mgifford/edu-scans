@workflow @docs-contract
Feature: Issue-triggered validation behavior contracts

  @issue_001 @smoke
  Scenario: [ISSUE-001] Prefix-based schedules are documented
    Given the documentation file "docs/issue-triggered-validation.md"
    Then it should include each of:
      | SCAN:      |
      | QUARTERLY: |
      | MONTHLY:   |
      | WEEKLY:    |

  @issue_002 @workflow
  Scenario: [ISSUE-002] Validation workflows are serialized for shared artifacts
    Given the documentation file "docs/issue-triggered-validation.md"
    Then it should include "Only one validation workflow runs at a time"
