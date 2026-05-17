@workflow @docs-contract
Feature: Subdomain scanning capability contract

  @sub_001 @workflow
  Scenario: [SUB-001] Subdomain scan workflow is present in the repository
    Then the repository file ".github/workflows/scan-subdomains.yml" should exist
