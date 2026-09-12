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
        "LAKE_ROOT": "s3://filings-test/lake",
        "DATABASE_URL": "",
        "SEC_USER_AGENT": "Test test@example.com",
    }.items():
        monkeypatch.setenv(k, v)
    reset_settings_cache()
    import s3fs

    fs = s3fs.S3FileSystem(key="test", secret="test", endpoint_url=s3_endpoint)
    if not fs.exists("filings-test"):
        fs.mkdir("filings-test")
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
        rows = db.query(
            "SELECT period_label, statements_source, checks_passed FROM periods_serving "
            "WHERE cik = ? ORDER BY period_end DESC LIMIT 3",
            [fx.APPLE],
        )
        assert [r["period_label"] for r in rows] == ["Q3 2026", "Q2 2026", "Q1 2026"]
        assert rows[1]["statements_source"] == "facts_fallback" and rows[2]["statements_source"] == "fsds"
        data = export_excel(db, fx.APPLE, ["FY2025", "Q1 2026"])
        assert len(data) > 5000
    finally:
        db.close()

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
