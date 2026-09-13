-- Separate ownership flows. Immutable normalized versions and raw-source references.
CREATE TABLE IF NOT EXISTS ownership_ingest_state (
    id TEXT PRIMARY KEY, accession TEXT NOT NULL, filer_cik BIGINT NOT NULL,
    issuer_cik BIGINT, kind TEXT NOT NULL, status TEXT NOT NULL,
    metadata TEXT NOT NULL, error TEXT, updated_at TEXT NOT NULL,
    last_successful_at TEXT, current_filing_id TEXT,
    UNIQUE(filer_cik, accession)
);
CREATE INDEX IF NOT EXISTS ownership_pending_idx ON ownership_ingest_state(status,updated_at);
CREATE TABLE IF NOT EXISTS ownership_filings (
    id TEXT PRIMARY KEY, state_id TEXT NOT NULL REFERENCES ownership_ingest_state(id),
    kind TEXT NOT NULL, filer_cik BIGINT NOT NULL, issuer_cik BIGINT, manager_cik BIGINT,
    accession TEXT NOT NULL, form TEXT NOT NULL, filed_date TEXT NOT NULL, report_period TEXT,
    record TEXT NOT NULL, documents TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ownership_filing_scope_idx ON ownership_filings(kind,issuer_cik,filed_date);
CREATE INDEX IF NOT EXISTS ownership_manager_period_idx ON ownership_filings(manager_cik,report_period);
CREATE TABLE IF NOT EXISTS ownership_insiders (
    id TEXT PRIMARY KEY, filing_id TEXT NOT NULL REFERENCES ownership_filings(id),
    issuer_cik BIGINT NOT NULL, owner_key TEXT NOT NULL, record TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ownership_insider_scope_idx ON ownership_insiders(issuer_cik,owner_key);
CREATE TABLE IF NOT EXISTS ownership_institutions (
    id TEXT PRIMARY KEY, filing_id TEXT NOT NULL REFERENCES ownership_filings(id),
    manager_cik BIGINT NOT NULL, cusip TEXT NOT NULL, record TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ownership_position_scope_idx ON ownership_institutions(cusip,manager_cik);
CREATE TABLE IF NOT EXISTS ownership_events (
    id TEXT PRIMARY KEY, filing_id TEXT NOT NULL REFERENCES ownership_filings(id),
    issuer_cik BIGINT NOT NULL, record TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ownership_event_scope_idx ON ownership_events(issuer_cik);
CREATE TABLE IF NOT EXISTS ownership_security_mappings (
    cusip TEXT PRIMARY KEY, issuer_cik BIGINT NOT NULL, security_title TEXT NOT NULL,
    source_url TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ownership_mapping_issuer_idx ON ownership_security_mappings(issuer_cik);
