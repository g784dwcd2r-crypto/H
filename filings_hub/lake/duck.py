"""DuckDB connection with views over the lake's Parquet layout."""

from __future__ import annotations

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
        self.con = duckdb.connect(database)
        if threads:
            self.con.execute(f"SET threads={int(threads)}")
        if storage.is_remote:
            self._configure_httpfs()

    def _configure_httpfs(self) -> None:
        from filings_hub.config import get_settings

        s = get_settings()
        self.con.execute("INSTALL httpfs; LOAD httpfs;")
        self.con.execute(f"SET s3_region='{s.aws_region}'")
        if s.aws_access_key_id:
            self.con.execute(f"SET s3_access_key_id='{s.aws_access_key_id}'")
            self.con.execute(f"SET s3_secret_access_key='{s.aws_secret_access_key}'")
            if s.aws_session_token:
                self.con.execute(f"SET s3_session_token='{s.aws_session_token}'")

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

    def sql(self, query: str, params: list[Any] | None = None) -> duckdb.DuckDBPyRelation:
        return self.con.execute(query, params or [])

    def fetch_arrow(self, query: str, params: list[Any] | None = None) -> pa.Table:
        return to_arrow(self.con.execute(query, params or []))

    def fetch_dicts(self, query: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        cur = self.con.execute(query, params or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def register(self, name: str, table: pa.Table) -> None:
        self.con.register(name, table)

    # -- views over the lake -------------------------------------------------------------------
    def view(self, name: str, rel_glob: str, hive: bool = True) -> bool:
        """Create/replace a view if the data exists. Returns False when there is nothing to read."""
        base = rel_glob.split("*")[0].rstrip("/")
        has_dir = self.storage.exists(base) and (self.storage.glob(rel_glob) or rel_glob.endswith(".parquet"))
        if not has_dir and not self.storage.exists(rel_glob):
            return False
        self.con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM {self.scan(rel_glob, hive)}")
        return True

    def create_views(self) -> dict[str, bool]:
        """Create standard views. Missing datasets are skipped (returned as False)."""
        return {
            "companies": self.view("companies", layout.COMPANIES, hive=False),
            "tickers": self.view("tickers", layout.TICKERS, hive=False),
            "filings": self.view("filings", f"{layout.FILINGS}/*/*.parquet"),
            "periods": self.view("periods", layout.PERIODS, hive=False),
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
        self.con.close()
