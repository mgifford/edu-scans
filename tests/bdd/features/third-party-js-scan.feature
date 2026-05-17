@smoke @docs-contract
Feature: Third-party JavaScript scanning capability contract

  @tpjs_001 @smoke
  Scenario: [TPJS-001] Third-party JavaScript scanner is a declared project capability
    Given the documentation file "README.md"
    Then it should include "Third-party JavaScript detection"
