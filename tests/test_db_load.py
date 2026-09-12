import pytest

from filings_hub.db.database import Database
from filings_hub.db.load import load_full, load_incremental
from filings_hub.export.grid import build_grid
from filings_hub.testing import edgar_fixtures as fx

psycopg = pytest.importorskip("psycopg")


def test_full_and_incremental_load(built_lake, pg_url):
    counts = load_full(built_lake, pg_url)
    assert counts["companies"] == len(fx.COMPANIES) and counts["filings"] > 30 and counts["statements"] > 0
    assert counts["periods"] > 10 and counts["statement_checks"] > 0 and counts["run_log"] == 1
    db = Database(pg_url, built_lake)
    try:
        assert db.backend == "postgres"
        p = db.query(
            "SELECT period_label, statements_source, checks_passed FROM periods WHERE cik = ? AND period_label = 'Q2 2026'",
            [fx.APPLE],
        )
        assert p == [
            {
                "period_label": "Q2 2026",
                "statements_source": "facts_fallback",
                "checks_passed": True,
            }
        ]
        # arrays survive COPY
        items = db.query("SELECT items FROM filings WHERE accession = ?", [fx._acc(fx.APPLE, 2025, 77)])
        assert items == [{"items": ["2.02", "9.01"]}]
        # the same grid comes out of Postgres as out of DuckDB
        g_pg = build_grid(db, fx.APPLE, ["FY2025", "Q1 2026"]).to_dict()
        duck = Database("", built_lake)
        g_duck = build_grid(duck, fx.APPLE, ["FY2025", "Q1 2026"]).to_dict()
        duck.close()
        assert g_pg == g_duck
        # incremental: patch Apple only, then everything still adds up (no duplicates)
        before = db.query("SELECT count(*) AS n FROM statements")[0]["n"]
        counts2 = load_incremental(
            built_lake,
            pg_url,
            {fx.APPLE},
            accessions={fx.APPLE_10K_FY2025},
            fsds_quarters=["2026q1"],
        )
        assert counts2["statements"] > 0 and counts2["filings"] == len(fx.APPLE_FILINGS)
        after = db.query("SELECT count(*) AS n FROM statements")[0]["n"]
        assert before == after
        assert db.query("SELECT count(*) AS n FROM statement_checks WHERE cik = ?", [fx.APPLE])[0]["n"] > 0
        # migrations are recorded once
        assert db.query("SELECT count(*) AS n FROM schema_migrations")[0]["n"] == 1
        db.execute("SELECT 1")
    finally:
        db.close()
    assert load_full(built_lake, pg_url, all_periods=True)["statements"] > counts["statements"]


def test_duckdb_backend_on_empty_lake(tmp_path):
    from filings_hub.lake.storage import Storage

    db = Database("", Storage(str(tmp_path)))
    assert db.query("SELECT count(*) AS n FROM companies") == [{"n": 0}]
    assert db.query("SELECT count(*) AS n FROM periods_serving") == [{"n": 0}]
    db.close()
    with pytest.raises(ValueError):
        Database("")
