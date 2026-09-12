"""Load serving tables from the lake into Postgres with COPY.

Full load: every table replaced. Incremental (daily): companies/tickers/periods/run_log replaced (small),
filings and statements replaced only for the touched CIKs / accessions.

Statements: by default only the primary-period rows (plus headers) are loaded -- that is what the hub
shows, one column per filing. Comparative columns stay in the lake (`--all-periods` loads them too).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import psycopg
import pyarrow as pa

from filings_hub.db.database import PERIODS_SERVING_SQL
from filings_hub.lake import layout
from filings_hub.lake.duck import Duck
from filings_hub.lake.storage import Storage

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

TABLE_COLUMNS: dict[str, list[str]] = {
    "companies": [
        "cik",
        "name",
        "ticker",
        "exchange",
        "sic",
        "sic_description",
        "entity_type",
        "category",
        "state_of_incorporation",
        "state_of_incorporation_description",
        "fiscal_year_end",
        "ein",
        "former_names",
        "business_state",
        "business_city",
        "website",
        "is_listed",
        "is_active",
        "last_filing_date",
        "last_financial_report_date",
        "last_financial_report_form",
        "filing_count",
    ],
    "tickers": ["cik", "ticker", "exchange", "is_primary", "source"],
    "filings": [
        "accession",
        "cik",
        "form",
        "filed_date",
        "report_date",
        "acceptance_datetime",
        "act",
        "file_number",
        "film_number",
        "items",
        "size",
        "is_xbrl",
        "is_inline_xbrl",
        "primary_doc",
        "primary_doc_description",
        "primary_doc_url",
        "filing_index_url",
        "source",
        "year",
    ],
    "periods": [
        "cik",
        "period_label",
        "fiscal_year",
        "fiscal_quarter",
        "period_type",
        "period_end",
        "results_accession",
        "results_form",
        "results_filed_date",
        "results_primary_doc_url",
        "earnings_release_accession",
        "earnings_release_filed_date",
        "earnings_release_primary_doc_url",
        "amendment_accessions",
        "label_method",
        "statements_source",
        "checks_passed",
    ],
    "statements": [
        "accession",
        "cik",
        "statement",
        "report",
        "line",
        "line_order",
        "is_parenthetical",
        "concept",
        "taxonomy",
        "label",
        "standard_label",
        "negating",
        "is_abstract",
        "is_custom",
        "iord",
        "crdr",
        "datatype",
        "period_start",
        "period_end",
        "period_end_rounded",
        "qtrs",
        "unit",
        "value",
        "value_presented",
        "is_primary_period",
        "is_subtotal",
        "parent_concept",
        "source",
        "fsds_quarter",
        "form",
        "filed_date",
        "checks_passed",
    ],
    "statement_checks": [
        "accession",
        "cik",
        "statement",
        "check_name",
        "passed",
        "lhs",
        "rhs",
        "difference",
        "detail",
        "source",
    ],
    "run_log": [
        "run_id",
        "kind",
        "started_at",
        "finished_at",
        "duration_seconds",
        "status",
        "index_dates",
        "new_filings",
        "ciks_refreshed",
        "facts_rows",
        "statements_built",
        "fsds_quarters_loaded",
        "failures",
        "error",
        "db_loaded",
    ],
}


# ---------------------------------------------------------------------------------------------
# Schema / migrations
# ---------------------------------------------------------------------------------------------
SCHEMA_SQL = Path(__file__).parent / "schema.sql"
SCHEMA_HEADER = (
    "-- Serving schema (Postgres). GENERATED from migrations/ by `make schema` -- do not edit by hand.\n"
    "-- Apply with `filings-hub load` (which runs the migrations) or `psql -f filings_hub/db/schema.sql`.\n"
)


def render_schema_sql() -> str:
    """The full schema as the concatenation of every migration, in order."""
    body = "\n".join(f"-- ==== {p.name} ====\n{p.read_text().strip()}\n" for p in sorted(MIGRATIONS_DIR.glob("*.sql")))
    return SCHEMA_HEADER + "\n" + body


def write_schema_sql() -> str:
    SCHEMA_SQL.write_text(render_schema_sql())
    return str(SCHEMA_SQL)


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT now())"
        )
        cur.execute("SELECT name FROM schema_migrations")
        done = {r[0] for r in cur.fetchall()}
    applied = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in done:
            continue
        with conn.cursor() as cur:
            cur.execute(path.read_text())
            cur.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
        applied.append(path.name)
        log.info("applied migration %s", path.name)
    return applied


# ---------------------------------------------------------------------------------------------
# COPY helpers
# ---------------------------------------------------------------------------------------------
def _clean(v: Any) -> Any:
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, datetime | date):
        return v
    return v


def copy_rows(
    conn: psycopg.Connection,
    table: str,
    rows: Iterable[dict[str, Any]],
    columns: list[str] | None = None,
) -> int:
    cols = columns or TABLE_COLUMNS[table]
    n = 0
    with conn.cursor() as cur, cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as copy:
        for r in rows:
            copy.write_row([_clean(r.get(c)) for c in cols])
            n += 1
    return n


def copy_table(conn: psycopg.Connection, table: str, arrow: pa.Table) -> int:
    cols = [c for c in TABLE_COLUMNS[table] if c in arrow.column_names]
    return copy_rows(conn, table, arrow.select(cols).to_pylist(), cols)


def _replace_all(conn: psycopg.Connection, table: str, arrow: pa.Table) -> int:
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(f"TRUNCATE {table}")
        return copy_table(conn, table, arrow)


def _replace_where(conn: psycopg.Connection, table: str, col: str, keys: list[Any], arrow: pa.Table) -> int:
    if not keys and arrow.num_rows == 0:
        return 0
    with conn.transaction(), conn.cursor() as cur:
        if keys:
            cur.execute(f"DELETE FROM {table} WHERE {col} = ANY(%s)", (list(keys),))
        return copy_table(conn, table, arrow)


# ---------------------------------------------------------------------------------------------
# Lake -> arrow for each serving table
# ---------------------------------------------------------------------------------------------
def _statements_filter(all_periods: bool) -> str:
    return "" if all_periods else "WHERE is_primary_period"


def serving_periods(duck: Duck) -> pa.Table:
    if not duck.view("periods", layout.PERIODS, hive=False):
        return pa.table({c: [] for c in TABLE_COLUMNS["periods"]})
    if duck.view("statements", f"{layout.STATEMENTS}/*/*.parquet"):
        return duck.fetch_arrow(PERIODS_SERVING_SQL)
    return duck.fetch_arrow("SELECT *, NULL::VARCHAR AS statements_source, NULL::BOOLEAN AS checks_passed FROM periods")


def load_full(storage: Storage, database_url: str, all_periods: bool = False, batch_ciks: int = 2000) -> dict[str, int]:
    """Rebuild every serving table from the lake."""
    counts: dict[str, int] = {}
    duck = Duck(storage)
    with psycopg.connect(database_url, autocommit=True) as conn:
        apply_migrations(conn)
        views = duck.create_views()
        if views["companies"]:
            counts["companies"] = _replace_all(conn, "companies", duck.fetch_arrow("SELECT * FROM companies"))
        if views["tickers"]:
            counts["tickers"] = _replace_all(conn, "tickers", duck.fetch_arrow("SELECT * FROM tickers"))
        if views["filings"]:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE filings")
            n = 0
            for y in duck.fetch_dicts("SELECT DISTINCT year FROM filings ORDER BY year"):
                n += copy_table(
                    conn,
                    "filings",
                    duck.fetch_arrow("SELECT * FROM filings WHERE year = ?", [y["year"]]),
                )
            counts["filings"] = n
        counts["periods"] = _replace_all(conn, "periods", serving_periods(duck))
        if views["statements"]:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE statements")
            ciks = [r["cik"] for r in duck.fetch_dicts("SELECT DISTINCT cik FROM statements ORDER BY cik")]
            n = 0
            for i in range(0, len(ciks), batch_ciks):
                chunk = ciks[i : i + batch_ciks]
                n += copy_table(
                    conn,
                    "statements",
                    duck.fetch_arrow(
                        f"SELECT * FROM statements {_statements_filter(all_periods)} "
                        f"{'AND' if not all_periods else 'WHERE'} cik IN (SELECT unnest(?::BIGINT[]))",
                        [chunk],
                    ),
                )
            counts["statements"] = n
        if views["statement_checks"]:
            counts["statement_checks"] = _replace_all(
                conn,
                "statement_checks",
                duck.fetch_arrow(
                    "SELECT * FROM statement_checks "
                    "QUALIFY row_number() OVER (PARTITION BY accession, statement, check_name ORDER BY source) = 1"
                ),
            )
        if views["run_log"]:
            counts["run_log"] = _replace_all(conn, "run_log", duck.fetch_arrow("SELECT * FROM run_log"))
    duck.close()
    log.info("full load: %s", counts)
    return counts


def load_incremental(
    storage: Storage,
    database_url: str,
    ciks: set[int],
    accessions: set[str] = frozenset(),
    fsds_quarters: list[str] | None = None,
    all_periods: bool = False,
) -> dict[str, int]:
    """Daily path: small tables replaced, big tables patched for the touched CIKs / accessions."""
    counts: dict[str, int] = {}
    duck = Duck(storage)
    views = duck.create_views()
    cik_list = sorted(ciks)
    with psycopg.connect(database_url, autocommit=True) as conn:
        apply_migrations(conn)
        if views["companies"]:
            counts["companies"] = _replace_all(conn, "companies", duck.fetch_arrow("SELECT * FROM companies"))
        if views["tickers"]:
            counts["tickers"] = _replace_all(conn, "tickers", duck.fetch_arrow("SELECT * FROM tickers"))
        counts["periods"] = _replace_all(conn, "periods", serving_periods(duck))
        if views["filings"] and (cik_list or accessions):
            rows = duck.fetch_arrow(
                "SELECT * FROM filings WHERE cik IN (SELECT unnest(?::BIGINT[])) "
                "OR accession IN (SELECT unnest(?::VARCHAR[]))",
                [cik_list, sorted(accessions)],
            )
            with conn.transaction(), conn.cursor() as cur:
                if cik_list:
                    cur.execute("DELETE FROM filings WHERE cik = ANY(%s)", (cik_list,))
                if accessions:
                    cur.execute("DELETE FROM filings WHERE accession = ANY(%s)", (sorted(accessions),))
                counts["filings"] = copy_table(conn, "filings", rows)
        if views["statements"]:
            touched_acc: set[str] = set()
            if cik_list:
                touched_acc |= {
                    r["accession"]
                    for r in duck.fetch_dicts(
                        "SELECT DISTINCT accession FROM statements WHERE cik IN (SELECT unnest(?::BIGINT[]))",
                        [cik_list],
                    )
                }
            for q in fsds_quarters or []:
                touched_acc |= {
                    r["accession"]
                    for r in duck.fetch_dicts("SELECT DISTINCT accession FROM statements WHERE fsds_quarter = ?", [q])
                }
            if touched_acc:
                acc = sorted(touched_acc)
                stm = duck.fetch_arrow(
                    f"SELECT * FROM statements {_statements_filter(all_periods)} "
                    f"{'AND' if not all_periods else 'WHERE'} accession IN (SELECT unnest(?::VARCHAR[]))",
                    [acc],
                )
                counts["statements"] = _replace_where(conn, "statements", "accession", acc, stm)
                if views["statement_checks"]:
                    chk = duck.fetch_arrow(
                        "SELECT * FROM statement_checks WHERE accession IN (SELECT unnest(?::VARCHAR[])) "
                        "QUALIFY row_number() OVER (PARTITION BY accession, statement, check_name ORDER BY source) = 1",
                        [acc],
                    )
                    counts["statement_checks"] = _replace_where(conn, "statement_checks", "accession", acc, chk)
        if views["run_log"]:
            counts["run_log"] = _replace_all(conn, "run_log", duck.fetch_arrow("SELECT * FROM run_log"))
    duck.close()
    log.info("incremental load: %s", counts)
    return counts
