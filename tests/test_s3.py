"""The plan says "from empty S3": the whole pipeline against an S3 bucket, served by a moto mock.

DuckDB reads and writes the lake through the same fsspec filesystem the rest of the code uses, so no
`httpfs` extension is needed and any S3-compatible endpoint works.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from datetime import date

import pytest

pytest.importorskip("moto")
pytest.importorskip("s3fs")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def s3_endpoint():
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "moto.server", "-p", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.skip("moto server did not start")
    yield url
    proc.kill()


@pytest.fixture()
def s3_env(s3_endpoint, monkeypatch):
    from filings_hub.config import reset_settings_cache

    for k, v in {
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
        "AWS_ENDPOINT_URL": s3_endpoint,
        "AWS_REGION": "us-east-1",
        "AWS_DEFAULT_REGION": "us-east-1",
        "LAKE_ROOT": "s3://filings-test/lake",
        "DATABASE_URL": "",
        "SEC_USER_AGENT": "Test test@example.com",
    }.items():
        monkeypatch.setenv(k, v)
    reset_settings_cache()
    import boto3
    import s3fs

    fs = s3fs.S3FileSystem(
        key="test", secret="test", endpoint_url=s3_endpoint, client_kwargs={"region_name": "us-east-1"}
    )
    if not fs.exists("filings-test"):
        # S3's us-east-1 bucket creation omits LocationConstraint. s3fs versions differ in how
        # they encode it for custom endpoints, so create the mock bucket through the native API.
        boto3.client(
            "s3",
            endpoint_url=s3_endpoint,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        ).create_bucket(Bucket="filings-test")
    yield s3_endpoint
    reset_settings_cache()


def test_full_backfill_and_serving_from_empty_s3(s3_env):
    from filings_hub.db.database import Database
    from filings_hub.export.excel import export_excel
    from filings_hub.ingest.backfill import run_backfill
    from filings_hub.ingest.fsds import load_log
    from filings_hub.lake import layout
    from filings_hub.lake.storage import Storage
    from filings_hub.testing import edgar_fixtures as fx

    storage = Storage(os.environ["LAKE_ROOT"])
    assert storage.is_remote and storage.fs.protocol[0] in ("s3", "s3a")
    fx.seed_raw(storage, date(2026, 9, 11))
    assert storage.exists(layout.raw_submissions_zip(date(2026, 9, 11)))

    run = run_backfill(storage, workers=2, skip_download=True, load_db=False, today=date(2026, 9, 11))
    assert run.status == "ok", run.summary()

    # every layer landed in the bucket: hive partitions written by DuckDB and parquet written by pyarrow
    assert storage.glob(f"{layout.FACTS}/cik={fx.APPLE}/*.parquet")
    assert storage.glob(f"{layout.STATEMENTS}/cik={fx.APPLE}/fsds_*.parquet")
    assert storage.glob(f"{layout.STATEMENTS}/cik={fx.APPLE}/fallback_*.parquet")
    assert storage.exists(layout.PERIODS) and storage.exists(layout.COMPANIES)
    assert {r["table"] for r in load_log(storage)} == {"sub", "num", "pre", "tag"}

    # and it serves: the same queries and the same workbook as a local lake
    db = Database("", storage)
    try:
        # the periods of one company carry their statements source from that company's partition only;
        # the whole-table `periods_serving` view cannot say (it never scans the remote statements table)
        rows = db.query(
            f"SELECT period_label, statements_source, checks_passed FROM {db.periods_table_for(fx.APPLE)} "
            "WHERE cik = ? ORDER BY period_end DESC LIMIT 3",
            [fx.APPLE],
        )
        assert [r["period_label"] for r in rows] == ["Q3 2026", "Q2 2026", "Q1 2026"]
        assert rows[1]["statements_source"] == "facts_fallback" and rows[2]["statements_source"] == "fsds"
        data = export_excel(db, fx.APPLE, ["FY2025", "Q1 2026"])
        assert len(data) > 5000
        # a remote lake is read one company partition at a time, never by listing the whole table
        assert db.is_remote_lake
        assert storage.any_parquet_under(f"{layout.STATEMENTS}/cik={fx.APPLE}")
        assert not storage.any_parquet_under(f"{layout.STATEMENTS}/cik=424242")
        scoped = db.table("statements", fx.APPLE)
        assert scoped.startswith("read_parquet([") and f"cik={fx.APPLE}/*.parquet" in scoped
        assert db.table("statements", 424242) == "(SELECT * FROM _empty_statements)"
        assert db.table("filings", fx.APPLE) == "filings"  # partitioned by year: stays a view
        n = db.query(f"SELECT count(DISTINCT accession) AS n FROM {scoped}")[0]["n"]
        assert n >= 3
        assert db.query(f"SELECT count(*) AS n FROM {db.table('statements', 424242)}")[0]["n"] == 0
        unscoped = db.query(
            "SELECT statements_source FROM periods_serving WHERE cik = ? ORDER BY period_end DESC LIMIT 1", [fx.APPLE]
        )
        assert unscoped == [{"statements_source": None}]
    finally:
        db.close()

    # the API over the same bucket: company, periods with metrics, statements, cheap coverage
    from fastapi.testclient import TestClient

    from filings_hub.api.app import create_app
    from filings_hub.config import Settings

    settings = Settings(lake_root=storage.root, database_url="", api_key="k", sec_user_agent="", _env_file=None)
    app = create_app(settings)
    with TestClient(app) as c:
        h = {"X-API-Key": "k"}
        assert c.get("/companies/AAPL", headers=h).json()["latest_period"]["period_label"] == "Q3 2026"
        periods = c.get("/companies/AAPL/periods", headers=h).json()["periods"]
        assert any(p["metrics"]["revenue"] for p in periods)
        grid = c.get("/companies/AAPL/statements?periods=FY2025,Q1%202026", headers=h).json()
        assert [p["period_label"] for p in grid["periods"]] == ["FY2025", "Q1 2026"] and grid["statements"]
        cov = c.get("/coverage", headers=h).json()
        assert cov["totals"]["directory_companies"] >= 1 and cov["totals"]["filings_with_statements"] is None
        assert cov["forms"] == [] and "remote-lake" in cov["limitations"][0]
        assert c.get("/quality/failed", headers=h).status_code in (401, 403)  # administrator only
    app.state.db.close()

    # a second backfill over the same bucket is a no-op for the data, exactly as on local disk
    duck_count = lambda: Database("", storage).query("SELECT count(*) AS n FROM statements")[0]["n"]  # noqa: E731
    before = duck_count()
    assert run_backfill(storage, workers=1, skip_download=True, load_db=False, today=date(2026, 9, 11)).status == "ok"
    assert duck_count() == before


def test_refresh_against_s3(s3_env):
    """The daily path writes the raw daily index, per-company API responses and per-CIK partitions."""
    from filings_hub.ingest import refresh as R
    from filings_hub.ingest.backfill import run_backfill
    from filings_hub.lake import layout
    from filings_hub.lake.storage import Storage
    from filings_hub.testing import edgar_fixtures as fx
    from tests.test_refresh import FakeEdgar

    storage = Storage("s3://filings-test/lake-refresh")
    fx.seed_raw(storage, date(2026, 9, 11))
    assert run_backfill(storage, workers=1, skip_download=True, load_db=False, today=date(2026, 9, 11)).status == "ok"
    monday = date(2026, 11, 2)
    fake = FakeEdgar({monday: [(fx.APPLE, "10-K", fx.APPLE_10K_FY2026)]})
    run = R.run_refresh(storage, fake, today=date(2026, 11, 3), index_date=monday, load_db=False, alert=False)
    assert run.status == "ok", run.summary()
    assert storage.exists(layout.raw_daily_index(monday))
    assert storage.exists(layout.raw_api_companyfacts(date(2026, 11, 3), fx.APPLE))
    labels = {r["period_label"] for r in storage.read_parquet(layout.PERIODS).to_pylist() if r["cik"] == fx.APPLE}
    assert "FY2026" in labels


def test_remote_lake_serves_small_tables_from_local_copies(s3_env):
    """Over object storage the whole-universe tables are copied next to the process and re-synced
    when the remote file changes, so search does not pull them from the bucket per query."""
    from filings_hub.db.database import LOCAL_TABLES, Database
    from filings_hub.ingest.backfill import run_backfill
    from filings_hub.lake import layout
    from filings_hub.lake.storage import Storage
    from filings_hub.testing import edgar_fixtures as fx

    storage = Storage(os.environ["LAKE_ROOT"])
    if not storage.exists(layout.COMPANIES):
        fx.seed_raw(storage, date(2026, 9, 11))
        assert (
            run_backfill(storage, workers=1, skip_download=True, load_db=False, today=date(2026, 9, 11)).status == "ok"
        )

    db = Database("", storage)
    try:
        assert db._local_dir and sorted(os.listdir(db._local_dir)) == sorted(f"{n}.parquet" for n in LOCAL_TABLES)
        assert db.query("SELECT count(*) AS n FROM companies")[0]["n"] == len(fx.COMPANIES)
        assert db.maybe_resync(ttl=0) is False  # nothing changed remotely

        # a refresh rewrites companies.parquet in the bucket: the next check picks it up
        t = storage.read_parquet(layout.COMPANIES)
        storage.write_parquet(layout.COMPANIES, t.slice(0, 1))
        assert db.maybe_resync(ttl=0) is True
        assert db.query("SELECT count(*) AS n FROM companies")[0]["n"] == 1
        assert db.maybe_resync(ttl=3600) is False  # within the TTL no remote round trip is made
        storage.write_parquet(layout.COMPANIES, t)  # restore for later tests in the module
        local_dir = db._local_dir
    finally:
        db.close()
    assert not os.path.exists(local_dir)

    local = Database("", Storage(str(__import__("tempfile").mkdtemp())))
    assert local._local_dir is None  # local lakes read in place
    local.close()


def test_remote_empty_views_discover_backfill_without_restarting(s3_env):
    from filings_hub.db.database import MISSING_VIEW_TTL, Database
    from filings_hub.lake.storage import Storage
    from tests.test_database_recovery import populate_missing

    storage = Storage("s3://filings-test/start-before-backfill")
    db = Database("", storage)
    try:
        assert db.query("SELECT count(*) AS n FROM filings") == [{"n": 0}]
        populate_missing(Storage(storage.root), db)
        db._missing_checked -= MISSING_VIEW_TTL + 1
        assert db.query("SELECT count(*) AS n FROM filings") == [{"n": 1}]
        # per-company tables are read per partition on a remote lake, never as a whole view
        assert db.query("SELECT count(*) AS n FROM statements") == [{"n": 0}]
        assert db.query("SELECT count(*) AS n FROM periods_serving") == [{"n": 1}]
        assert db._local_dir and not db._missing_views
        db.refresh_views()
        views = db.duck.fetch_dicts("SELECT sql FROM duckdb_views() WHERE view_name = 'companies'")
        assert db._local_dir in views[0]["sql"]
        assert db.maybe_resync(ttl=3600) is False
    finally:
        db.close()


@pytest.mark.parametrize("local_cache", [True, False])
def test_remote_lake_reads_company_partitions_written_by_an_external_writer(s3_env, local_cache):
    """A remote lake never binds a whole-table view over a per-company table (that lists every object
    in the table); it reads one company's partition through `Database.table()`, and a partition another
    process writes later becomes visible once the bounded partition check expires."""
    import boto3
    import pyarrow as pa
    import pyarrow.parquet as pq

    from filings_hub.db.database import MISSING_VIEW_TTL, Database
    from filings_hub.lake.storage import Storage
    from tests.test_database_recovery import populate_missing

    prefix = f"external-writer-{local_cache}"
    storage = Storage(f"s3://filings-test/{prefix}")
    db = Database("", storage, local_cache=local_cache)
    try:
        populate_missing(storage, db)
        assert db.maybe_resync(ttl=0)
        assert "statements" not in db._missing_views and "filings" not in db._missing_views
        assert db.query("SELECT count(*) AS n FROM filings") == [{"n": 1}]  # year-partitioned: a whole view
        assert db.query("SELECT count(*) AS n FROM statements") == [{"n": 0}]  # per company only
        assert db.query(f"SELECT count(*) AS n FROM {db.table('statements', 7)}") == [{"n": 0}]
        buf = pa.BufferOutputStream()
        pq.write_table(pa.Table.from_pylist([{"cik": 7}], schema=db._empty_table_schemas()["statements"]), buf)
        boto3.client(
            "s3",
            endpoint_url=s3_env,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        ).put_object(
            Bucket="filings-test", Key=f"{prefix}/statements/cik=7/one.parquet", Body=buf.getvalue().to_pybytes()
        )
        assert db.query(f"SELECT count(*) AS n FROM {db.table('statements', 7)}") == [{"n": 0}]  # probe is bounded
        db._partitions[("statements", 7)] = (db._partitions[("statements", 7)][0] - MISSING_VIEW_TTL - 1, False)
        db._remote_checked -= 601
        assert db.query(f"SELECT count(*) AS n FROM {db.table('statements', 7)}") == [{"n": 1}]
        assert db.query(f"SELECT count(*) AS n FROM {db.periods_table_for(7)}") == [{"n": 0}]
    finally:
        db.close()
