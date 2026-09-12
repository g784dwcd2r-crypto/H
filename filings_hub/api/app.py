"""FastAPI application.

GET /search?q=                                     companies
GET /companies/{cik}                               profile + latest period + next expected results
GET /companies/{cik}/periods                       period spine with attached filings
GET /companies/{cik}/filings?form=&from=&to=       other filings
GET /companies/{cik}/statements?periods=           as-reported lines (grid)
GET /companies/{cik}/export.xlsx?periods=          workbook
GET /companies/{cik}/facts?concept=                XBRL fact history from the lake (restatements)
GET /health
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Response

from filings_hub import __version__
from filings_hub.api.security import RateLimiter, make_auth
from filings_hub.config import Settings, get_settings
from filings_hub.db.database import Database
from filings_hub.export.excel import export_excel
from filings_hub.export.grid import build_grid
from filings_hub.ingest.periods import next_expected_results
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage

log = logging.getLogger(__name__)

FORM_LABELS = {
    "10-K": "Annual report",
    "10-K/A": "Annual report (amended)",
    "10-Q": "Quarterly report",
    "10-Q/A": "Quarterly report (amended)",
    "8-K": "Current report",
    "8-K/A": "Current report (amended)",
    "20-F": "Annual report (foreign filer)",
    "40-F": "Annual report (Canadian filer)",
    "6-K": "Interim report (foreign filer)",
    "DEF 14A": "Proxy statement",
    "DEFA14A": "Proxy materials",
    "S-8": "Employee stock plan registration",
    "S-3": "Shelf registration",
    "S-3ASR": "Shelf registration (automatic)",
    "424B2": "Prospectus supplement",
    "424B5": "Prospectus supplement",
    "4": "Insider transaction",
    "3": "Initial insider holdings",
    "SC 13G": "Passive ownership >5%",
    "SC 13G/A": "Passive ownership >5% (amended)",
    "SC 13D": "Activist ownership >5%",
    "11-K": "Employee plan annual report",
    "ARS": "Annual report to shareholders",
    "SD": "Conflict minerals",
    "PX14A6G": "Shareholder proxy exempt solicitation",
    "CORRESP": "Correspondence with SEC",
    "UPLOAD": "SEC comment letter",
    "10-KT": "Transition report (annual)",
    "10-QT": "Transition report (quarterly)",
    "25-NSE": "Delisting notice",
    "144": "Proposed insider sale",
    "15-12G": "Deregistration",
}


def form_label(form: str) -> str:
    return FORM_LABELS.get(form, form)


def create_app(settings: Settings | None = None, db: Database | None = None) -> FastAPI:
    s = settings or get_settings()
    storage = Storage(s.resolved_lake_root())
    database = db or Database(s.database_url, storage)
    limiter = RateLimiter(s.api_rate_limit_per_minute)
    auth = make_auth(s.api_key, limiter)
    if not s.api_key:
        log.warning("API_KEY is empty: the API is unauthenticated (dev mode)")

    app = FastAPI(title="Filings Hub API", version=__version__, docs_url="/docs")
    app.state.db = database

    def resolve_cik(cik: str) -> int:
        if cik.isdigit():
            return int(cik)
        rows = database.query(
            "SELECT cik FROM tickers WHERE ticker = ? ORDER BY is_primary DESC LIMIT 1",
            [cik.upper()],
        )
        if not rows:
            raise HTTPException(404, f"unknown ticker {cik}")
        return int(rows[0]["cik"])

    @app.get("/health")
    def health() -> dict[str, Any]:
        runs = database.query("SELECT run_id, status, finished_at FROM run_log ORDER BY started_at DESC LIMIT 1")
        return {
            "status": "ok",
            "version": __version__,
            "backend": database.backend,
            "last_run": runs[0] if runs else None,
        }

    @app.get("/search")
    def search(q: str = Query(min_length=1), limit: int = Query(20, le=100), _: str = Depends(auth)) -> dict[str, Any]:
        like = f"%{q.lower()}%"
        rows = database.query(
            "SELECT c.cik, c.name, c.ticker, c.exchange, c.sic_description, c.is_active, c.last_financial_report_date "
            "FROM companies c WHERE lower(c.name) LIKE ? OR c.ticker = ? OR CAST(c.cik AS VARCHAR) = ? "
            "OR c.cik IN (SELECT cik FROM tickers WHERE ticker = ?) "
            "ORDER BY (c.ticker = ?) DESC, c.is_active DESC, c.filing_count DESC LIMIT ?",
            [like, q.upper(), q, q.upper(), q.upper(), limit],
        )
        return {"query": q, "results": rows}

    @app.get("/companies/{cik}")
    def company(cik: str, _: str = Depends(auth)) -> dict[str, Any]:
        c = resolve_cik(cik)
        rows = database.query("SELECT * FROM companies WHERE cik = ?", [c])
        if not rows:
            raise HTTPException(404, f"unknown CIK {c}")
        tickers = database.query(
            "SELECT ticker, exchange, is_primary FROM tickers WHERE cik = ? ORDER BY is_primary DESC, ticker",
            [c],
        )
        periods = database.query(
            f"SELECT * FROM {database.periods_table} WHERE cik = ? ORDER BY period_end DESC LIMIT 12",
            [c],
        )
        latest = periods[0] if periods else None
        nxt = next_expected_results(periods) if periods else None
        return {
            "company": rows[0],
            "tickers": tickers,
            "latest_period": latest,
            "next_expected": nxt,
        }

    @app.get("/companies/{cik}/periods")
    def company_periods(cik: str, limit: int = Query(40, le=400), _: str = Depends(auth)) -> dict[str, Any]:
        c = resolve_cik(cik)
        rows = database.query(
            f"SELECT p.*, f.filing_index_url AS results_filing_index_url, "
            f"e.filing_index_url AS earnings_release_filing_index_url "
            f"FROM {database.periods_table} p LEFT JOIN filings f ON f.accession = p.results_accession "
            f"LEFT JOIN filings e ON e.accession = p.earnings_release_accession "
            f"WHERE p.cik = ? ORDER BY p.period_end DESC LIMIT ?",
            [c, limit],
        )
        return {"cik": c, "periods": rows}

    @app.get("/companies/{cik}/filings")
    def company_filings(
        cik: str,
        form: str | None = None,
        from_: date | None = Query(None, alias="from"),
        to: date | None = None,
        limit: int = Query(100, le=1000),
        _: str = Depends(auth),
    ) -> dict[str, Any]:
        c = resolve_cik(cik)
        sql = (
            "SELECT accession, form, filed_date, report_date, items, primary_doc_url, filing_index_url, "
            "primary_doc_description FROM filings WHERE cik = ?"
        )
        params: list[Any] = [c]
        if form:
            sql += " AND form = ?"
            params.append(form)
        if from_:
            sql += " AND filed_date >= ?"
            params.append(from_)
        if to:
            sql += " AND filed_date <= ?"
            params.append(to)
        sql += " ORDER BY filed_date DESC, accession DESC LIMIT ?"
        params.append(limit)
        rows = database.query(sql, params)
        for r in rows:
            r["label"] = form_label(r["form"])
        return {"cik": c, "filings": rows}

    def _labels(periods: str | None) -> list[str] | None:
        return [p.strip() for p in periods.split(",") if p.strip()] if periods else None

    @app.get("/companies/{cik}/statements")
    def company_statements(
        cik: str, periods: str | None = None, limit: int = Query(8, le=60), _: str = Depends(auth)
    ) -> dict[str, Any]:
        c = resolve_cik(cik)
        try:
            return build_grid(database, c, _labels(periods), limit).to_dict()
        except KeyError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/companies/{cik}/export.xlsx")
    def company_export(
        cik: str, periods: str | None = None, limit: int = Query(8, le=60), _: str = Depends(auth)
    ) -> Response:
        c = resolve_cik(cik)
        try:
            data = export_excel(database, c, _labels(periods), limit)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        name = database.query("SELECT ticker, name FROM companies WHERE cik = ?", [c])[0]
        fname = (name["ticker"] or str(c)) + "-statements.xlsx"
        return Response(
            data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    @app.get("/companies/{cik}/facts")
    def company_facts(
        cik: str,
        concept: str = Query(min_length=1),
        unit: str | None = None,
        history: bool = False,
        _: str = Depends(auth),
    ) -> dict[str, Any]:
        c = resolve_cik(cik)
        duck = database.facts_duck()
        if not duck.view("cik_facts", f"{layout.facts_cik_dir(c)}/*.parquet"):
            return {"cik": c, "concept": concept, "facts": []}
        sql = (
            "SELECT taxonomy, concept, unit, period_start, period_end, duration_kind, value, accession, form, filed, "
            "fy, fp, frame, is_current FROM cik_facts WHERE concept = ?"
        )
        params: list[Any] = [concept]
        if unit:
            sql += " AND unit = ?"
            params.append(unit)
        if not history:
            sql += " AND is_current"
        sql += " ORDER BY period_end, period_start NULLS FIRST, filed"
        return {"cik": c, "concept": concept, "facts": duck.fetch_dicts(sql, params)}

    return app


def app_factory() -> FastAPI:
    return create_app()
