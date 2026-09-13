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
from contextlib import closing, contextmanager
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
    SELECT cik, accession,
           CASE WHEN bool_or(source = 'fsds') THEN 'fsds' ELSE 'facts_fallback' END AS statements_source,
           bool_and(checks_passed) AS checks_passed
    FROM statements
    WHERE statement IN ('IS', 'BS', 'CF') AND is_primary_period
    GROUP BY cik, accession
) s ON s.accession = p.results_accession AND s.cik = p.cik
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
MISSING_VIEW_TTL = 30.0
PARTITION_TTL = 600.0  # how long "company X has a statements partition" is trusted on a remote lake
PER_COMPANY_TABLES = ("documents", "facts", "statements", "statement_checks")  # partitioned by cik
PARTITIONED_TABLES = {
    "filings": layout.FILINGS,
    "documents": layout.DOCUMENTS,
    "facts": layout.FACTS,
    "statements": layout.STATEMENTS,
    "statement_checks": layout.STATEMENT_CHECKS,
}


class Database:
    def __init__(self, url: str | None = None, storage: Storage | None = None, local_cache: bool = True):
        self.url = url or ""
        self.storage = storage
        self._local_dir: str | None = None
        self._local_stamp: dict[str, tuple[int, str]] = {}
        self._local_checked = 0.0
        self._remote_checked = 0.0
        self._missing_checked = 0.0
        self._missing_views: set[str] = set()
        self._partitions: dict[tuple[str, int], tuple[float, bool]] = {}
        if self.url.startswith(("postgresql://", "postgres://")):
            self.backend = "postgres"
            import psycopg

            self._pg = psycopg
            self.conn = psycopg.connect(self.url, autocommit=True)
        else:
            if storage is None:
                raise ValueError("DuckDB backend needs a lake Storage")
            self.backend = "duckdb"
            from filings_hub.config import get_settings

            cfg = get_settings()
            self.duck = Duck(storage, threads=cfg.duckdb_threads or None, memory_limit=cfg.duckdb_memory_limit or None)
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
        return int(info.get("size") or 0), str(info.get("ETag") or info.get("LastModified") or info.get("mtime") or "")

    def _localise(self, name: str, rel: str) -> bool:
        """Copy `rel` next to the process and point the view at it. False when the table is absent."""
        assert self.storage is not None and self._local_dir is not None
        stamp = self._remote_stamp(rel)
        if stamp is None:
            return False
        path = os.path.join(self._local_dir, f"{name}.parquet")
        if self._local_stamp.get(name) != stamp:
            tmp = path + ".part"
            with self.storage.open(rel, "rb") as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.replace(tmp, path)
            self._local_stamp[name] = stamp
            log.info("local copy of %s refreshed (%d bytes)", rel, stamp[0])
        # An explicit refresh_views() may just have rebound this view to the remote object.
        self.duck.sql(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{path}')")
        return True

    def maybe_resync(self, ttl: float = LOCAL_CACHE_TTL) -> bool:
        """Refresh remote small-table caches and replace empty views as datasets arrive.

        Missing tables are probed at most every 30 seconds, including on local lakes. Existing
        partition scans remain live; whole-universe remote copies keep their longer cache TTL.
        """
        if self.backend != "duckdb":
            return False
        now = time.monotonic()
        cache_due = self._local_dir is not None and now - self._local_checked >= ttl
        remote_due = self.storage is not None and self.storage.is_remote and now - self._remote_checked >= ttl
        missing_due = bool(self._missing_views) and now - self._missing_checked >= min(ttl, MISSING_VIEW_TTL)
        if not cache_due and not missing_due and not remote_due:
            return False
        with self.duck._lock:
            before = dict(self._local_stamp)
            missing_before = set(self._missing_views)
            if self.storage is not None and self.storage.is_remote and (remote_due or cache_due or missing_due):
                # A separate ingestion process cannot invalidate this process's S3 directory cache.
                # Refresh listings even when all views exist and local small-table caching is off.
                self.storage.fs.invalidate_cache()
                duck_fs = getattr(self.storage, "duck_fs", None)
                if duck_fs is not None and duck_fs is not self.storage.fs:
                    duck_fs.invalidate_cache()
                self._remote_checked = now
            if cache_due:
                self._local_checked = now
                for name, rel in LOCAL_TABLES.items():
                    if self._localise(name, rel):
                        self._missing_views.discard(name)
            if missing_due:
                self._missing_checked = now
                assert self.storage is not None
                for name in sorted(self._missing_views):
                    if name in LOCAL_TABLES:
                        rel = LOCAL_TABLES[name]
                        found = self._localise(name, rel) if self._local_dir else self.duck.view(name, rel, hive=False)
                    elif name == "run_log":
                        found = self.duck.view(name, f"{layout.RUN_LOG}/*.parquet", hive=False)
                    else:
                        found = self.duck.view(name, f"{PARTITIONED_TABLES[name]}/*/*.parquet")
                    if found:
                        self._missing_views.discard(name)
            changed = self._local_stamp != before or self._missing_views != missing_before
            if changed:
                self.duck.sql(f"CREATE OR REPLACE VIEW periods_serving AS {PERIODS_SERVING_SQL}")
        return changed

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
        # On a remote lake the per-company tables get no whole-table view (binding one lists every
        # object in the table); they read from the typed empty stand-in and `table()` scopes real
        # reads to one company's partition.
        views = self.duck.create_views(partitioned=not self.is_remote_lake)
        if self._local_dir is not None:
            for name, rel in LOCAL_TABLES.items():
                if self._localise(name, rel):
                    views[name] = True
            self._local_checked = time.monotonic()
        self._missing_views = set()
        self._missing_checked = time.monotonic()
        self._remote_checked = self._missing_checked
        for name, schema in self._empty_table_schemas().items():
            # the typed empty stand-in is always registered: `table()` reads from it when a company
            # has no partition, and a missing dataset's view points at it until the data arrives
            self.duck.register(f"_empty_{name}", schema.empty_table())
            if not views.get(name):
                if not (self.is_remote_lake and name in PER_COMPANY_TABLES):
                    self._missing_views.add(name)  # per-company tables are never retried as whole views
                self.duck.sql(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM _empty_{name}")
        # periods_serving adds the statements source and check outcome to each period
        self.duck.sql(f"CREATE OR REPLACE VIEW periods_serving AS {PERIODS_SERVING_SQL}")

    def refresh_views(self) -> None:
        if self.backend == "duckdb":
            with self.duck._lock:
                self._prepare_duck_views()

    @property
    def periods_table(self) -> str:
        return "periods" if self.backend == "postgres" else "periods_serving"

    @property
    def is_remote_lake(self) -> bool:
        """DuckDB over object storage: whole-table scans list millions of objects and are avoided."""
        return self.backend == "duckdb" and self.storage is not None and self.storage.is_remote

    def _partition_exists(self, name: str, cik: int) -> bool:
        assert self.storage is not None
        key = (name, int(cik))
        now = time.monotonic()
        hit = self._partitions.get(key)
        if hit is not None and now - hit[0] < PARTITION_TTL and hit[1]:
            return True
        if hit is not None and now - hit[0] < MISSING_VIEW_TTL:
            return hit[1]
        found = self.storage.any_parquet_under(f"{PARTITIONED_TABLES[name]}/cik={int(cik)}")
        self._partitions[key] = (now, found)
        return found

    def table(self, name: str, cik: int | None = None, ciks: Sequence[int] | None = None) -> str:
        """The SQL source to read `name` from for one company (or a few).

        Locally and on Postgres it is the table itself. On a remote lake a per-company table is read
        from that company's partition folder only: one small listing and a handful of parquet footers
        instead of a listing of every object in the table. `filings` is partitioned by year, not by
        company, and stays a whole-table view (row-group statistics keep a per-company read cheap).
        """
        ids = [int(cik)] if cik is not None else [int(c) for c in (ciks or [])]
        if not self.is_remote_lake or name not in PARTITIONED_TABLES or name == "filings" or not ids:
            return name
        globs = [
            self.duck.path(f"{PARTITIONED_TABLES[name]}/cik={c}/*.parquet")
            for c in dict.fromkeys(ids)
            if self._partition_exists(name, c)
        ]
        if not globs:
            return f"(SELECT * FROM _empty_{name})"
        listed = ", ".join(f"'{g}'" for g in globs)
        return f"read_parquet([{listed}], hive_partitioning=true, union_by_name=true)"

    def periods_table_for(self, cik: int) -> str:
        """`periods_table` for one company. On a remote lake the statements source and check outcome
        come from that company's statements partition rather than a join over the whole table."""
        if not self.is_remote_lake:
            return self.periods_table
        c = int(cik)
        return (
            "(SELECT p.*, s.statements_source, s.checks_passed FROM periods p LEFT JOIN ("
            "SELECT cik, accession, CASE WHEN bool_or(source = 'fsds') THEN 'fsds' ELSE 'facts_fallback' END "
            f"AS statements_source, bool_and(checks_passed) AS checks_passed FROM {self.table('statements', c)} "
            "WHERE statement IN ('IS', 'BS', 'CF') AND is_primary_period GROUP BY cik, accession) s "
            f"ON s.accession = p.results_accession AND s.cik = p.cik WHERE p.cik = {c})"
        )

    def warm(self) -> None:
        """Touch the year-partitioned filings table once so its parquet footers are cached before the
        first company page asks for them (a cold read over object storage takes several seconds)."""
        if not self.is_remote_lake:
            return
        try:
            self.duck.fetch_dicts("SELECT count(*) AS n FROM filings WHERE cik = 0")
        except Exception as e:  # pragma: no cover - warming is best effort
            log.warning("filings warm-up failed: %s", e)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        if self.backend == "duckdb":
            self.maybe_resync()
            return self.duck.fetch_dicts(sql, list(params))
        with self.conn.cursor() as cur:
            cur.execute(sql.replace("?", "%s"), list(params))
            if cur.description is None:
                return []
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    @contextmanager
    def read_snapshot(self):
        """One response observes one cooperating Postgres publication.

        Take the shared publication lock *before* a repeatable-read snapshot is acquired: TRUNCATE
        is not MVCC-safe for readers whose snapshot predates a load. A dedicated connection also
        prevents concurrent HTTP requests from sharing or committing each other's transaction.
        DuckDB's lock protects local view changes only; the mutable lake is not a published snapshot.
        """
        if getattr(self, "_snapshot_active", False):
            yield self
        elif self.backend == "duckdb":
            with self.duck._lock:
                yield self
        else:
            with closing(Database(self.url, self.storage)) as reader:
                reader.conn.execute("SELECT pg_advisory_lock_shared(684319202601)")
                with reader.conn.transaction():
                    reader.conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    reader._snapshot_active = True
                    yield reader
                # Closing the dedicated connection always releases the session lock, including on failure.

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
        if hasattr(self, "_facts_duck"):
            self._facts_duck.close()
        if self._local_dir:
            shutil.rmtree(self._local_dir, ignore_errors=True)

    # -- facts always come from the lake --------------------------------------------------------
    def facts_duck(self) -> Duck:
        if self.backend == "duckdb":
            self.maybe_resync()
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
