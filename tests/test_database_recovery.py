import pyarrow as pa

from filings_hub.db.database import LOCAL_TABLES, MISSING_VIEW_TTL, PARTITIONED_TABLES, Database
from filings_hub.lake.storage import Storage


def populate_missing(storage, db):
    for name, schema in db._empty_table_schemas().items():
        rel = LOCAL_TABLES.get(name)
        if rel is None:
            rel = "run_log/one.parquet" if name == "run_log" else f"{PARTITIONED_TABLES[name]}/part=1/one.parquet"
        storage.write_parquet(rel, pa.Table.from_pylist([{}], schema=schema))


def test_local_startup_empty_views_discover_data_during_queries(tmp_path):
    storage = Storage(str(tmp_path))
    db = Database("", storage)
    try:
        assert db.query("SELECT count(*) AS n FROM statements") == [{"n": 0}]
        populate_missing(storage, db)
        assert db.query("SELECT count(*) AS n FROM statements") == [{"n": 0}]  # probes stay bounded
        db._missing_checked -= MISSING_VIEW_TTL + 1
        for name in db._empty_table_schemas():
            assert db.query(f"SELECT count(*) AS n FROM {name}") == [{"n": 1}]
        assert db.query("SELECT count(*) AS n FROM periods_serving") == [{"n": 1}]
        assert not db._missing_views
        assert db.maybe_resync(ttl=0) is False
    finally:
        db.close()
