import pyarrow as pa

from filings_hub.db.database import Database
from filings_hub.export.grid import build_grid
from filings_hub.testing import edgar_fixtures as fx


def test_a_shared_accession_cannot_mix_issuer_values_or_duplicate_period_columns(lake_copy):
    db = Database("", lake_copy)
    try:
        baseline = build_grid(db, fx.APPLE, limit=60).to_dict()
        filings = db.duck.fetch_arrow("SELECT * FROM filings")
        original = next(r for r in filings.to_pylist() if r["accession"] == fx.APPLE_10K_FY2025)
        cofiling = {**original, "cik": 999999, "filing_index_url": "https://example.test/wrong-issuer"}
        db.duck.register(
            "_cofilings", pa.concat_tables([filings, pa.Table.from_pylist([cofiling], schema=filings.schema)])
        )
        db.duck.sql("CREATE OR REPLACE VIEW filings AS SELECT * FROM _cofilings")
        statements = db.duck.fetch_arrow("SELECT * FROM statements")
        competing = [
            {
                **r,
                "cik": 999999,
                "checks_passed": False,
                "value": 999999999999,
                "value_presented": 999999999999,
                "label": "Other issuer",
            }
            for r in statements.to_pylist()
            if r["accession"] == fx.APPLE_10K_FY2025
        ]
        db.duck.register(
            "_costatements", pa.concat_tables([statements, pa.Table.from_pylist(competing, schema=statements.schema)])
        )
        db.duck.sql("CREATE OR REPLACE VIEW statements AS SELECT * FROM _costatements")
        assert build_grid(db, fx.APPLE, limit=60).to_dict() == baseline
    finally:
        db.close()


def test_cofiler_quality_failure_survives_full_and_incremental_publication(lake_copy, pg_url):
    from filings_hub.db.load import load_full, load_incremental
    from filings_hub.lake import layout

    path = lake_copy.glob(f"{layout.statement_checks_cik_dir(fx.APPLE)}/*.parquet")[0]
    checks = lake_copy.read_parquet(path)
    original = checks.to_pylist()[0]
    cofiling = {**original, "cik": 999999, "passed": False, "detail": "Other issuer failed"}
    lake_copy.write_parquet(
        f"{layout.statement_checks_cik_dir(999999)}/cofiler.parquet",
        pa.Table.from_pylist([cofiling], schema=checks.schema),
    )
    for publish in (
        lambda: load_full(lake_copy, pg_url),
        lambda: load_incremental(lake_copy, pg_url, {fx.APPLE}, accessions={original["accession"]}),
    ):
        publish()
        db = Database(pg_url, lake_copy)
        try:
            rows = db.query(
                "SELECT cik, passed FROM statement_checks WHERE accession = ? "
                "AND statement = ? AND check_name = ? ORDER BY cik",
                [original["accession"], original["statement"], original["check_name"]],
            )
            assert rows == [{"cik": fx.APPLE, "passed": original["passed"]}, {"cik": 999999, "passed": False}]
        finally:
            db.close()
