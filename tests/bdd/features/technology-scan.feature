@smoke @docs-contract
Feature: Technology scanning capability contract

  @tech_001 @smoke
  Scenario: [TECH-001] Technology scanner is a declared project capability
    Given the documentation file "README.md"
    Then it should include "Technology detection"
