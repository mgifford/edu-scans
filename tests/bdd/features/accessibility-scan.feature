@smoke @docs-contract
Feature: Accessibility scanning capability contract

  @acc_001 @smoke
  Scenario: [ACC-001] Accessibility scanner is a declared project capability
    Given the documentation file "README.md"
    Then it should include "Accessibility statement detection"
