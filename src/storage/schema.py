"""Metadata schema and migration bootstrap for scan lifecycle state."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class CountryScan:
    scan_id: str
    country_code: str
    run_month: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    artifact_path: str | None = None
    artifact_checksum: str | None = None
    host_total: int = 0
    host_processed: int = 0
    error_summary: str | None = None


@dataclass(slots=True)
class DomainRecord:
    country_code: str
    canonical_hostname: str
    input_hostname: str
    alias_hostnames: str = ""
    in_scope_wad: int = 1
    source_type: str = "other"
    source_reference_url: str = ""
    last_seen_scan_id: str | None = None
    stale: int = 0
    unreachable_streak: int = 0
    active: int = 1


@dataclass(slots=True)
class UrlValidationResult:
    url: str
    country_code: str
    scan_id: str
    status_code: int | None = None
    error_message: str | None = None
    redirected_to: str | None = None
    redirect_chain: str | None = None
    is_valid: int = 0
    failure_count: int = 0
    validated_at: str | None = None


@dataclass(slots=True)
class UrlTechResult:
    """Result of a technology detection scan for a single URL."""
    url: str
    country_code: str
    scan_id: str
    technologies: str  # JSON-encoded string: {tech_name: {versions: [...], categories: [...]}}
    error_message: str | None = None
    scanned_at: str | None = None


@dataclass(slots=True)
class UrlSocialMediaResult:
    """Result of a social media link scan for a single URL."""
    url: str
    country_code: str
    scan_id: str
    is_reachable: int = 1  # 1 = reachable, 0 = not reachable
    twitter_links: str = "[]"   # JSON list of twitter.com hrefs
    x_links: str = "[]"         # JSON list of x.com hrefs
    bluesky_links: str = "[]"   # JSON list of bsky.app / bsky.social hrefs
    mastodon_links: str = "[]"  # JSON list of detected Mastodon hrefs
    facebook_links: str = "[]"  # JSON list of facebook.com hrefs
    linkedin_links: str = "[]"  # JSON list of linkedin.com hrefs
    social_tier: str = "no_social"  # "unreachable"|"no_social"|"twitter_only"|"modern_only"|"mixed"
    error_message: str | None = None
    scanned_at: str | None = None
    # Tracks which platform set was active when this row was written.
    # Rows with platforms_version < SOCIAL_PLATFORMS_VERSION are re-scanned
    # so newly-added platforms (e.g. Facebook, LinkedIn) are picked up.
    platforms_version: int = 0


@dataclass(slots=True)
class UrlLighthouseResult:
    """Result of a Google Lighthouse scan for a single URL."""
    url: str
    country_code: str
    scan_id: str
    performance_score: float | None = None    # 0.0–1.0
    accessibility_score: float | None = None  # 0.0–1.0
    best_practices_score: float | None = None  # 0.0–1.0
    seo_score: float | None = None             # 0.0–1.0
    pwa_score: float | None = None             # 0.0–1.0
    error_message: str | None = None
    scanned_at: str | None = None


@dataclass(slots=True)
class UrlAccessibilityResult:
    """Result of an accessibility statement scan for a single URL."""

    url: str
    country_code: str
    scan_id: str
    is_reachable: int = 1           # 1 = reachable, 0 = not reachable
    has_statement: int = 0          # 1 = accessibility statement link found
    found_in_footer: int = 0        # 1 = link was found inside a <footer> element
    statement_links: str = "[]"     # JSON list of resolved statement URLs
    matched_terms: str = "[]"       # JSON list of matched glossary terms
    # JSON-encoded list of ThirdPartyScript dicts:
    # [{src, host, service_name, version, categories}, ...]
    scripts: str = "[]"
    error_message: str | None = None
    scanned_at: str | None = None


@dataclass(slots=True)
class UrlOverlayResult:
    """Result of an accessibility overlay scan for a single URL."""

    url: str
    country_code: str
    scan_id: str
    is_reachable: int = 1       # 1 = reachable, 0 = not reachable
    overlays: str = "[]"        # JSON list of detected overlay vendor names
    overlay_count: int = 0      # number of distinct overlays detected
    error_message: str | None = None
    scanned_at: str | None = None


@dataclass(slots=True)
class ValidationBatchState:
    """Tracks progress of batch validation cycles."""
    cycle_id: str
    country_code: str
    status: str  # pending, processing, completed, failed
    started_at: str | None = None
    completed_at: str | None = None
    github_issue_number: int | None = None
    error_message: str | None = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS country_scans (
    scan_id TEXT PRIMARY KEY,
    country_code TEXT NOT NULL,
    run_month TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    artifact_path TEXT,
    artifact_checksum TEXT,
    host_total INTEGER NOT NULL DEFAULT 0,
    host_processed INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT,
    UNIQUE(country_code, run_month, scan_id)
);

CREATE TABLE IF NOT EXISTS domain_records (
    country_code TEXT NOT NULL,
    canonical_hostname TEXT NOT NULL,
    input_hostname TEXT NOT NULL,
    alias_hostnames TEXT NOT NULL DEFAULT '',
    in_scope_wad INTEGER NOT NULL DEFAULT 1,
    source_type TEXT NOT NULL,
    source_reference_url TEXT NOT NULL,
    last_seen_scan_id TEXT,
    stale INTEGER NOT NULL DEFAULT 0,
    unreachable_streak INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (country_code, canonical_hostname)
);

CREATE TABLE IF NOT EXISTS url_validation_results (
    url TEXT NOT NULL,
    country_code TEXT NOT NULL,
    scan_id TEXT NOT NULL,
    status_code INTEGER,
    error_message TEXT,
    redirected_to TEXT,
    redirect_chain TEXT,
    is_valid INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    validated_at TEXT,
    PRIMARY KEY (url, scan_id)
);

CREATE INDEX IF NOT EXISTS idx_url_validation_country ON url_validation_results(country_code);
CREATE INDEX IF NOT EXISTS idx_url_validation_scan ON url_validation_results(scan_id);
CREATE INDEX IF NOT EXISTS idx_url_validation_failures ON url_validation_results(failure_count);

-- Migration: Added url_tech_results table for technology detection scan results
CREATE TABLE IF NOT EXISTS url_tech_results (
    url TEXT NOT NULL,
    country_code TEXT NOT NULL,
    scan_id TEXT NOT NULL,
    technologies TEXT NOT NULL DEFAULT '{}',
    error_message TEXT,
    scanned_at TEXT,
    PRIMARY KEY (url, scan_id)
);

CREATE INDEX IF NOT EXISTS idx_url_tech_country ON url_tech_results(country_code);
CREATE INDEX IF NOT EXISTS idx_url_tech_scan ON url_tech_results(scan_id);

-- Migration: Added url_social_media_results table for social media link scan results
CREATE TABLE IF NOT EXISTS url_social_media_results (
    url TEXT NOT NULL,
    country_code TEXT NOT NULL,
    scan_id TEXT NOT NULL,
    is_reachable INTEGER NOT NULL DEFAULT 1,
    twitter_links TEXT NOT NULL DEFAULT '[]',
    x_links TEXT NOT NULL DEFAULT '[]',
    bluesky_links TEXT NOT NULL DEFAULT '[]',
    mastodon_links TEXT NOT NULL DEFAULT '[]',
    facebook_links TEXT NOT NULL DEFAULT '[]',
    linkedin_links TEXT NOT NULL DEFAULT '[]',
    social_tier TEXT NOT NULL DEFAULT 'no_social',
    error_message TEXT,
    scanned_at TEXT,
    platforms_version INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (url, scan_id)
);

CREATE INDEX IF NOT EXISTS idx_social_media_country ON url_social_media_results(country_code);
CREATE INDEX IF NOT EXISTS idx_social_media_scan ON url_social_media_results(scan_id);
CREATE INDEX IF NOT EXISTS idx_social_media_tier ON url_social_media_results(social_tier);

-- Migration: Added url_lighthouse_results table for Google Lighthouse scan results
CREATE TABLE IF NOT EXISTS url_lighthouse_results (
    url TEXT NOT NULL,
    country_code TEXT NOT NULL,
    scan_id TEXT NOT NULL,
    performance_score REAL,
    accessibility_score REAL,
    best_practices_score REAL,
    seo_score REAL,
    pwa_score REAL,
    error_message TEXT,
    scanned_at TEXT,
    PRIMARY KEY (url, scan_id)
);

CREATE INDEX IF NOT EXISTS idx_lighthouse_country ON url_lighthouse_results(country_code);
CREATE INDEX IF NOT EXISTS idx_lighthouse_scan ON url_lighthouse_results(scan_id);

-- Migration: Added url_accessibility_results table for accessibility statement scan results
CREATE TABLE IF NOT EXISTS url_accessibility_results (
    url TEXT NOT NULL,
    country_code TEXT NOT NULL,
    scan_id TEXT NOT NULL,
    is_reachable INTEGER NOT NULL DEFAULT 1,
    has_statement INTEGER NOT NULL DEFAULT 0,
    found_in_footer INTEGER NOT NULL DEFAULT 0,
    statement_links TEXT NOT NULL DEFAULT '[]',
    matched_terms TEXT NOT NULL DEFAULT '[]',
    error_message TEXT,
    scanned_at TEXT,
    PRIMARY KEY (url, scan_id)
);

CREATE INDEX IF NOT EXISTS idx_accessibility_country ON url_accessibility_results(country_code);
CREATE INDEX IF NOT EXISTS idx_accessibility_scan ON url_accessibility_results(scan_id);
CREATE INDEX IF NOT EXISTS idx_accessibility_has_statement ON url_accessibility_results(has_statement);
CREATE INDEX IF NOT EXISTS idx_accessibility_in_footer ON url_accessibility_results(found_in_footer);

CREATE TABLE IF NOT EXISTS validation_batch_state (
    cycle_id TEXT NOT NULL,
    country_code TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    github_issue_number INTEGER,
    error_message TEXT,
    PRIMARY KEY (cycle_id, country_code)
);

CREATE INDEX IF NOT EXISTS idx_batch_state_cycle ON validation_batch_state(cycle_id);
CREATE INDEX IF NOT EXISTS idx_batch_state_status ON validation_batch_state(status);
CREATE INDEX IF NOT EXISTS idx_batch_state_issue ON validation_batch_state(github_issue_number);

CREATE TABLE IF NOT EXISTS issue_trigger_runs (
    issue_number INTEGER NOT NULL,
    trigger_prefix TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    PRIMARY KEY (issue_number, started_at)
);

CREATE INDEX IF NOT EXISTS idx_trigger_runs_issue ON issue_trigger_runs(issue_number);
CREATE INDEX IF NOT EXISTS idx_trigger_runs_status ON issue_trigger_runs(status);

-- Migration: Added url_third_party_js_results table for third-party JavaScript scan results
CREATE TABLE IF NOT EXISTS url_third_party_js_results (
    url TEXT NOT NULL,
    country_code TEXT NOT NULL,
    scan_id TEXT NOT NULL,
    is_reachable INTEGER NOT NULL DEFAULT 1,
    scripts TEXT NOT NULL DEFAULT '[]',
    error_message TEXT,
    scanned_at TEXT,
    PRIMARY KEY (url, scan_id)
);

CREATE INDEX IF NOT EXISTS idx_third_party_js_country ON url_third_party_js_results(country_code);
CREATE INDEX IF NOT EXISTS idx_third_party_js_scan ON url_third_party_js_results(scan_id);

-- Migration: Added url_overlay_results table for accessibility overlay scan results
CREATE TABLE IF NOT EXISTS url_overlay_results (
    url TEXT NOT NULL,
    country_code TEXT NOT NULL,
    scan_id TEXT NOT NULL,
    is_reachable INTEGER NOT NULL DEFAULT 1,
    overlays TEXT NOT NULL DEFAULT '[]',
    overlay_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    scanned_at TEXT,
    PRIMARY KEY (url, scan_id)
);

CREATE INDEX IF NOT EXISTS idx_overlay_country ON url_overlay_results(country_code);
CREATE INDEX IF NOT EXISTS idx_overlay_scan ON url_overlay_results(scan_id);
CREATE INDEX IF NOT EXISTS idx_overlay_has_overlay ON url_overlay_results(overlay_count);
"""


