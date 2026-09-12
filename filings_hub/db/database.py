"""One query interface over two backends.

* Postgres (`DATABASE_URL=postgresql://...`): the serving tables loaded by `db.load`.
* DuckDB over the lake (no DATABASE_URL): views over the same tables straight from Parquet, so the API,
  exporter and tests run without a database.

SQL is written once with `?` placeholders (converted to `%s` for psycopg).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

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


class Database:
    def __init__(self, url: str | None = None, storage: Storage | None = None):
        self.url = url or ""
        self.storage = storage
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
            self._prepare_duck_views()

    def _prepare_duck_views(self) -> None:
        views = self.duck.create_views()
        if views["periods"] and views["statements"]:
            self.duck.sql(f"CREATE OR REPLACE VIEW periods_serving AS {PERIODS_SERVING_SQL}")
        elif views["periods"]:
            self.duck.sql(
                "CREATE OR REPLACE VIEW periods_serving AS "
                "SELECT *, NULL::VARCHAR AS statements_source, NULL::BOOLEAN AS checks_passed FROM periods"
            )
        for name, ok in views.items():
            if not ok and name in (
                "companies",
                "tickers",
                "filings",
                "periods",
                "statements",
                "statement_checks",
                "run_log",
            ):
                # empty stand-ins so queries do not fail on a fresh lake
                self.duck.sql(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM (SELECT 1) WHERE FALSE")
        if not views["periods"]:
            self.duck.sql("CREATE OR REPLACE VIEW periods_serving AS SELECT * FROM (SELECT 1) WHERE FALSE")

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
