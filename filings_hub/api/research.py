"""Read-only indexed research routes, wired explicitly by create_app."""

from __future__ import annotations

from datetime import date
from threading import Lock

from fastapi import Depends, FastAPI, HTTPException, Query

from filings_hub.db.database import Database
from filings_hub.lake.storage import Storage
from filings_hub.research_index import ResearchIndex, open_index
from filings_hub.research_query import QueryError


def attach_research_search_routes(
    app: FastAPI, *, database: Database, storage: Storage, auth, index: ResearchIndex | None = None
) -> None:
    lock = Lock()
    owns_index = index is None

    # Lazy opening creates no index or external traffic merely by importing the application.
    def get_index() -> ResearchIndex:
        nonlocal index
        with lock:
            if index is None:
                try:
                    index = open_index(storage, database.url)
                except Exception as exc:
                    raise HTTPException(503, "The durable research index is not available on this deployment.") from exc
        return index

    def close_index():
        if owns_index and index is not None:
            index.close()

    app.router.add_event_handler("shutdown", close_index)

    @app.get("/research/search")
    def search(
        q: str = Query("", max_length=1000),
        cik: int | None = Query(None, gt=0, lt=10**10),
        form: str | None = Query(None, max_length=32),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
        _: str = Depends(auth),
    ):
        if from_date and to_date and from_date > to_date:
            raise HTTPException(422, "The from date must be on or before the to date.")
        try:
            return get_index().search(
                q,
                cik=cik,
                form=form.strip().upper() if form else None,
                from_date=from_date,
                to_date=to_date,
                limit=limit,
                offset=offset,
            )
        except QueryError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/research/documents/{version_id}")
    def document(version_id: str, _: str = Depends(auth)):
        if len(version_id) != 71 or not version_id.startswith("sha256:"):
            raise HTTPException(404, "Indexed document version not found.")
        record = get_index().version(version_id)
        if record is None:
            raise HTTPException(404, "Indexed document version not found.")
        return record

    @app.get("/research/documents/{version_id}/history")
    def history(
        version_id: str, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), _: str = Depends(auth)
    ):
        if len(version_id) != 71 or not version_id.startswith("sha256:"):
            raise HTTPException(404, "Indexed document version not found.")
        record = get_index().history(version_id, limit=limit, offset=offset)
        if record is None:
            raise HTTPException(404, "Indexed document version not found.")
        return record

    @app.get("/research/compare")
    def compare(
        before: str = Query(pattern=r"^sha256:[0-9a-f]{64}$"),
        after: str = Query(pattern=r"^sha256:[0-9a-f]{64}$"),
        context: int = Query(3, ge=0, le=10),
        max_hunks: int = Query(20, ge=1, le=50),
        max_lines: int = Query(600, ge=1, le=1000),
        _: str = Depends(auth),
    ):
        try:
            record = get_index().compare(before, after, context=context, max_hunks=max_hunks, max_lines=max_lines)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if record is None:
            raise HTTPException(404, "Indexed document version not found.")
        return record
