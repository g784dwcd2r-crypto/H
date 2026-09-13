"""Separate issuer-scoped ownership flows. GET requests never create or ingest a corpus."""

from __future__ import annotations

import csv
import io
import sqlite3
from datetime import date
from pathlib import Path
from threading import Lock, RLock
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import Response

from filings_hub.ownership.store import OwnershipStore, SourceIntegrityError, number
from filings_hub.research_index import ResearchIndex

Flow = Literal["insiders", "institutions", "events"]
Direction = Literal["all", "buys", "sales"]


def readonly_index(storage, database_url):
    """Reuse the index transaction/query interface without its constructor's schema writes."""
    index = object.__new__(ResearchIndex)
    index._lock = RLock()
    index.postgres = database_url.startswith(("postgresql://", "postgres://"))
    if index.postgres:
        import psycopg
        from psycopg.rows import dict_row

        index.conn = psycopg.connect(
            database_url, autocommit=True, row_factory=dict_row, options="-c default_transaction_read_only=on"
        )
    else:
        if storage.is_remote:
            raise ValueError("A remote ownership corpus requires PostgreSQL.")
        path = Path(storage.full("research/search.sqlite3"))
        index.conn = sqlite3.connect(
            path.as_uri() + "?mode=ro", uri=True, check_same_thread=False, isolation_level=None, timeout=30
        )
        index.conn.row_factory = sqlite3.Row
    return index


def csv_cell(value):
    value = "" if value is None else str(value)
    if value.startswith(("\t", "\r", "\n")) or (
        value.lstrip().startswith(("=", "+", "-", "@")) and number(value.strip()) is None
    ):
        return "'" + value
    return value


def attach_ownership_routes(app: FastAPI, *, database, storage, auth, index=None):
    lock, store, owns = Lock(), None, index is None

    def get_store():
        nonlocal store, index
        with lock:
            if store is None:
                try:
                    if index is None:
                        index = readonly_index(storage, database.url)
                    store = OwnershipStore(index, storage, initialize=False)
                except Exception as error:
                    if owns and index is not None:
                        index.close()
                        index = None
                    raise HTTPException(
                        503, "Ownership coverage is unavailable until its explicit ingestion and schema setup have run."
                    ) from error
        return store

    def close():
        if owns and index is not None:
            index.close()

    def checked(action):
        try:
            return action()
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except (SourceIntegrityError, OSError) as error:
            raise HTTPException(
                503, "The retained ownership source is unavailable or failed integrity verification."
            ) from error

    app.router.add_event_handler("shutdown", close)

    @app.get("/companies/{cik}/ownership/documents/{document_id}")
    def document(cik: int, document_id: str, _: str = Depends(auth)):
        result = checked(lambda: get_store().document(cik, document_id))
        if result is None:
            raise HTTPException(404, "Ownership source is not linked to this issuer.")
        return result

    @app.get("/companies/{cik}/ownership/{kind}/export.csv")
    def export(
        cik: int,
        kind: Flow,
        direction: Direction = "all",
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        _: str = Depends(auth),
    ):
        rows = checked(lambda: get_store().export_rows(cik, kind, direction, from_date, to_date))
        headers = list(rows[0]) if rows else ["issuer_cik", "accession", "form", "filed_date", "source_url"]
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(csv_cell(row.get(key)) for key in headers)
        return Response(
            output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{cik}-{kind}.csv"',
                "X-Ownership-Coverage": "partial",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/companies/{cik}/ownership/{kind}")
    def flow(
        cik: int,
        kind: Flow,
        limit: int = Query(20, ge=1, le=50),
        offset: int = Query(0, ge=0, le=1_000_000),
        direction: Direction = "all",
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        _: str = Depends(auth),
    ):
        return checked(lambda: get_store().flow(cik, kind, limit, offset, direction, from_date, to_date))

    @app.get("/ownership/recent")
    def recent(
        ciks: str = Query(..., max_length=2400),
        flow: Flow = "insiders",
        since: date | None = None,
        limit: int = Query(50, ge=1, le=100),
        _: str = Depends(auth),
    ):
        return checked(lambda: get_store().feed(ciks.split(","), since, flow, limit))

    @app.get("/ownership/coverage")
    def coverage(cik: int | None = Query(None, gt=0, lt=10**10), _: str = Depends(auth)):
        return checked(lambda: get_store().coverage(cik))

    return get_store
