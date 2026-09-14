-- Serving schema (Postgres). GENERATED from migrations/ by `make schema` -- do not edit by hand.
-- Apply with `filings-hub load` (which runs the migrations) or `psql -f filings_hub/db/schema.sql`.

-- ==== 0001_initial.sql ====
-- 0001: serving tables (Postgres). Facts stay in the Parquet lake.
CREATE TABLE IF NOT EXISTS companies (
    cik                                 BIGINT PRIMARY KEY,
    name                                TEXT NOT NULL,
    ticker                              TEXT,
    exchange                            TEXT,
    sic                                 TEXT,
    sic_description                     TEXT,
    entity_type                         TEXT,
    category                            TEXT,
    state_of_incorporation              TEXT,
    state_of_incorporation_description  TEXT,
    fiscal_year_end                     TEXT,
    ein                                 TEXT,
    former_names                        TEXT[],
    business_state                      TEXT,
    business_city                       TEXT,
    website                             TEXT,
    is_listed                           BOOLEAN NOT NULL DEFAULT FALSE,
    is_active                           BOOLEAN NOT NULL DEFAULT FALSE,
    last_filing_date                    DATE,
    last_financial_report_date          DATE,
    last_financial_report_form          TEXT,
    filing_count                        BIGINT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS companies_name_idx ON companies (lower(name));
CREATE INDEX IF NOT EXISTS companies_ticker_idx ON companies (ticker);

CREATE TABLE IF NOT EXISTS tickers (
    cik         BIGINT NOT NULL,
    ticker      TEXT NOT NULL,
    exchange    TEXT,
    is_primary  BOOLEAN NOT NULL DEFAULT FALSE,
    source      TEXT,
    PRIMARY KEY (cik, ticker)
);
CREATE INDEX IF NOT EXISTS tickers_ticker_idx ON tickers (ticker);

CREATE TABLE IF NOT EXISTS filings (
    accession               TEXT PRIMARY KEY,
    cik                     BIGINT NOT NULL,
    form                    TEXT NOT NULL,
    filed_date              DATE,
    report_date             DATE,
    acceptance_datetime     TIMESTAMP,
    act                     TEXT,
    file_number             TEXT,
    film_number             TEXT,
    items                   TEXT[],
    size                    BIGINT,
    is_xbrl                 BOOLEAN,
    is_inline_xbrl          BOOLEAN,
    primary_doc             TEXT,
    primary_doc_description TEXT,
    primary_doc_url         TEXT,
    filing_index_url        TEXT,
    source                  TEXT,
    year                    INTEGER
);
CREATE INDEX IF NOT EXISTS filings_cik_filed_idx ON filings (cik, filed_date DESC);
CREATE INDEX IF NOT EXISTS filings_form_idx ON filings (form);

CREATE TABLE IF NOT EXISTS periods (
    cik                                 BIGINT NOT NULL,
    period_label                        TEXT NOT NULL,
    fiscal_year                         INTEGER NOT NULL,
    fiscal_quarter                      SMALLINT NOT NULL,
    period_type                         TEXT NOT NULL,
    period_end                          DATE NOT NULL,
    results_accession                   TEXT NOT NULL,
    results_form                        TEXT,
    results_filed_date                  DATE,
    results_primary_doc_url             TEXT,
    earnings_release_accession          TEXT,
    earnings_release_filed_date         DATE,
    earnings_release_primary_doc_url    TEXT,
    amendment_accessions                TEXT[],
    label_method                        TEXT,
    statements_source                   TEXT,
    checks_passed                       BOOLEAN,
    PRIMARY KEY (cik, period_label)
);
CREATE INDEX IF NOT EXISTS periods_cik_end_idx ON periods (cik, period_end DESC);

CREATE TABLE IF NOT EXISTS statements (
    accession           TEXT NOT NULL,
    cik                 BIGINT NOT NULL,
    statement           TEXT NOT NULL,
    report              INTEGER,
    line                INTEGER,
    line_order          INTEGER NOT NULL,
    is_parenthetical    BOOLEAN NOT NULL DEFAULT FALSE,
    concept             TEXT NOT NULL,
    taxonomy            TEXT,
    label               TEXT,
    standard_label      TEXT,
    negating            BOOLEAN,
    is_abstract         BOOLEAN,
    is_custom           BOOLEAN,
    iord                TEXT,
    crdr                TEXT,
    datatype            TEXT,
    period_start        DATE,
    period_end          DATE,
    period_end_rounded  DATE,
    qtrs                INTEGER,
    unit                TEXT,
    value               DOUBLE PRECISION,
    value_presented     DOUBLE PRECISION,
    is_primary_period   BOOLEAN NOT NULL,
    is_subtotal         BOOLEAN,
    parent_concept      TEXT,
    source              TEXT NOT NULL,
    fsds_quarter        TEXT,
    form                TEXT,
    filed_date          DATE,
    checks_passed       BOOLEAN
);
CREATE INDEX IF NOT EXISTS statements_accession_idx ON statements (accession, statement, line_order);
CREATE INDEX IF NOT EXISTS statements_cik_idx ON statements (cik);

CREATE TABLE IF NOT EXISTS statement_checks (
    accession   TEXT NOT NULL,
    cik         BIGINT NOT NULL,
    statement   TEXT NOT NULL,
    check_name  TEXT NOT NULL,
    passed      BOOLEAN NOT NULL,
    lhs         DOUBLE PRECISION,
    rhs         DOUBLE PRECISION,
    difference  DOUBLE PRECISION,
    detail      TEXT,
    source      TEXT,
    PRIMARY KEY (accession, statement, check_name)
);
CREATE INDEX IF NOT EXISTS statement_checks_failed_idx ON statement_checks (passed) WHERE NOT passed;

CREATE TABLE IF NOT EXISTS run_log (
    run_id               TEXT PRIMARY KEY,
    kind                 TEXT,
    started_at           TIMESTAMP,
    finished_at          TIMESTAMP,
    duration_seconds     DOUBLE PRECISION,
    status               TEXT,
    index_dates          TEXT[],
    new_filings          BIGINT,
    ciks_refreshed       BIGINT,
    facts_rows           BIGINT,
    statements_built     BIGINT,
    fsds_quarters_loaded TEXT[],
    failures             TEXT[],
    error                TEXT,
    db_loaded            BOOLEAN
);

-- ==== 0002_search_indexes.sql ====
-- 0002: make company search index-friendly at full EDGAR scale (~900k companies).
--
-- The search query is a UNION of one branch per identifier (name, ticker, CIK) so each branch can use
-- an index; a single OR across the three columns forces a sequential scan instead.
--
-- The name branch needs a trigram index for the leading-wildcard LIKE. pg_trgm is a trusted extension
-- on PostgreSQL 13+ and on the managed providers, but a restricted role may still be refused it, so the
-- whole block is wrapped: if the extension cannot be created the migration still succeeds and company
-- search falls back to a sequential scan.
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE INDEX IF NOT EXISTS companies_name_trgm_idx ON companies USING gin (lower(name) gin_trgm_ops);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pg_trgm unavailable (%); company search falls back to a sequential scan', SQLERRM;
END $$;

-- Ranking columns for the candidate set.
CREATE INDEX IF NOT EXISTS companies_rank_idx ON companies (is_active DESC, filing_count DESC);

-- ==== 0003_filings_cofiler_key.sql ====
-- 0003: one EDGAR accession can belong to several CIKs.
--
-- A parent and its operating partnership file a combined 10-K under a single accession number, and the
-- daily index lists one line per co-filer. `accession` alone is therefore not a key: loading both rows
-- violated filings_pkey. The key is (cik, accession); a plain index keeps accession lookups fast.
ALTER TABLE filings DROP CONSTRAINT IF EXISTS filings_pkey;
ALTER TABLE filings ADD CONSTRAINT filings_pkey PRIMARY KEY (cik, accession);
CREATE INDEX IF NOT EXISTS filings_accession_idx ON filings (accession);

-- ==== 0004_run_log_steps.sql ====
-- 0004: per-step timings on run_log, so a slow backfill can be attributed to a step.
ALTER TABLE run_log ADD COLUMN IF NOT EXISTS steps TEXT[];

-- ==== 0005_company_metrics.sql ====
-- 0005: latest annual key numbers per company (peers, ranking). Rebuilt from the lake on every load.
CREATE TABLE IF NOT EXISTS company_metrics (
    cik                 BIGINT PRIMARY KEY,
    period_label        TEXT,
    fiscal_year         INTEGER,
    period_end          DATE,
    results_accession   TEXT,
    revenue             DOUBLE PRECISION,
    net_income          DOUBLE PRECISION,
    eps_diluted         DOUBLE PRECISION,
    total_assets        DOUBLE PRECISION,
    operating_cash_flow DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS company_metrics_revenue_idx ON company_metrics (revenue DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS companies_sic_idx ON companies (sic);

-- ==== 0006_accounts.sql ====
-- 0006: accounts and the preference spine (used when the API serves from Postgres).
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    plan        TEXT NOT NULL DEFAULT 'free',
    locale      TEXT,
    timezone    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scope       TEXT NOT NULL,          -- global | sector | company | statement | export
    scope_key   TEXT NOT NULL DEFAULT '',
    key         TEXT NOT NULL,
    value       JSONB,
    source      TEXT NOT NULL DEFAULT 'explicit',   -- explicit | inferred | preset
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, scope, scope_key, key)
);
CREATE TABLE IF NOT EXISTS auth_tokens (
    token_hash  TEXT PRIMARY KEY,
    record      JSONB NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS pref_events (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL,
    key         TEXT,
    scope       TEXT,
    old         JSONB,
    new         JSONB,
    source      TEXT,
    at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pref_events_user_idx ON pref_events (user_id, at DESC);

-- ==== 0007_user_profile.sql ====
-- 0007: the sign-up profile (who the analyst is) on users.
ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS company TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS specialty TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS country TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS marketing_opt_in BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMPTZ;

-- ==== 0008_account_security.sql ====
-- Durable sessions and tenant authorization. The record preserves API timestamps as ISO strings;
-- indexed identity columns and foreign keys constrain ownership independently of JSON contents.
CREATE TABLE IF NOT EXISTS account_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    record JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS account_sessions_user_idx ON account_sessions (user_id);

CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    record JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS organization_memberships (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
    record JSONB NOT NULL,
    UNIQUE (organization_id, user_id)
);
CREATE INDEX IF NOT EXISTS organization_memberships_user_idx ON organization_memberships (user_id);

CREATE TABLE IF NOT EXISTS account_security_audit (
    id TEXT PRIMARY KEY,
    organization_id TEXT REFERENCES organizations(id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL,
    record JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS account_security_audit_org_idx ON account_security_audit (organization_id);
CREATE INDEX IF NOT EXISTS account_security_audit_actor_idx ON account_security_audit (actor_id);

-- ==== 0009_research_index.sql ====
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

-- ==== 0010_serving_publications.sql ====
-- Published in the same transaction as all serving-table changes. Failed loads leave no publication.
CREATE TABLE IF NOT EXISTS serving_publications (
    publication_id UUID PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('full', 'incremental')),
    published_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    counts JSONB NOT NULL,
    all_periods BOOLEAN NOT NULL,
    source_root TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS serving_publications_recent ON serving_publications (published_at DESC);

-- ==== 0011_research_projects.sql ====
-- Scoped, revisioned user-authored projects. Evidence pointers do not copy provider content.
CREATE TABLE IF NOT EXISTS research_projects (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES users(id),
    organization_id TEXT REFERENCES organizations(id),
    record JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS research_projects_owner_idx ON research_projects (owner_id);
CREATE INDEX IF NOT EXISTS research_projects_org_idx ON research_projects (organization_id);
CREATE TABLE IF NOT EXISTS research_notes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES research_projects(id) ON DELETE CASCADE,
    record JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS research_notes_project_idx ON research_notes (project_id);

-- ==== 0012_cofiler_checks.sql ====
-- Quality results belong to an issuer even when a filing accession is shared by co-filers.
ALTER TABLE statement_checks DROP CONSTRAINT IF EXISTS statement_checks_pkey;
ALTER TABLE statement_checks ADD CONSTRAINT statement_checks_pkey PRIMARY KEY (cik, accession, statement, check_name);

-- ==== 0013_research_jobs.sql ====
CREATE TABLE IF NOT EXISTS research_jobs (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL,
    not_before DOUBLE PRECISION NOT NULL,
    lease_expires DOUBLE PRECISION,
    record TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS research_jobs_queue_idx ON research_jobs(status,not_before);
-- All corpus-writing jobs share one fence. Scope partitioning is intentionally not claimed.
CREATE TABLE IF NOT EXISTS research_worker_fence (
    id INTEGER PRIMARY KEY,
    job_id TEXT,
    token TEXT,
    expires DOUBLE PRECISION
);
INSERT INTO research_worker_fence(id) VALUES(1) ON CONFLICT DO NOTHING;

-- ==== 0014_cited_research.sql ====
-- Immutable code-point spans. Embeddings never grant access to their parent document.
CREATE TABLE IF NOT EXISTS research_text_projections (
    projection_id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES research_versions(version_id),
    extractor_version TEXT NOT NULL,
    text_content TEXT NOT NULL,
    pages TEXT NOT NULL,
    prepared_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_prepared_projection (
    version_id TEXT PRIMARY KEY REFERENCES research_versions(version_id),
    projection_id TEXT NOT NULL REFERENCES research_text_projections(projection_id)
);
CREATE TABLE IF NOT EXISTS research_preparation_failures (
    version_id TEXT NOT NULL REFERENCES research_versions(version_id),
    extractor_version TEXT NOT NULL,
    error_code TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    failed_at TEXT NOT NULL,
    PRIMARY KEY(version_id, extractor_version)
);
CREATE TABLE IF NOT EXISTS research_prepared_versions (
    version_id TEXT PRIMARY KEY REFERENCES research_versions(version_id),
    prepared_at TEXT NOT NULL,
    span_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS research_spans (
    span_id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES research_versions(version_id),
    start_offset INTEGER NOT NULL,
    end_offset INTEGER NOT NULL,
    text_content TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS research_spans_version_idx ON research_spans(version_id);
CREATE TABLE IF NOT EXISTS research_span_projections (
    span_id TEXT PRIMARY KEY REFERENCES research_spans(span_id),
    projection_id TEXT NOT NULL REFERENCES research_text_projections(projection_id)
);
CREATE TABLE IF NOT EXISTS research_span_terms (
    span_id TEXT NOT NULL REFERENCES research_spans(span_id),
    term TEXT NOT NULL,
    PRIMARY KEY(term, span_id)
);
CREATE TABLE IF NOT EXISTS research_embeddings (
    span_id TEXT NOT NULL REFERENCES research_spans(span_id),
    model TEXT NOT NULL,
    vector TEXT NOT NULL,
    embedded_at TEXT NOT NULL,
    PRIMARY KEY(span_id, model)
);
-- Same transaction adapter and authorization locks as accounts/projects.
CREATE TABLE IF NOT EXISTS cited_research_runs (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    project_id TEXT,
    record JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS cited_research_runs_owner_idx ON cited_research_runs(owner_id);
CREATE INDEX IF NOT EXISTS cited_research_runs_project_idx ON cited_research_runs(project_id);

-- ==== 0015_platform_admin.sql ====
-- Dedicated platform operators. Neither users nor tenant roles imply platform privileges.
CREATE TABLE IF NOT EXISTS platform_admins (id TEXT PRIMARY KEY, record JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS platform_admin_sessions (
    id TEXT PRIMARY KEY, admin_id TEXT NOT NULL REFERENCES platform_admins(id), record JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS platform_admin_sessions_admin_idx ON platform_admin_sessions(admin_id);
CREATE TABLE IF NOT EXISTS platform_admin_audit (
    id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, action TEXT NOT NULL, target_id TEXT NOT NULL, record JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS platform_admin_audit_action_idx ON platform_admin_audit(action);
CREATE INDEX IF NOT EXISTS platform_admin_audit_target_idx ON platform_admin_audit(target_id);
CREATE TABLE IF NOT EXISTS platform_account_controls (
    id TEXT PRIMARY KEY REFERENCES users(id), record JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_admin_settings (id TEXT PRIMARY KEY, record JSONB NOT NULL);
-- A durable intent precedes any mutation in the separately owned research-job engine.
CREATE TABLE IF NOT EXISTS platform_admin_job_commands (
    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, status TEXT NOT NULL, record JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS platform_admin_job_commands_status_idx ON platform_admin_job_commands(status);

-- ==== 0016_ownership.sql ====
-- Separate ownership flows. Immutable normalized versions and raw-source references.
CREATE TABLE IF NOT EXISTS ownership_ingest_state (
    id TEXT PRIMARY KEY, accession TEXT NOT NULL, filer_cik BIGINT NOT NULL,
    issuer_cik BIGINT, kind TEXT NOT NULL, status TEXT NOT NULL,
    metadata TEXT NOT NULL, error TEXT, updated_at TEXT NOT NULL,
    last_successful_at TEXT, current_filing_id TEXT,
    UNIQUE(accession)
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

-- ==== 0017_launch.sql ====
-- One global campaign, individual accounts only. Never allocate by email submission or region.
CREATE TABLE IF NOT EXISTS launch_memberships (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL CHECK (status IN ('reserved', 'waitlisted')),
    position INTEGER NOT NULL CHECK (position > 0),
    record JSONB NOT NULL,
    UNIQUE (campaign_id, user_id),
    UNIQUE (campaign_id, position),
    CHECK ((status = 'reserved' AND position <= 20) OR (status = 'waitlisted' AND position > 20))
);
CREATE INDEX IF NOT EXISTS launch_memberships_campaign_idx ON launch_memberships(campaign_id, status);
CREATE TABLE IF NOT EXISTS demo_requests (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    caller_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('new', 'contacted', 'scheduled', 'completed')),
    created_at TEXT NOT NULL,
    record JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS demo_requests_status_idx ON demo_requests(status, created_at);
CREATE INDEX IF NOT EXISTS demo_requests_email_idx ON demo_requests(email, created_at);
CREATE INDEX IF NOT EXISTS demo_requests_caller_idx ON demo_requests(caller_hash, created_at);

-- ==== 0018_company_header_fields.sql ====
-- 0018: every field of the SEC submissions header on companies (addresses, LEI, owner org, flags,
-- insider-transaction markers, the former-names list with dates, and a JSON catch-all for keys the
-- parser has no column for); core_type on filings (the SEC's grouping of a form with its amendments).
ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS owner_org TEXT,
    ADD COLUMN IF NOT EXISTS lei TEXT,
    ADD COLUMN IF NOT EXISTS former_names_json TEXT,
    ADD COLUMN IF NOT EXISTS phone TEXT,
    ADD COLUMN IF NOT EXISTS investor_website TEXT,
    ADD COLUMN IF NOT EXISTS description TEXT,
    ADD COLUMN IF NOT EXISTS flags TEXT,
    ADD COLUMN IF NOT EXISTS insider_transaction_for_owner_exists BOOLEAN,
    ADD COLUMN IF NOT EXISTS insider_transaction_for_issuer_exists BOOLEAN,
    ADD COLUMN IF NOT EXISTS business_street1 TEXT,
    ADD COLUMN IF NOT EXISTS business_street2 TEXT,
    ADD COLUMN IF NOT EXISTS business_zip TEXT,
    ADD COLUMN IF NOT EXISTS business_state_description TEXT,
    ADD COLUMN IF NOT EXISTS business_country TEXT,
    ADD COLUMN IF NOT EXISTS business_country_code TEXT,
    ADD COLUMN IF NOT EXISTS business_is_foreign BOOLEAN,
    ADD COLUMN IF NOT EXISTS business_foreign_state_territory TEXT,
    ADD COLUMN IF NOT EXISTS mailing_street1 TEXT,
    ADD COLUMN IF NOT EXISTS mailing_street2 TEXT,
    ADD COLUMN IF NOT EXISTS mailing_city TEXT,
    ADD COLUMN IF NOT EXISTS mailing_state TEXT,
    ADD COLUMN IF NOT EXISTS mailing_zip TEXT,
    ADD COLUMN IF NOT EXISTS mailing_state_description TEXT,
    ADD COLUMN IF NOT EXISTS mailing_country TEXT,
    ADD COLUMN IF NOT EXISTS mailing_country_code TEXT,
    ADD COLUMN IF NOT EXISTS mailing_is_foreign BOOLEAN,
    ADD COLUMN IF NOT EXISTS mailing_foreign_state_territory TEXT,
    ADD COLUMN IF NOT EXISTS header_extra TEXT;
ALTER TABLE filings ADD COLUMN IF NOT EXISTS core_type TEXT;

-- ==== 0019_statement_segments.sql ====
-- 0019: the dimensional context of a statement line. A line's identity is its concept PLUS this:
-- the same tag broken out by product or share class is several lines, not one. Empty for a total.
ALTER TABLE statements ADD COLUMN IF NOT EXISTS segments TEXT;
CREATE INDEX IF NOT EXISTS statements_segments_idx ON statements (cik, statement) WHERE segments IS NOT NULL;

-- ==== 0020_ticker_current_owner.sql ====
-- 0020: which company currently owns a reused ticker symbol. A symbol gets reused after a company
-- delists; both companies keep a row, and is_current marks the one still filing so a ticker lookup
-- never lands on the dead company. Set by mark_current_owner at universe-build time.
ALTER TABLE tickers ADD COLUMN IF NOT EXISTS is_current BOOLEAN;
CREATE INDEX IF NOT EXISTS tickers_ticker_current_idx ON tickers (ticker) WHERE is_current;
