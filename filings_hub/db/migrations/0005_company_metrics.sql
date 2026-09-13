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
