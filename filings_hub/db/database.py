"""One query interface over two backends.

* Postgres (`DATABASE_URL=postgresql://...`): the serving tables loaded by `db.load`.
* DuckDB over the lake (no DATABASE_URL): views over the same tables straight from Parquet, so the API,
  exporter and tests run without a database.

SQL is written once with `?` placeholders (converted to `%s` for psycopg).
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from collections.abc import Sequence
from typing import Any

import pyarrow as pa

from filings_hub.lake import layout
from filings_hub.lake.duck import Duck
from filings_hub.lake.storage import Storage

log = logging.getLogger(__name__)

# Serving view of periods: adds statements_source / checks_passed from the statements table.
PERIODS_SERVING_SQL = """
SELECT p.*, s.statements_source, s.checks_passed
FROM periods p
LEFT JOIN (
    SELECT accession,
           CASE WHEN bool_or(source = 'fsds') THEN 'fsds' ELSE 'facts_fallback' END AS statements_source,
           bool_and(checks_passed) AS checks_passed
    FROM statements
    WHERE statement IN ('IS', 'BS', 'CF') AND is_primary_period
    GROUP BY accession
) s ON s.accession = p.results_accession
"""


# Whole-universe tables every request touches. Over a remote lake (R2/S3) they are copied to local
# disk once and re-checked every `LOCAL_CACHE_TTL` seconds, so a search reads a local file rather than
# pulling tens of megabytes from object storage per query. Per-company tables stay remote: one
# partition per request is a single small read.
LOCAL_TABLES = {
    "companies": layout.COMPANIES,
    "tickers": layout.TICKERS,
    "periods": layout.PERIODS,
    "company_metrics": layout.COMPANY_METRICS,
}
LOCAL_CACHE_TTL = 600.0


class Database:
    def __init__(self, url: str | None = None, storage: Storage | None = None, local_cache: bool = True):
        self.url = url or ""
        self.storage = storage
        self._local_dir: str | None = None
        self._local_stamp: dict[str, tuple[int, str]] = {}
        self._local_checked = 0.0
        if self.url.startswith(("postgresql://", "postgres://")):
            self.backend = "postgres"
            import psycopg

            self._pg = psycopg
            self.conn = psycopg.connect(self.url, autocommit=True)
        else:
            if storage is None:
                raise ValueError("DuckDB backend needs a lake Storage")
            self.backend = "duckdb"
            self.duck = Duck(storage)
            if local_cache and storage.is_remote:
                self._local_dir = tempfile.mkdtemp(prefix="filings-hub-cache-")
            self._prepare_duck_views()

    # -- local copies of the small whole-universe tables (remote lakes only) -----------------------
    def _remote_stamp(self, rel: str) -> tuple[int, str] | None:
        assert self.storage is not None
        try:
            info = self.storage.fs.info(self.storage.full(rel))
        except FileNotFoundError:
            return None
        return int(info.get("size") or 0), str(info.get("LastModified") or info.get("mtime") or "")

    def _localise(self, name: str, rel: str) -> bool:
        """Copy `rel` next to the process and point the view at it. False when the table is absent."""
        assert self.storage is not None and self._local_dir is not None
        stamp = self._remote_stamp(rel)
        if stamp is None:
            return False
        if self._local_stamp.get(name) != stamp:
            path = os.path.join(self._local_dir, f"{name}.parquet")
            tmp = path + ".part"
            with self.storage.open(rel, "rb") as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.replace(tmp, path)
            self._local_stamp[name] = stamp
            self.duck.sql(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{path}')")
            log.info("local copy of %s refreshed (%d bytes)", rel, stamp[0])
        return True

    def maybe_resync(self, ttl: float = LOCAL_CACHE_TTL) -> bool:
        """Re-check the remote small tables at most every `ttl` seconds; True when something changed."""
        if self._local_dir is None or time.monotonic() - self._local_checked < ttl:
            return False
        self._local_checked = time.monotonic()
        before = dict(self._local_stamp)
        with self.duck._lock:
            for name, rel in LOCAL_TABLES.items():
                self._localise(name, rel)
            if self._local_stamp != before:
                self.duck.sql(f"CREATE OR REPLACE VIEW periods_serving AS {PERIODS_SERVING_SQL}")
        return self._local_stamp != before

    @staticmethod
    def _empty_table_schemas() -> dict[str, pa.Schema]:
        """Arrow schema per serving table, taken from the modules that write them so the empty
        stand-ins have the real columns and types (imported lazily: the db layer does not otherwise
        depend on ingest)."""
        from filings_hub.ingest.documents import DOCUMENTS_SCHEMA
        from filings_hub.ingest.metrics import COMPANY_METRICS_SCHEMA
        from filings_hub.ingest.periods import PERIODS_SCHEMA
        from filings_hub.ingest.refresh import RUN_LOG_SCHEMA
        from filings_hub.ingest.submissions import FILINGS_SCHEMA
        from filings_hub.ingest.sync_facts import FACTS_SCHEMA
        from filings_hub.ingest.sync_statements import CHECKS_SCHEMA, STATEMENTS_SCHEMA
        from filings_hub.ingest.sync_universe import COMPANIES_SCHEMA, TICKERS_SCHEMA

        return {
            "companies": COMPANIES_SCHEMA,
            "tickers": TICKERS_SCHEMA,
            "filings": FILINGS_SCHEMA,
            "periods": PERIODS_SCHEMA,
            "company_metrics": COMPANY_METRICS_SCHEMA,
            "documents": DOCUMENTS_SCHEMA,
            "facts": FACTS_SCHEMA,
            "statements": STATEMENTS_SCHEMA,
            "statement_checks": CHECKS_SCHEMA,
            "run_log": RUN_LOG_SCHEMA,
        }

    def _prepare_duck_views(self) -> None:
        """Views over whatever the lake holds, with correctly-typed empty stand-ins for the rest.

        A lake that is still being backfilled (or has a table with no rows yet) must answer queries with
        an empty result, not fail: the API is expected to be up while `filings-hub backfill` runs.
        """
        views = self.duck.create_views()
        if self._local_dir is not None:
            for name, rel in LOCAL_TABLES.items():
                if self._localise(name, rel):
                    views[name] = True
            self._local_checked = time.monotonic()
        for name, schema in self._empty_table_schemas().items():
            if not views.get(name):
                self.duck.register(f"_empty_{name}", schema.empty_table())
                self.duck.sql(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM _empty_{name}")
        # periods_serving adds the statements source and check outcome to each period
        self.duck.sql(f"CREATE OR REPLACE VIEW periods_serving AS {PERIODS_SERVING_SQL}")

    def refresh_views(self) -> None:
        if self.backend == "duckdb":
            self._prepare_duck_views()

    @property
    def periods_table(self) -> str:
        return "periods" if self.backend == "postgres" else "periods_serving"

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        if self.backend == "duckdb":
            return self.duck.fetch_dicts(sql, list(params))
        with self.conn.cursor() as cur:
            cur.execute(sql.replace("?", "%s"), list(params))
            if cur.description is None:
                return []
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        if self.backend == "duckdb":
            self.duck.sql(sql, list(params))
        else:
            with self.conn.cursor() as cur:
                cur.execute(sql.replace("?", "%s"), list(params))

    def close(self) -> None:
        if self.backend == "duckdb":
            self.duck.close()
        else:
            self.conn.close()
        if self._local_dir:
            shutil.rmtree(self._local_dir, ignore_errors=True)

    # -- facts always come from the lake --------------------------------------------------------
    def facts_duck(self) -> Duck:
        if self.backend == "duckdb":
            return self.duck
        if self.storage is None:
            raise RuntimeError("facts need a lake Storage")
        if not hasattr(self, "_facts_duck"):
            self._facts_duck = Duck(self.storage)
            self._facts_duck.view("facts", f"{layout.FACTS}/*/*.parquet")
        return self._facts_duck


def database_from_settings(storage: Storage | None = None) -> Database:
    from filings_hub.config import get_settings

    s = get_settings()
    storage = storage or Storage(s.resolved_lake_root())
    return Database(s.database_url, storage)
