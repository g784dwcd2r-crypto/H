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
