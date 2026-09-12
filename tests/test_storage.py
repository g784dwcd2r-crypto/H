import pyarrow as pa

from filings_hub.lake.storage import Storage


def test_local_storage_roundtrip(tmp_path):
    st = Storage(str(tmp_path / "lake"))
    assert not st.is_remote and st.exists("") and st.ls("nope") == []
    st.write_text("a/b/c.txt", "hello")
    assert st.read_text("a/b/c.txt") == "hello" and st.size("a/b/c.txt") == 5
    assert st.ls("a") == ["a/b"] and st.glob("a/**/*.txt") == ["a/b/c.txt"]
    t = pa.table({"x": [1, 2]})
    st.write_parquet("p/q.parquet", t)
    assert st.read_parquet("p/q.parquet").equals(t)
    st.replace_dir_with_parquet("p", pa.table({"x": [3]}))
    assert st.ls("p") == ["p/part-0.parquet"]
    with st.open("a/b/c.txt", "rb") as f:
        assert f.read() == b"hello"
    with st.local_copy("a/b/c.txt") as p:
        assert p.read_text() == "hello"
    st.delete("a")
    assert not st.exists("a")
    st.delete("a")  # no-op
    assert st.duck_path("x") == st.full("x")


def test_view_skips_empty_directories(tmp_path):
    """An empty partition directory must degrade to "no data", not make every later query raise.

    `build_fsds_quarter` creates statements/ and statement_checks/ before it knows whether either will
    get rows, so a quarter in which no filing has an applicable arithmetic check leaves an empty
    statement_checks/ behind. Treating that as present made DuckDB raise IOException on every query.
    """
    import duckdb
    import pytest

    from filings_hub.lake.duck import Duck

    st = Storage(str(tmp_path / "lake"))
    st.mkdirs("statement_checks")  # exists, but holds no parquet
    st.write_parquet("statements/cik=1/part-0.parquet", pa.table({"cik": [1]}))

    duck = Duck(st)
    try:
        assert duck.view("statement_checks", "statement_checks/*/*.parquet") is False
        assert duck.view("statements", "statements/*/*.parquet") is True
        assert duck.view("periods", "periods/periods.parquet", hive=False) is False
        views = duck.create_views()
        assert views["statement_checks"] is False and views["statements"] is True
        with pytest.raises(duckdb.CatalogException):
            duck.sql("SELECT * FROM statement_checks")  # the view was never created
        assert duck.fetch_dicts("SELECT count(*) AS n FROM statements")[0]["n"] == 1
    finally:
        duck.close()


def test_database_survives_an_empty_partition_directory(tmp_path):
    """The serving layer must open against such a lake instead of failing at construction."""
    from filings_hub.db.database import Database

    st = Storage(str(tmp_path / "lake"))
    st.mkdirs("statement_checks")
    st.mkdirs("facts")
    db = Database("", st)
    try:
        assert db.query("SELECT count(*) AS n FROM statement_checks") == [{"n": 0}]
    finally:
        db.close()


def test_api_answers_on_an_empty_lake(tmp_path):
    """The API is expected to be up while `filings-hub backfill` runs for hours, so every endpoint
    must return an empty result rather than a 500 with a DuckDB binder error."""
    from fastapi.testclient import TestClient

    from filings_hub.api.app import create_app
    from filings_hub.config import Settings

    settings = Settings(
        lake_root=str(tmp_path / "empty"),
        database_url="",
        api_key="",
        api_rate_limit_per_minute=10000,
        _env_file=None,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        assert c.get("/health").json()["last_run"] is None
        assert c.get("/search?q=apple").json()["results"] == []
        assert c.get("/companies/320193").status_code == 404
        assert c.get("/companies/AAPL").status_code == 404
        assert c.get("/companies/320193/periods").json()["periods"] == []
        assert c.get("/companies/320193/filings").json()["filings"] == []
        assert c.get("/companies/320193/statements").status_code == 404
        assert c.get("/companies/320193/facts?concept=Assets").json()["facts"] == []
        m = c.get("/metrics").json()
        assert m["totals"]["companies"] == 0 and m["runs"] == [] and m["filings_per_day"] == []
        assert c.get("/quality/failed").json() == {"total": 0, "limit": 100, "offset": 0, "failed": []}
    app.state.db.close()


def test_concurrent_reads_are_safe(built_lake):
    """One DuckDB connection is not safe for concurrent use, and the API serves sync endpoints from a
    threadpool (a single company page fires three requests at once). Without serialisation `execute` on
    one thread replaces the pending result of another, pairing one query's columns with another's rows.
    """
    from collections import Counter
    from concurrent.futures import ThreadPoolExecutor

    from filings_hub.db.database import Database
    from filings_hub.testing import edgar_fixtures as fx

    db = Database("", built_lake)
    queries = [
        ("SELECT * FROM companies WHERE cik = ?", [fx.APPLE], 1),
        ("SELECT * FROM periods_serving WHERE cik = ? ORDER BY period_end DESC", [fx.APPLE], 8),
        ("SELECT * FROM filings WHERE cik = ? ORDER BY filed_date", [fx.APPLE], len(fx.APPLE_FILINGS)),
        (
            "SELECT * FROM statements WHERE accession = ? AND statement = 'BS' AND is_primary_period",
            [fx.APPLE_10K_FY2025],
            8,
        ),
    ]

    def run(i: int) -> str:
        sql, params, expected = queries[i % len(queries)]
        try:
            rows = db.query(sql, params)
        except Exception as e:
            return f"{type(e).__name__}"
        if len(rows) != expected:
            return f"wrong row count {len(rows)} != {expected}"
        # every row must carry the columns the query asked for, not another query's
        if any("cik" not in r for r in rows):
            return "column/row mismatch"
        return "ok"

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = Counter(pool.map(run, range(400)))
    finally:
        db.close()
    assert results == Counter({"ok": 400}), results
