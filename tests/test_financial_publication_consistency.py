"""A financial read and a cooperating publisher cannot straddle serving publications."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pyarrow as pa
import pytest

from filings_hub.db import load
from filings_hub.db.database import Database
from filings_hub.lake import layout
from filings_hub.platform.financials import financial_snapshot
from filings_hub.testing import edgar_fixtures as fx


@pytest.mark.parametrize("kind", ["full", "incremental"])
def test_financial_read_holds_publication_until_complete(lake_copy, pg_url, monkeypatch, kind):
    load.load_full(lake_copy, pg_url)
    database = Database(pg_url, lake_copy)
    original = financial_snapshot(database, fx.APPLE)
    companies = lake_copy.read_parquet(layout.COMPANIES)
    updated = [
        {**row, "name": "Newly published company"} if row["cik"] == fx.APPLE else row for row in companies.to_pylist()
    ]
    lake_copy.write_parquet(layout.COMPANIES, pa.Table.from_pylist(updated, schema=companies.schema))
    attempting_lock, acquired_lock = Event(), Event()
    original_lock = load._publication_lock

    def observed_lock(conn):
        attempting_lock.set()
        original_lock(conn)
        acquired_lock.set()

    monkeypatch.setattr(load, "_publication_lock", observed_lock)

    def publish():
        if kind == "full":
            return load.load_full(lake_copy, pg_url)
        return load.load_incremental(lake_copy, pg_url, {fx.APPLE})

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with database.read_snapshot() as reader:
                assert financial_snapshot(reader, fx.APPLE) == original
                future = pool.submit(publish)
                assert attempting_lock.wait(timeout=10), "publisher did not reach its lock"
                # The attempt event is set immediately before the real blocking lock acquisition.
                assert not acquired_lock.wait(timeout=0.15), "publisher bypassed the active financial read"
                assert financial_snapshot(reader, fx.APPLE) == original
            assert future.result(timeout=30)["companies"] > 0
            assert acquired_lock.is_set()
        next_read = financial_snapshot(database, fx.APPLE)
        assert next_read["grid"]["company_name"] == "Newly published company"
        assert next_read["snapshot_id"] != original["snapshot_id"]
    finally:
        database.close()
