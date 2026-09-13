"""DuckDB connection with views over the lake's Parquet layout."""

from __future__ import annotations

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

    def __init__(self, storage: Storage, database: str = ":memory:", threads: int | None = None):
        self.storage = storage
        # One DuckDB connection is not safe for concurrent use: `execute` on a second thread replaces
        # the pending result of the first, which silently pairs one query's columns with another's rows.
        # The API serves sync endpoints from a threadpool, so every use of the connection is serialised.
        # Re-entrant because the higher-level helpers call each other.
        self._lock = threading.RLock()
        self.con = duckdb.connect(database)
        if threads:
            self.sql(f"SET threads={int(threads)}")
        if storage.is_remote:
            # The lake's own fsspec filesystem serves DuckDB too: one credential path, no `httpfs`
            # extension to download, and any S3-compatible endpoint. Reads, globs and partitioned
            # COPY ... APPEND all go through it.
            with self._lock:
                self.con.register_filesystem(storage.fs)

    # -- helpers -------------------------------------------------------------------------------
    def path(self, rel: str) -> str:
        return self.storage.duck_path(rel)

    def has(self, rel: str) -> bool:
        return self.storage.exists(rel)

    def has_parquet_under(self, rel_dir: str) -> bool:
        return bool(self.storage.glob(f"{rel_dir}/**/*.parquet")) or bool(self.storage.glob(f"{rel_dir}/*.parquet"))

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
            if not self.storage.glob(rel_glob):
                return False
        elif not self.storage.exists(rel_glob):
            return False
        self.sql(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM {self.scan(rel_glob, hive)}")
        return True

    def create_views(self) -> dict[str, bool]:
        """Create standard views. Missing datasets are skipped (returned as False)."""
        return {
            "companies": self.view("companies", layout.COMPANIES, hive=False),
            "tickers": self.view("tickers", layout.TICKERS, hive=False),
            "filings": self.view("filings", f"{layout.FILINGS}/*/*.parquet"),
            "periods": self.view("periods", layout.PERIODS, hive=False),
            "company_metrics": self.view("company_metrics", layout.COMPANY_METRICS, hive=False),
            "documents": self.view("documents", f"{layout.DOCUMENTS}/*/*.parquet"),
            "facts": self.view("facts", f"{layout.FACTS}/*/*.parquet"),
            "statements": self.view("statements", f"{layout.STATEMENTS}/*/*.parquet"),
            "statement_checks": self.view("statement_checks", f"{layout.STATEMENT_CHECKS}/*/*.parquet"),
            "fsds_sub": self.view("fsds_sub", f"{layout.FSDS}/sub/*/*.parquet"),
            "fsds_num": self.view("fsds_num", f"{layout.FSDS}/num/*/*.parquet"),
            "fsds_pre": self.view("fsds_pre", f"{layout.FSDS}/pre/*/*.parquet"),
            "fsds_tag": self.view("fsds_tag", f"{layout.FSDS}/tag/*/*.parquet"),
            "run_log": self.view("run_log", f"{layout.RUN_LOG}/*.parquet", hive=False),
        }

    def close(self) -> None:
        with self._lock:
            self.con.close()
