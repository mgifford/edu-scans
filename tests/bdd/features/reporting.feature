@regression @docs-contract
Feature: Reporting capability contract

  @rep_001 @regression
  Scenario: [REP-001] Scan progress report is a published output
    Given the documentation file "docs/index.md"
    Then it should include each of:
      | Scan Progress Report |
      | Social Media         |
      | Accessibility Statements |
      | Technology Scanning  |
