-- Durable public SEC lexical index. Text and source metadata are immutable per content version.
-- Position postings provide exact phrases across long filings without a tsvector position ceiling.
CREATE TABLE IF NOT EXISTS research_filings (
    cik BIGINT NOT NULL,
    accession TEXT NOT NULL,
    form TEXT,
    filed_date TEXT,
    company_name TEXT,
    source_id TEXT NOT NULL DEFAULT 'sec-edgar',
    visibility TEXT NOT NULL DEFAULT 'public',
    inventory_status TEXT NOT NULL DEFAULT 'pending',
    inventory_error TEXT,
    checked_at TEXT,
    PRIMARY KEY (cik, accession)
);
CREATE TABLE IF NOT EXISTS research_documents (
    document_id TEXT PRIMARY KEY,
    cik BIGINT NOT NULL,
    accession TEXT NOT NULL,
    filename TEXT NOT NULL,
    title TEXT NOT NULL,
    company_name TEXT,
    form TEXT,
    filed_date TEXT,
    source_url TEXT NOT NULL,
    source_id TEXT NOT NULL DEFAULT 'sec-edgar',
    visibility TEXT NOT NULL DEFAULT 'public',
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    current_version_id TEXT,
    discovered_at TEXT NOT NULL,
    attempted_at TEXT,
    UNIQUE (cik, accession, filename)
);
CREATE INDEX IF NOT EXISTS research_documents_scope_idx ON research_documents (source_id, visibility, cik, form, filed_date);
CREATE INDEX IF NOT EXISTS research_documents_status_idx ON research_documents (status, attempted_at);
CREATE TABLE IF NOT EXISTS research_versions (
    version_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES research_documents(document_id),
    content_sha256 TEXT NOT NULL,
    raw_path TEXT NOT NULL,
    text_content TEXT NOT NULL,
    source_metadata TEXT NOT NULL,
    indexed_at TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    content_bytes BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS research_versions_document_idx ON research_versions (document_id);
CREATE TABLE IF NOT EXISTS research_terms (
    version_id TEXT NOT NULL REFERENCES research_versions(version_id),
    term TEXT NOT NULL,
    position BIGINT NOT NULL,
    PRIMARY KEY (version_id, position)
);
CREATE INDEX IF NOT EXISTS research_terms_lookup_idx ON research_terms (term, version_id, position);
CREATE TABLE IF NOT EXISTS research_index_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
