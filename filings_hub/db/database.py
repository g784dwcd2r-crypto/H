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

    @staticmethod
    def _empty_table_schemas() -> dict[str, pa.Schema]:
        """Arrow schema per serving table, taken from the modules that write them so the empty
        stand-ins have the real columns and types (imported lazily: the db layer does not otherwise
        depend on ingest)."""
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
