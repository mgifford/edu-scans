@smoke @docs-contract
Feature: Social media scanning capability contract

  @soc_001 @smoke
  Scenario: [SOC-001] Social media scanner is a declared project capability
    Given the documentation file "README.md"
    Then it should include "Social media detection"
