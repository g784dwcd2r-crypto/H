from filings_hub.ingest import metrics
from filings_hub.lake import layout
from filings_hub.testing import edgar_fixtures as fx


def test_period_metrics_read_the_as_reported_statements(db):
    m = metrics.period_metrics(db.query, fx.APPLE)
    fy25 = m[fx.APPLE_10K_FY2025] if hasattr(fx, "APPLE_10K_FY2025") else None
    if fy25 is None:  # find the FY2025 annual filing through the periods table
        row = db.query(
            f"SELECT results_accession FROM {db.periods_table} WHERE cik = ? AND period_label = 'FY2025'", [fx.APPLE]
        )[0]
        fy25 = m[row["results_accession"]]
    rev = db.query(
        "SELECT value FROM statements WHERE cik = ? AND accession = ? AND statement = 'IS' AND is_primary_period "
        "AND concept = 'RevenueFromContractWithCustomerExcludingAssessedTax'",
        [fx.APPLE, next(a for a, v in m.items() if v is fy25)],
    )
    assert fy25["revenue"] == rev[0]["value"] and fy25["revenue"] > 0
    assert fy25["net_income"] and fy25["eps_diluted"] and fy25["total_assets"] and fy25["operating_cash_flow"]
    assert set(fy25) == set(metrics.METRIC_NAMES)


def test_company_metrics_table_is_built_by_the_backfill(built_lake):
    t = built_lake.read_parquet(layout.COMPANY_METRICS)
    rows = {r["cik"]: r for r in t.to_pylist()}
    assert rows[fx.APPLE]["period_label"] == "FY2025" and rows[fx.APPLE]["revenue"] > 0
    assert rows[fx.APPLE]["total_assets"] > 0


def test_upsert_company_metrics_touches_only_the_given_companies(lake_copy):
    before = {r["cik"]: r for r in lake_copy.read_parquet(layout.COMPANY_METRICS).to_pylist()}
    n = metrics.upsert_company_metrics(lake_copy, [fx.APPLE])
    after = {r["cik"]: r for r in lake_copy.read_parquet(layout.COMPANY_METRICS).to_pylist()}
    assert n == 1 and after == before
    assert metrics.upsert_company_metrics(lake_copy, []) == 0
