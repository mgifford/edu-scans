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
