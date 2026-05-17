@smoke @docs-contract
Feature: Lighthouse scanning capability contract

  @lh_001 @smoke
  Scenario: [LH-001] Lighthouse scanner is a declared project capability
    Given the documentation file "README.md"
    Then it should include "Lighthouse audits"