def _db_path_from_url(db_url: str) -> Path:
    if db_url.startswith("sqlite:///"):
        return Path(db_url.replace("sqlite:///", "", 1))
    return Path(db_url)


def initialize_schema(db_url: str) -> Path:
    """Create required schema tables and return resolved db path."""
    db_path = _db_path_from_url(db_url)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        # Migration: add facebook_links and linkedin_links to existing databases
        # that were created before these columns were added.
        # The column names below come from a hardcoded tuple and are never
        # derived from user input, so string interpolation is safe here.
        _NEW_SOCIAL_COLUMNS = (("facebook_links", "[]"), ("linkedin_links", "[]"))
        for col, default in _NEW_SOCIAL_COLUMNS:
            existing = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(url_social_media_results)"
                ).fetchall()
            }
            if col not in existing:
                conn.execute(
                    f"ALTER TABLE url_social_media_results "
                    f"ADD COLUMN {col} TEXT NOT NULL DEFAULT '{default}'"
                )
        # Migration: add platforms_version to existing databases.  Rows created
        # before this column existed receive DEFAULT 0, meaning they pre-date
        # full platform support and will be re-scanned when the skip logic
        # checks platforms_version >= SOCIAL_PLATFORMS_VERSION.
        existing_cols = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(url_social_media_results)"
            ).fetchall()
        }
        if "platforms_version" not in existing_cols:
            conn.execute(
                "ALTER TABLE url_social_media_results "
                "ADD COLUMN platforms_version INTEGER NOT NULL DEFAULT 0"
            )
        conn.commit()
    finally:
        conn.close()
    return db_path
