"""DuckDB connection with views over the lake's Parquet layout."""

from __future__ import annotations

import contextlib
import threading
from typing import Any

import duckdb
import pyarrow as pa

from filings_hub.lake import layout
from filings_hub.lake.storage import Storage


def to_arrow(result: duckdb.DuckDBPyConnection) -> pa.Table:
    """DuckDB result -> pyarrow.Table across DuckDB versions (to_arrow_table is 1.5+)."""
    fn = getattr(result, "to_arrow_table", None) or result.fetch_arrow_table
    return fn()


class Duck:
    """One DuckDB connection bound to a lake. Views are created lazily and tolerate missing data."""

    def __init__(
        self, storage: Storage, database: str = ":memory:", threads: int | None = None, memory_limit: str | None = None
    ):
        self.storage = storage
        # One DuckDB connection is not safe for concurrent use: `execute` on a second thread replaces
        # the pending result of the first, which silently pairs one query's columns with another's rows.
        # The API serves sync endpoints from a threadpool, so every use of the connection is serialised.
        # Re-entrant because the higher-level helpers call each other.
        self._lock = threading.RLock()
        self.con = duckdb.connect(database)
        if threads:
            self.sql(f"SET threads={int(threads)}")
        if memory_limit:
            # A small serving instance (512MB on the free tier) must not let DuckDB claim 80% of the
            # machine: the cap makes it spill to disk instead of being killed.
            self.sql(f"SET memory_limit='{memory_limit}'")
        if storage.is_remote:
            # The lake's own fsspec filesystem serves DuckDB too: one credential path, no `httpfs`
            # extension to download, and any S3-compatible endpoint. Reads, globs and partitioned
            # COPY ... APPEND all go through it.
            with self._lock:
                self.con.register_filesystem(getattr(storage, "duck_fs", storage.fs))
            # Parquet footers and object listings are fetched over the network: keep them for the
            # life of the connection so a company read a second time costs no round trips.
            for setting in ("SET parquet_metadata_cache=true", "SET enable_object_cache=true"):
                with contextlib.suppress(duckdb.Error):  # older DuckDB without the setting
                    self.sql(setting)

    # -- helpers -------------------------------------------------------------------------------
    def path(self, rel: str) -> str:
        return self.storage.duck_path(rel)

    def has(self, rel: str) -> bool:
        return self.storage.exists(rel)

    def has_parquet_under(self, rel_dir: str) -> bool:
        return self.storage.any_parquet_under(rel_dir)

    def scan(self, rel_glob: str, hive: bool = True) -> str:
        """SQL fragment reading parquet files under a lake-relative glob."""
        hp = "true" if hive else "false"
        return f"read_parquet('{self.path(rel_glob)}', hive_partitioning={hp}, union_by_name=true)"

    def sql(self, query: str, params: list[Any] | None = None) -> None:
        """Run a statement that returns nothing (DDL, COPY, SET). To read rows use a fetch_* method:
        the result of a bare `execute` is only valid until the next one on this connection."""
        with self._lock:
            self.con.execute(query, params or [])

    def fetch_arrow(self, query: str, params: list[Any] | None = None) -> pa.Table:
        with self._lock:
            return to_arrow(self.con.execute(query, params or []))

    def fetch_all(self, query: str, params: list[Any] | None = None) -> list[tuple]:
        with self._lock:
            return self.con.execute(query, params or []).fetchall()

    def fetch_one(self, query: str, params: list[Any] | None = None) -> tuple | None:
        with self._lock:
            return self.con.execute(query, params or []).fetchone()

    def fetch_value(self, query: str, params: list[Any] | None = None) -> Any:
        row = self.fetch_one(query, params)
        return row[0] if row else None

    def fetch_column(self, query: str, params: list[Any] | None = None) -> list[Any]:
        return [r[0] for r in self.fetch_all(query, params)]

    def fetch_dicts(self, query: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            cur = self.con.execute(query, params or [])
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def register(self, name: str, table: pa.Table) -> None:
        with self._lock:
            self.con.register(name, table)

    def unregister(self, name: str) -> None:
        with self._lock:
            self.con.unregister(name)

    # -- views over the lake -------------------------------------------------------------------
    def view(self, name: str, rel_glob: str, hive: bool = True) -> bool:
        """Create/replace a view over `rel_glob`. Returns False when there is nothing to read.

        A wildcard pattern needs at least one matching file, not merely an existing directory: the
        builders create partition directories before they know whether anything will land in them, and
        DuckDB raises on a pattern that matches no file, which would take down every later query.
        """
        if "*" in rel_glob:
            # one request for "is there anything under the fixed part of the pattern", never a listing
            # of every object the pattern matches (millions on a full remote lake)
            if not self.storage.any_parquet_under(rel_glob.split("*", 1)[0].rstrip("/")):
                return False
        elif not self.storage.exists(rel_glob):
            return False
        self.sql(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM {self.scan(rel_glob, hive)}")
        return True

    def create_views(self, partitioned: bool = True) -> dict[str, bool]:
        """Create standard views. Missing datasets are skipped (returned as False).

        `partitioned=False` leaves the per-company tables (documents, facts, statements, checks)
        without a whole-table view: DuckDB binds a view at creation by listing every file the pattern
        matches, which on a full remote lake is millions of objects. Those tables are then read one
        company partition at a time through `Database.table()`.
        """

        def per_company(name: str, rel: str) -> bool:
            return self.view(name, f"{rel}/*/*.parquet") if partitioned else False

        return {
            "companies": self.view("companies", layout.COMPANIES, hive=False),
            "tickers": self.view("tickers", layout.TICKERS, hive=False),
            "filings": self.view("filings", f"{layout.FILINGS}/*/*.parquet"),
            "periods": self.view("periods", layout.PERIODS, hive=False),
            "company_metrics": self.view("company_metrics", layout.COMPANY_METRICS, hive=False),
            "documents": per_company("documents", layout.DOCUMENTS),
            "facts": per_company("facts", layout.FACTS),
            "statements": per_company("statements", layout.STATEMENTS),
            "statement_checks": per_company("statement_checks", layout.STATEMENT_CHECKS),
            "fsds_sub": self.view("fsds_sub", f"{layout.FSDS}/sub/*/*.parquet"),
            "fsds_num": self.view("fsds_num", f"{layout.FSDS}/num/*/*.parquet"),
            "fsds_pre": self.view("fsds_pre", f"{layout.FSDS}/pre/*/*.parquet"),
            "fsds_tag": self.view("fsds_tag", f"{layout.FSDS}/tag/*/*.parquet"),
            "run_log": self.view("run_log", f"{layout.RUN_LOG}/*.parquet", hive=False),
        }

    def close(self) -> None:
        with self._lock:
            self.con.close()
