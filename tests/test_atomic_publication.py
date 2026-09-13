import psycopg
import pytest

from filings_hub.db import load
from filings_hub.testing import edgar_fixtures as fx


@pytest.mark.parametrize("kind", ["full", "incremental"])
def test_failed_publication_rolls_back_all_tables_and_manifest(built_lake, pg_url, monkeypatch, kind):
    load.load_full(built_lake, pg_url)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute("UPDATE companies SET name = 'Previous published company' WHERE cik = %s", (fx.APPLE,))
        previous = conn.execute("SELECT count(*) FROM serving_publications").fetchone()[0]
        previous_filings = conn.execute("SELECT count(*) FROM filings").fetchone()[0]
    original = load.copy_table

    def fail_after_company_update(conn, table, arrow):
        if table == "periods":
            raise RuntimeError("injected failure after companies changed")
        return original(conn, table, arrow)

    monkeypatch.setattr(load, "copy_table", fail_after_company_update)
    with pytest.raises(RuntimeError, match="injected failure"):
        if kind == "full":
            load.load_full(built_lake, pg_url)
        else:
            load.load_incremental(built_lake, pg_url, {fx.APPLE})
    with psycopg.connect(pg_url) as conn:
        assert (
            conn.execute("SELECT name FROM companies WHERE cik = %s", (fx.APPLE,)).fetchone()[0]
            == "Previous published company"
        )
        assert conn.execute("SELECT count(*) FROM filings").fetchone()[0] == previous_filings
        assert conn.execute("SELECT count(*) FROM serving_publications").fetchone()[0] == previous


def test_publication_records_only_committed_counts(built_lake, pg_url):
    counts = load.load_full(built_lake, pg_url)
    with psycopg.connect(pg_url) as conn:
        kind, stored, all_periods = conn.execute(
            "SELECT kind, counts, all_periods FROM serving_publications ORDER BY published_at DESC LIMIT 1"
        ).fetchone()
    assert kind == "full" and stored == counts and all_periods


def test_missing_source_inventory_cannot_publish_a_hybrid(lake_copy, pg_url):
    load.load_full(lake_copy, pg_url)
    with psycopg.connect(pg_url) as conn:
        before = conn.execute("SELECT count(*) FROM serving_publications").fetchone()[0]
        periods = conn.execute("SELECT count(*) FROM periods").fetchone()[0]
    lake_copy.delete("statements")
    for publish in (
        lambda: load.load_full(lake_copy, pg_url),
        lambda: load.load_incremental(lake_copy, pg_url, {fx.APPLE}),
    ):
        with pytest.raises(ValueError, match="Incomplete serving source inventory"):
            publish()
    with psycopg.connect(pg_url) as conn:
        assert conn.execute("SELECT count(*) FROM serving_publications").fetchone()[0] == before
        assert conn.execute("SELECT count(*) FROM periods").fetchone()[0] == periods
