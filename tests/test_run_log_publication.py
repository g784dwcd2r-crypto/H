from datetime import date

import psycopg

from filings_hub.coverage import coverage_summary
from filings_hub.db.database import Database
from filings_hub.ingest import refresh as R
from filings_hub.ingest.backfill import run_backfill
from filings_hub.lake import layout
from filings_hub.testing import edgar_fixtures as fx
from tests.test_refresh import FakeEdgar


def test_backfill_and_refresh_publish_the_current_finalized_run(lake_copy, pg_url):
    # A fresh serving database must show this backfill immediately, without waiting for another run.
    backfill = run_backfill(lake_copy, workers=1, skip_download=True, today=date(2026, 9, 11), database_url=pg_url)
    assert backfill.status == "ok" and backfill.db_loaded
    db = Database(pg_url, lake_copy)
    try:
        stored = db.query("SELECT status, finished_at, db_loaded FROM run_log WHERE run_id = ?", [backfill.run_id])
        assert stored == [{"status": "ok", "finished_at": backfill.finished_at, "db_loaded": True}]
        assert coverage_summary(db)["last_completed_ingestion"] == backfill.finished_at
        day = date(2026, 11, 2)
        refresh = R.run_refresh(
            lake_copy,
            FakeEdgar({day: [(fx.APPLE, "10-K", fx.APPLE_10K_FY2026)]}),
            today=date(2026, 11, 3),
            index_date=day,
            database_url=pg_url,
            alert=False,
        )
        assert refresh.status == "ok" and refresh.db_loaded
        stored = db.query("SELECT status, finished_at, db_loaded FROM run_log WHERE run_id = ?", [refresh.run_id])
        assert stored == [{"status": "ok", "finished_at": refresh.finished_at, "db_loaded": True}]
        assert coverage_summary(db)["last_completed_ingestion"] == refresh.finished_at
    finally:
        db.close()


def test_failed_refresh_publishes_failure_before_the_data_load(lake_copy, pg_url):
    class Broken(FakeEdgar):
        def fetch_daily_index(self, day):
            raise RuntimeError("upstream unavailable")

    run = R.run_refresh(lake_copy, Broken({}), today=date(2026, 11, 3), database_url=pg_url, alert=False)
    assert run.status == "failed" and not run.db_loaded
    with psycopg.connect(pg_url) as conn:
        stored = conn.execute(
            "SELECT status, error, db_loaded FROM run_log WHERE run_id = %s", (run.run_id,)
        ).fetchone()
    assert stored == ("failed", "RuntimeError: upstream unavailable", False)


def test_log_publication_is_idempotent_and_failure_is_retained_in_the_lake(lake_copy, pg_url, monkeypatch):
    from filings_hub.db import run_log

    run = R.RunLog().finish("ok")
    R.write_run_log(lake_copy, run, pg_url)
    R.write_run_log(lake_copy, run, pg_url)
    with psycopg.connect(pg_url) as conn:
        assert conn.execute("SELECT count(*) FROM run_log WHERE run_id = %s", (run.run_id,)).fetchone() == (1,)

    def fail(*args):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(run_log, "publish_run_log", fail)
    R.write_run_log(lake_copy, run, pg_url)
    assert run.status == "failed" and "publication failed" in run.error
    records = [
        row for rel in lake_copy.glob(f"{layout.RUN_LOG}/*.parquet") for row in lake_copy.read_parquet(rel).to_pylist()
    ]
    assert next(row for row in records if row["run_id"] == run.run_id)["status"] == "failed"
