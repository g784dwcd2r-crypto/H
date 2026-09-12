from __future__ import annotations

import os
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from filings_hub.ingest.backfill import run_backfill
from filings_hub.lake.storage import Storage
from filings_hub.testing.edgar_fixtures import seed_raw

TODAY = date(2026, 9, 11)


@pytest.fixture(scope="session")
def built_lake(tmp_path_factory: pytest.TempPathFactory) -> Storage:
    """A lake seeded with the synthetic EDGAR fixtures and fully built (shared, read-only)."""
    root = tmp_path_factory.mktemp("lake")
    storage = Storage(str(root))
    seed_raw(storage, TODAY)
    run = run_backfill(storage, workers=1, skip_download=True, load_db=False, today=TODAY)
    assert run.status == "ok", run.summary()
    return storage


@pytest.fixture()
def lake_copy(built_lake: Storage, tmp_path: Path) -> Storage:
    """A private copy of the built lake for tests that mutate it."""
    dst = tmp_path / "lake"
    shutil.copytree(built_lake.root, dst)
    return Storage(str(dst))


@pytest.fixture()
def db(built_lake: Storage):
    from filings_hub.db.database import Database

    database = Database("", built_lake)
    yield database
    database.close()


# ---------------------------------------------------------------------------------------------
# Throwaway Postgres cluster for loader tests (skipped when no binaries and no TEST_DATABASE_URL)
# ---------------------------------------------------------------------------------------------
def _pg_bin(name: str) -> str | None:
    p = shutil.which(name)
    if p:
        return p
    for d in sorted(Path("/usr/lib/postgresql").glob("*/bin"), reverse=True):
        if (d / name).exists():
            return str(d / name)
    return None


@pytest.fixture(scope="session")
def pg_url(tmp_path_factory: pytest.TempPathFactory):
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return
    initdb, pg_ctl, psql = _pg_bin("initdb"), _pg_bin("pg_ctl"), _pg_bin("psql")
    if not (initdb and pg_ctl and psql):
        pytest.skip("no Postgres binaries and TEST_DATABASE_URL not set")
    import tempfile

    base = Path(tempfile.mkdtemp(prefix="filings-hub-pg-"))  # /tmp is traversable by the postgres user
    data, sock = base / "data", base / "sock"
    sock.mkdir()
    as_root = os.geteuid() == 0

    def run(cmd: str) -> subprocess.CompletedProcess:
        if as_root:
            return subprocess.run(["su", "postgres", "-c", cmd], capture_output=True, text=True, check=False)
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)

    if as_root:
        subprocess.run(["chown", "-R", "postgres:postgres", str(base)], check=True)
        subprocess.run(["chmod", "755", str(base)], check=True)
    port = 54329
    r = run(f"{initdb} -D {data} -U test --auth=trust >/dev/null")
    if r.returncode != 0:
        pytest.skip(f"initdb failed: {r.stderr[-300:]}")
    r = run(f"{pg_ctl} -D {data} -o \"-p {port} -k {sock} -c listen_addresses=''\" -l {base}/pg.log -w start")
    if r.returncode != 0:
        pytest.skip(f"pg_ctl start failed: {r.stderr[-300:]}")
    run(f"{psql} -h {sock} -p {port} -U test -d postgres -c 'CREATE DATABASE filings_test'")
    try:
        yield f"postgresql://test@/filings_test?host={sock}&port={port}"
    finally:
        run(f"{pg_ctl} -D {data} -m immediate stop")
        shutil.rmtree(base, ignore_errors=True)
