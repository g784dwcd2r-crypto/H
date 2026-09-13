"""Publish a finalized ingestion run after the serving data load has completed."""

from typing import Any

import psycopg
from psycopg import sql

from filings_hub.db.load import TABLE_COLUMNS, apply_migrations


def publish_run_log(database_url: str, row: dict[str, Any]) -> None:
    columns = TABLE_COLUMNS["run_log"]
    statement = sql.SQL(
        "INSERT INTO run_log ({columns}) VALUES ({values}) ON CONFLICT (run_id) DO UPDATE SET {updates}"
    ).format(
        columns=sql.SQL(", ").join(map(sql.Identifier, columns)),
        values=sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        updates=sql.SQL(", ").join(
            sql.SQL("{name} = EXCLUDED.{name}").format(name=sql.Identifier(name))
            for name in columns
            if name != "run_id"
        ),
    )
    with psycopg.connect(database_url, autocommit=True) as conn:
        apply_migrations(conn)
        conn.execute(statement, [row.get(column) for column in columns])
