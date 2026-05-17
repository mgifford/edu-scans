@regression @docs-contract
Feature: URL validation behavior contracts

  @val_001 @smoke
  Scenario: [VAL-001] Remove URLs after two consecutive failures
    Given the documentation file "docs/url-validation-scanner.md"
    Then it should include "Second failure: URL is removed from the TOON file"

  @val_002 @regression
  Scenario: [VAL-002] Avoid same-session retries
    Given the documentation file "docs/url-validation-scanner.md"
    Then it should include "No retry in same session"
