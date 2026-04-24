# Data Model - EU Government Accessibility Statement Discovery

## Entity: CountryScan
Purpose: Represents one scan execution for a country and month.

Fields:
- `scan_id` (string, unique)
- `country_code` (string, ISO 3166-1 alpha-2)
- `run_month` (string, `YYYY-MM`)
- `status` (enum: `queued`, `running`, `completed`, `failed`)
- `started_at` (datetime)
- `finished_at` (datetime, nullable)
- `artifact_path` (string, nullable)
- `artifact_checksum` (string, nullable)
- `host_total` (integer)
- `host_processed` (integer)
- `error_summary` (string, nullable)

Validation rules:
- One active `CountryScan` per `country_code` at a time.
- One completed monthly artifact per `country_code` + `run_month`.

State transitions:
- `queued` -> `running` -> `completed`
- `queued` -> `running` -> `failed`

## Entity: DomainRecord
Purpose: Canonical government site entry for scanning and reporting.

Fields:
- `country_code` (string)
- `canonical_hostname` (string, unique within country)
- `input_hostname` (string)
- `alias_hostnames` (array of string)
- `in_scope_wad` (boolean)
- `source_type` (enum: `official`, `curated`, `archive`, `other`)
- `source_reference_url` (string)
- `last_seen_scan_id` (string)
- `stale` (boolean)
- `unreachable_streak` (integer)
- `active` (boolean)

Validation rules:
- Canonical uniqueness key is `country_code + canonical_hostname`.
- `source_reference_url` required for imported list records.
- When `unreachable_streak >= 2` on consecutive scans, set `active = false` and remove from active scan set.

State transitions:
- `active=true, stale=false` (normal)
- `active=true, stale=true` (first unreachable)
- `active=false` (second consecutive unreachable)

## Entity: StatementDetectionResult
Purpose: Detection outcome for one canonical hostname in one scan.

Fields:
- `scan_id` (string)
- `country_code` (string)
- `canonical_hostname` (string)
- `detection_status` (enum: `found`, `not_found`, `uncertain`)
- `statement_url` (string, nullable)
- `confidence` (enum: `high`, `medium`, `low`)
- `detected_language` (string, nullable, BCP-47)
- `policy_mentions` (array of string; optional, e.g. GDPR, EN 301 549)
- `evidence_terms` (array of string)
- `created_at` (datetime)

Validation rules:
- If `detection_status = found`, `statement_url` must be present.
- `confidence` must be one of `high|medium|low`.

## Entity: RedirectTrace
Purpose: Ordered redirect history used to resolve canonical hostname.

Fields:
- `scan_id` (string)
- `country_code` (string)
- `canonical_hostname` (string)
- `hops` (array of objects with `position`, `from_url`, `to_url`, `status_code`)

Validation rules:
- Hop `position` starts at 1 and increases consecutively.

## Entity: SampleUrlSet
Purpose: Navigation sample used for downstream audits (for example Lighthouse).

Fields:
- `scan_id` (string)
- `country_code` (string)
- `canonical_hostname` (string)
- `sampled_urls` (array of string, max 10)
- `sample_shortfall_reason` (string, nullable)

Validation rules:
- `sampled_urls` length must be <= 10.
- If length < 10, `sample_shortfall_reason` must be present.

## Entity: TranslationGlossary
Purpose: Canonical glossary terms used for multilingual statement detection.

Fields:
- `term_key` (string, e.g. `accessibility_statement`)
- `language_code` (string, BCP-47)
- `term_value` (string)
- `active` (boolean)
- `updated_at` (datetime)

Validation rules:
- Must include entries for all official EU languages.
- Duplicate `term_key + language_code` pairs are not allowed.

## Relationships
- `CountryScan` 1-to-many `StatementDetectionResult`
- `CountryScan` 1-to-many `RedirectTrace`
- `CountryScan` 1-to-many `SampleUrlSet`
- `DomainRecord` 1-to-many historical `StatementDetectionResult`
- `TranslationGlossary` influences detection logic for `StatementDetectionResult`

## TOON Artifact Mapping
Each country monthly TOON artifact includes:
- country metadata (`country_code`, `run_month`, `scan_id`)
- array of domain result objects keyed by `canonical_hostname`
- for each domain: `statement_url`, `detection_status`, `confidence`, `detected_language`, `redirect_chain`, `sampled_urls`, `source_reference_url`, `stale`
