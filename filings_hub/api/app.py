"""FastAPI application.

GET /search?q=                                     companies
GET /companies/{cik}                               profile + latest period + next expected results
GET /companies/{cik}/periods                       period spine with attached filings
GET /companies/{cik}/filings?form=&from=&to=       other filings
GET /companies/{cik}/statements?periods=           as-reported lines (grid)
GET /companies/{cik}/export.xlsx?periods=          workbook
GET /companies/{cik}/facts?concept=                XBRL fact history from the lake (restatements)
GET /companies/{cik}/documents?accessions=         exhibit-level contents of filings, plain names
GET /companies/{cik}/filings/{acc}/document?file=  a filing document, sanitised, with a table of contents
GET /companies/{cik}/search?q=                     phrase search inside the company's results filings
GET /companies/{cik}/peers                         same industry, by size
GET /filings/recent?ciks=                          what the followed companies filed lately
POST /subscriptions                                email alerts for followed companies
POST /requests                                     coverage requests (other regions)
POST /auth/magic-link · /auth/verify · /auth/google  sign in; GET /auth/config
GET /me; GET/PUT/DELETE /me/prefs; GET /me/prefs/resolve; POST /me/prefs/export · /import · /reset
GET /health
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import date, timedelta
from typing import Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Response

from filings_hub import __version__, accounts, tenancy
from filings_hub.api.security import RateLimiter, make_auth
from filings_hub.config import Settings, get_settings
from filings_hub.db.database import Database
from filings_hub.export.excel import ExportOptions, export_workbook
from filings_hub.export.grid import COLUMN_ORDERS, PERIOD_MODES, build_grid
from filings_hub.ingest import digest, documents
from filings_hub.ingest.edgar_client import EdgarClient, EdgarError, client_from_settings
from filings_hub.ingest.metrics import METRIC_LABELS, METRIC_NAMES, headline_preset, period_metrics
from filings_hub.ingest.periods import base_form, next_expected_results
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage
from filings_hub.reader import DocumentCache, render_document, search_text

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
    "3/A": "Initial insider holdings (amended)",
    "4/A": "Insider transaction (amended)",
    "5": "Annual insider disclosure",
    "5/A": "Annual insider disclosure (amended)",
    "13F-HR": "Institutional reported holdings",
    "13F-HR/A": "Institutional reported holdings (amended)",
    "13F-NT": "Institutional holdings notice",
    "13F-NT/A": "Institutional holdings notice (amended)",
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


for _schedule in ("SC 13D", "SC 13G", "SCHEDULE 13D", "SCHEDULE 13G"):
    FORM_LABELS[_schedule] = "Major beneficial ownership disclosure"
    FORM_LABELS[_schedule + "/A"] = "Major beneficial ownership disclosure (amended)"


def form_label(form: str) -> str:
    return FORM_LABELS.get(form, form)


# One UNION branch per identifier so each can use an index: a single OR across name, ticker and CIK
# forces a sequential scan over the whole ~900k-company universe (measured: 200 ms, vs 0.4 ms here).
# The name branch is capped because a very generic term ("capital", "holdings") can match a six-figure
# number of companies and ranking them all costs more than the scan it replaced. Below the cap the
# ranking is exact, which covers every query that is not a bare industry word; exact ticker and CIK
# matches are in their own uncapped branches, so they are never dropped.
SEARCH_CANDIDATE_CAP = 5000

SEARCH_SQL = f"""
WITH matches AS (
    (SELECT cik FROM companies WHERE lower(name) LIKE ? LIMIT {SEARCH_CANDIDATE_CAP})
    UNION
    SELECT cik FROM companies WHERE ticker = ?
    UNION
    SELECT cik FROM tickers WHERE ticker = ?
    UNION
    SELECT cik FROM companies WHERE cik = ?
)
SELECT c.cik, c.name, c.ticker, c.exchange, c.sic_description, c.is_active, c.last_financial_report_date
FROM companies c JOIN matches m ON m.cik = c.cik
ORDER BY (c.ticker = ?) DESC, c.is_active DESC, c.filing_count DESC
LIMIT ?
"""


def search_params(q: str, limit: int) -> list[Any]:
    """Positional parameters for SEARCH_SQL. A non-numeric query passes NULL to the CIK branch so it
    matches nothing, rather than casting every CIK to text (which no index can serve)."""
    sym = q.strip().upper()
    cik = int(q) if q.strip().isdigit() else None
    return [f"%{q.strip().lower()}%", sym, sym, cik, sym, limit]


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def create_app(
    settings: Settings | None = None,
    db: Database | None = None,
    edgar_client: EdgarClient | None = None,
    research_provider=None,
) -> FastAPI:
    s = settings or get_settings()
    storage = Storage(s.resolved_lake_root())
    database = db or Database(s.database_url, storage, lazy_remote_views=True)
    if database.is_remote_lake:
        import threading

        threading.Thread(target=database.warm, name="filings-warm", daemon=True).start()
    try:
        universe = database.query("SELECT count(*) AS n FROM companies")[0]["n"]
    except Exception:  # pragma: no cover - a broken lake is reported by the first request instead
        universe = None
    if not universe:
        # A service pointed at the wrong place (the image's default LAKE_ROOT=/data, an unset
        # environment group) comes up healthy and serves an empty site; say so where the
        # platform's log is read. /health carries the same facts under "lake".
        log.warning(
            "serving from %s, which has no companies table: check LAKE_ROOT and the storage credentials",
            storage.root,
        )
    limiter = RateLimiter(s.api_rate_limit_per_minute)
    if not s.api_key:
        log.warning("API_KEY is empty: the API is unauthenticated (dev mode)")
    client = edgar_client
    if client is None and "@" in (s.sec_user_agent or ""):
        client = client_from_settings()
    docs_cache = DocumentCache(storage, client)
    users = accounts.store_from_settings(storage, s.database_url)
    account_security = tenancy.SecurityStore(users, storage, s.database_url)
    signer = accounts.SessionSigner(s.session_secret, s.session_days, account_security)
    auth = make_auth(s.api_key, limiter, signer.verify)
    admin_emails = {email.strip().lower() for email in s.admin_emails.split(",") if email.strip()}
    magic_limiter = RateLimiter(3)

    app = FastAPI(title="Disclosure API", version=__version__, docs_url="/docs")

    @app.middleware("http")
    async def _timing(request, call_next):  # type: ignore[no-untyped-def]
        # One line per request with its duration: on a hosted instance the platform's log is the
        # only way to tell a slow lake read from a slow page render.
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        if request.url.path != "/health" or elapsed_ms > 1000:
            log.info("%s %s -> %s in %.0f ms", request.method, request.url.path, response.status_code, elapsed_ms)
        response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.0f}"
        return response

    app.state.db = database
    app.state.edgar = client
    app.state.users = users
    app.state.signer = signer
    app.state.account_security = account_security
    from filings_hub.api.admin import attach_admin
    from filings_hub.platform_admin import AdminStore

    platform_admin = AdminStore(account_security, s)
    users.registration_policy = platform_admin.registration_policy
    attach_admin(app, platform_admin, database)

    def current_user(
        _: str = Depends(auth), x_session: str | None = Header(default=None, alias="X-Session")
    ) -> accounts.User:
        uid = signer.verify(x_session)
        user = users.get_user(uid) if uid else None
        if user is None:
            raise HTTPException(401, "sign in required")
        return user

    def current_admin(user: accounts.User = Depends(current_user)) -> accounts.User:
        if user.email.lower() not in admin_emails:
            raise HTTPException(403, "administrator access required")
        return user

    app.include_router(tenancy.security_router(account_security, signer, current_user))
    from filings_hub.launch import LaunchStore, launch_router

    launch = LaunchStore(account_security, identity_secret=s.session_secret)
    app.state.launch = launch
    app.include_router(launch_router(launch, auth, current_user))
    from filings_hub import projects

    app.include_router(projects.project_router(account_security, current_user))
    from filings_hub.api.ownership import attach_ownership_routes

    attach_ownership_routes(app, database=database, storage=storage, auth=auth)

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
        # Never wait on the lake: the platform's health check decides whether the service is
        # reachable at all, and a warm-up or a slow read on another thread must not fail it.
        runs = database.query_if_idle(
            "SELECT run_id, status, finished_at FROM run_log ORDER BY started_at DESC LIMIT 1", timeout=1.0
        )
        companies = None if runs is None else database.query_if_idle("SELECT count(*) AS n FROM companies", timeout=1.0)
        return {
            "status": "ok",
            "version": __version__,
            "backend": database.backend,
            "last_run": runs[0] if runs else None,
            "busy": runs is None,
            # what the service is actually serving from, so an empty site can be diagnosed from
            # this one response: the lake it was pointed at, whether the universe table arrived,
            # and whether the background bind of the filings table has finished
            "lake": {
                "root": storage.root,
                "remote": database.is_remote_lake,
                "companies": companies[0]["n"] if companies else None,
                "filings_ready": getattr(database, "filings_ready", True),
            },
        }

    @app.get("/search")
    def search(q: str = Query(min_length=1), limit: int = Query(20, le=100), _: str = Depends(auth)) -> dict[str, Any]:
        database.maybe_resync()
        rows = database.query(SEARCH_SQL, search_params(q, limit))
        return {"query": q, "results": rows}

    @app.get("/companies/{cik}")
    def company(cik: str, _: str = Depends(auth)) -> dict[str, Any]:
        database.maybe_resync()
        c = resolve_cik(cik)
        with database.read_snapshot() as reader:
            rows = reader.query("SELECT * FROM companies WHERE cik = ?", [c])
            if not rows:
                raise HTTPException(404, f"unknown CIK {c}")
            tickers = reader.query(
                "SELECT ticker, exchange, is_primary FROM tickers WHERE cik = ? ORDER BY is_primary DESC, ticker",
                [c],
            )
            periods = reader.query(
                f"SELECT * FROM {reader.periods_table_for(c)} WHERE cik = ? ORDER BY period_end DESC LIMIT 12",
                [c],
            )
            latest = periods[0] if periods else None
            nxt = next_expected_results(periods) if periods else None
            return {
                "company": rows[0],
                "tickers": tickers,
                "latest_period": latest,
                "next_expected": nxt,
                "headline_preset": headline_preset(rows[0].get("sic")),
                "metric_labels": METRIC_LABELS,
            }

    @app.get("/companies/{cik}/periods")
    def company_periods(cik: str, limit: int = Query(40, le=400), _: str = Depends(auth)) -> dict[str, Any]:
        c = resolve_cik(cik)
        with database.read_snapshot() as reader:
            rows = reader.query(
                f"SELECT p.*, f.filing_index_url AS results_filing_index_url, "
                f"e.filing_index_url AS earnings_release_filing_index_url "
                f"FROM {reader.periods_table_for(c)} p LEFT JOIN filings f "
                f"ON f.accession = p.results_accession AND f.cik = p.cik "
                f"LEFT JOIN filings e ON e.accession = p.earnings_release_accession AND e.cik = p.cik "
                f"WHERE p.cik = ? ORDER BY p.period_end DESC LIMIT ?",
                [c, limit],
            )
            metrics = period_metrics(reader.query, c, reader.table("statements", c))
            for r in rows:
                r["metrics"] = metrics.get(r["results_accession"]) or dict.fromkeys(METRIC_NAMES)
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

    def _grid_params(period_mode: str, column_order: str) -> None:
        if period_mode not in PERIOD_MODES:
            raise HTTPException(422, f"period_mode must be one of {', '.join(PERIOD_MODES)}")
        if column_order not in COLUMN_ORDERS:
            raise HTTPException(422, f"column_order must be one of {', '.join(COLUMN_ORDERS)}")

    @app.get("/companies/{cik}/statements")
    def company_statements(
        cik: str,
        periods: str | None = None,
        limit: int = Query(8, le=60),
        period_mode: str = "as_filed",
        restated: bool = False,
        column_order: str = "newest_right",
        as_of: date | None = None,
        _: str = Depends(auth),
    ) -> dict[str, Any]:
        """The statement grid. `period_mode`: as_filed | quarterly | annual | ltm; `restated` takes
        comparatives from the latest filing that presents the period (as-filed and annual modes)."""
        c = resolve_cik(cik)
        _grid_params(period_mode, column_order)
        try:
            return build_grid(
                database,
                c,
                _labels(periods),
                limit,
                period_mode=period_mode,
                restated=restated,
                column_order=column_order,
                as_of=as_of,
            ).to_dict()
        except KeyError as e:
            raise HTTPException(404, str(e)) from e

    def _export_options(
        layout: str | None,
        orientation: str | None,
        subtotals: str | None,
        include: str | None,
        scale: str | None,
        negative_style: str | None,
        filename: str | None,
        statements: str | None,
    ) -> ExportOptions:
        """Export options from query parameters. `include` is a comma list drawn from
        source, checks, concepts, filed_dates; leaving it out keeps everything."""
        d: dict[str, Any] = {
            "layout": layout,
            "orientation": orientation,
            "subtotals": subtotals,
            "scale": scale,
            "negative_style": negative_style,
            "filename": filename,
            "statements": statements,
        }
        if include is not None:
            wanted = {w.strip() for w in include.split(",") if w.strip()}
            for k in ("source", "checks", "concepts", "filed_dates"):
                d[f"include_{k}"] = k in wanted
        try:
            return ExportOptions.from_dict(d)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @app.get("/companies/{cik}/export.xlsx")
    def company_export(
        cik: str,
        periods: str | None = None,
        limit: int = Query(8, le=60),
        period_mode: str = "as_filed",
        restated: bool = False,
        column_order: str = "newest_right",
        as_of: date | None = None,
        layout: str | None = None,
        orientation: str | None = None,
        subtotals: str | None = None,
        include: str | None = None,
        scale: str | None = None,
        negative_style: str | None = None,
        filename: str | None = None,
        statements: str | None = None,
        _: str = Depends(auth),
    ) -> Response:
        c = resolve_cik(cik)
        _grid_params(period_mode, column_order)
        opts = _export_options(layout, orientation, subtotals, include, scale, negative_style, filename, statements)
        try:
            data, fname = export_workbook(
                database, c, _labels(periods), limit, opts, period_mode, restated, column_order, as_of
            )
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
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

    @app.get("/companies/{cik}/peers")
    def company_peers(cik: str, limit: int = Query(12, le=50), _: str = Depends(auth)) -> dict[str, Any]:
        """Same industry code, biggest first (latest annual revenue, else total assets)."""
        c = resolve_cik(cik)
        me = database.query("SELECT sic, sic_description FROM companies WHERE cik = ?", [c])
        if not me:
            raise HTTPException(404, f"unknown CIK {c}")
        sic = me[0]["sic"]
        peers = (
            database.query(
                "SELECT c.cik, c.name, c.ticker, c.exchange, m.fiscal_year, m.revenue, m.net_income, m.total_assets "
                "FROM companies c LEFT JOIN company_metrics m ON m.cik = c.cik "
                "WHERE c.sic = ? AND c.cik <> ? AND c.is_active "
                "ORDER BY coalesce(m.revenue, m.total_assets, 0) DESC, c.filing_count DESC LIMIT ?",
                [sic, c, limit],
            )
            if sic
            else []
        )
        return {"cik": c, "sic": sic, "sic_description": me[0]["sic_description"], "peers": peers}

    def _filing_rows(c: int, accessions: list[str]) -> list[dict[str, Any]]:
        if not accessions:
            return []
        marks = ", ".join("?" for _ in accessions)
        return database.query(
            f"SELECT accession, form, items, primary_doc, primary_doc_url, filed_date FROM filings "
            f"WHERE cik = ? AND accession IN ({marks})",
            [c, *accessions],
        )

    def _period_accessions(c: int, limit: int) -> list[str]:
        """Results filings, earnings releases and amendments of the latest `limit` periods, newest first."""
        rows = database.query(
            f"SELECT results_accession, earnings_release_accession, amendment_accessions "
            f"FROM {database.periods_table_for(c)} WHERE cik = ? ORDER BY period_end DESC LIMIT ?",
            [c, limit],
        )
        out: list[str] = []
        for r in rows:
            for a in (r["results_accession"], r["earnings_release_accession"], *(r["amendment_accessions"] or [])):
                if a and a not in out:
                    out.append(a)
        return out

    @app.get("/companies/{cik}/documents")
    def company_documents(
        cik: str,
        accessions: str | None = None,
        limit: int = Query(8, le=60),
        all: bool = False,
        _: str = Depends(auth),
    ) -> dict[str, Any]:
        """Exhibit-level contents of filings with plain names, fetched from EDGAR once and kept."""
        c = resolve_cik(cik)
        accs = [a.strip() for a in accessions.split(",") if a.strip()] if accessions else _period_accessions(c, limit)
        filings = _filing_rows(c, accs)
        table, failures = documents.ensure_documents(storage, client, c, filings)
        grouped: dict[str, list[dict[str, Any]]] = {a: [] for a in accs}
        for d in sorted(table.to_pylist(), key=lambda d: (d["rank"], d["seq"])):
            if d["kind"] == "support" and not all:
                continue
            grouped.setdefault(d["accession"], []).append(
                {
                    k: d[k]
                    for k in (
                        "seq",
                        "doc_type",
                        "description",
                        "filename",
                        "url",
                        "size",
                        "label",
                        "kind",
                        "is_primary",
                    )
                }
            )
        return {"cik": c, "documents": grouped, "failures": failures, "fetch_enabled": client is not None}

    @app.get("/companies/{cik}/filings/{accession}/document")
    def filing_document(cik: str, accession: str, file: str | None = None, _: str = Depends(auth)) -> dict[str, Any]:
        """A filing document, sanitised for the reader, with a table of contents."""
        c = resolve_cik(cik)
        rows = _filing_rows(c, [accession])
        if not rows:
            raise HTTPException(404, f"unknown filing {accession}")
        filename = file or rows[0]["primary_doc"]
        if not filename or "/" in filename or ".." in filename:
            raise HTTPException(404, "no document")
        try:
            raw = docs_cache.fetch_document(c, accession, filename)
        except (EdgarError, RuntimeError) as e:
            raise HTTPException(502, f"could not fetch the document from EDGAR: {e}") from e
        folder = documents.document_url(c, accession, "")
        rendered = render_document(raw.decode("utf-8", errors="replace"), folder)
        return {
            "cik": c,
            "accession": accession,
            "form": rows[0]["form"],
            "filed_date": rows[0]["filed_date"],
            "filename": filename,
            "source_url": documents.document_url(c, accession, filename),
            **rendered,
        }

    @app.get("/companies/{cik}/search")
    def company_search(
        cik: str, q: str = Query(min_length=2, max_length=200), filings: int = Query(20, le=40), _: str = Depends(auth)
    ) -> dict[str, Any]:
        """Where did they last mention it: phrase search over the company's results filings and
        earnings releases, newest first, with context."""
        c = resolve_cik(cik)
        accs = _period_accessions(c, filings)
        rows = {r["accession"]: r for r in _filing_rows(c, accs)}
        table, _f = documents.ensure_documents(storage, client, c, list(rows.values()))
        docs = table.to_pylist()
        results = []
        searched = 0
        for a in accs:
            r = rows.get(a)
            if not r:
                continue
            form = base_form(r["form"] or "")
            # the release exhibit for an 8-K, the report itself otherwise
            target = r["primary_doc"]
            label = form_label(r["form"])
            if form == "8-K":
                rel = [d for d in docs if d["accession"] == a and d["kind"] == "release"]
                if rel:
                    target, label = rel[0]["filename"], rel[0]["label"]
            if not target:
                continue
            try:
                text = docs_cache.fetch_text(c, a, target)
            except (EdgarError, RuntimeError) as e:
                log.warning("search: could not fetch %s/%s: %s", a, target, e)
                continue
            searched += 1
            hits = search_text(text, q)
            if hits:
                results.append(
                    {
                        "accession": a,
                        "form": r["form"],
                        "label": label,
                        "filed_date": r["filed_date"],
                        "filename": target,
                        "hits": hits,
                    }
                )
        return {"cik": c, "query": q, "searched": searched, "results": results, "fetch_enabled": client is not None}

    @app.get("/filings/recent")
    def recent_filings(
        ciks: str = Query(min_length=1),
        days: int = Query(7, le=90),
        since: date | None = None,
        limit: int = Query(100, le=500),
        _: str = Depends(auth),
    ) -> dict[str, Any]:
        """What the followed companies filed since `since` (default: the last `days` days), newest first."""
        ids = sorted({int(x) for x in ciks.split(",") if x.strip().isdigit()})[:200]
        if not ids:
            return {"filings": []}
        marks = ", ".join("?" for _ in ids)
        rows = database.query(
            f"SELECT f.cik, c.name, c.ticker, f.accession, f.form, f.filed_date, f.items, f.primary_doc_url, "
            f"f.filing_index_url FROM filings f LEFT JOIN companies c ON c.cik = f.cik "
            f"WHERE f.cik IN ({marks}) AND f.filed_date >= ? "
            f"ORDER BY f.filed_date DESC, f.accession DESC LIMIT ?",
            [*ids, since or (date.today() - timedelta(days=days)), limit],
        )
        for r in rows:
            r["label"] = form_label(r["form"])
            r["is_results"] = digest.is_results_filing(r)
        return {"filings": rows}

    def _store(rel: str, payload: dict[str, Any]) -> None:
        import json

        try:
            storage.write_text(rel, json.dumps(payload))
        except Exception as e:
            log.warning("could not store %s: %s", rel, e)
            raise HTTPException(503, "this deployment cannot store submissions (read-only lake)") from e

    @app.post("/subscriptions")
    def subscribe(payload: dict[str, Any] = Body(...), user: accounts.User = Depends(current_user)) -> dict[str, Any]:
        if not s.smtp_host and not s.auth_dev_links:
            raise HTTPException(503, "email delivery is not configured on this deployment")
        email = user.email
        ciks = payload.get("ciks") or []
        if payload.get("email") and str(payload["email"]).strip().lower() != email.lower():
            raise HTTPException(403, "alerts can only be sent to your verified account email")
        if not isinstance(ciks, list) or not all(str(c).isdigit() for c in ciks) or not 0 < len(ciks) <= 200:
            raise HTTPException(422, "ciks must be a list of 1 to 200 CIKs")
        flows = payload.get("ownership_flows", [])
        allowed_flows = {"insiders", "institutions", "events"}
        if not isinstance(flows, list) or any(not isinstance(f, str) or f not in allowed_flows for f in flows):
            raise HTTPException(422, "ownership_flows must contain insiders, institutions or events")
        import json

        previous_path = f"{layout.SUBSCRIPTIONS}/{digest.subscription_id(email)}.json"
        previous = json.loads(storage.read_text(previous_path)) if storage.exists(previous_path) else {}
        started = previous.get("ownership_started") or {}
        rec = {
            "ownership_flows": sorted(set(flows)),
            "ownership_started": {f: started.get(f, date.today().isoformat()) for f in flows},
            "email": email.lower(),
            "ciks": sorted({int(c) for c in ciks}),
            "created": date.today().isoformat(),
            "user_id": user.id,
        }
        _store(f"{layout.SUBSCRIPTIONS}/{digest.subscription_id(email)}.json", rec)
        return {"stored": True, "email": rec["email"], "ciks": len(rec["ciks"])}

    @app.get("/subscriptions")
    def subscription(user: accounts.User = Depends(current_user)) -> dict[str, Any]:
        import json

        path = f"{layout.SUBSCRIPTIONS}/{digest.subscription_id(user.email)}.json"
        if not storage.exists(path):
            return {"subscribed": False, "ciks": [], "ownership_flows": []}
        record = json.loads(storage.read_text(path))
        return {
            "subscribed": True,
            "ciks": record.get("ciks", []),
            "ownership_flows": record.get("ownership_flows", []),
        }

    @app.delete("/subscriptions")
    def unsubscribe(user: accounts.User = Depends(current_user)) -> dict[str, Any]:
        path = f"{layout.SUBSCRIPTIONS}/{digest.subscription_id(user.email)}.json"
        if storage.exists(path):
            storage.delete(path)
        return {"subscribed": False, "ciks": [], "ownership_flows": []}

    @app.post("/requests")
    def coverage_request(payload: dict[str, Any] = Body(...), _: str = Depends(auth)) -> dict[str, Any]:
        region = str(payload.get("region") or "").strip()[:40]
        note = str(payload.get("note") or "").strip()[:2000]
        email = str(payload.get("email") or "").strip()[:200]
        if not region or not note:
            raise HTTPException(422, "region and note are required")
        rid = uuid.uuid4().hex[:12]
        _store(f"{layout.REQUESTS}/{rid}.json", {"id": rid, "region": region, "note": note, "email": email})
        return {"stored": True, "id": rid}

    # -- accounts ----------------------------------------------------------------------------------
    def return_context(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            context = accounts.auth_return_context(payload.get("next"), payload.get("region"))
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return {"next_path": context.get("next"), "region": context.get("region")}

    @app.get("/auth/config")
    def auth_config(_: str = Depends(auth)) -> dict[str, Any]:
        return {
            "email_link": bool(s.smtp_host) or s.auth_dev_links,
            "google_client_id": s.google_client_id or None,
            "site_url": s.site_url,
            "business_email_only": platform_admin.configuration()["business_email_only"],
            "new_registration_enabled": platform_admin.configuration()["new_registration_enabled"],
        }

    @app.post("/auth/magic-link")
    def magic_link(payload: dict[str, Any] = Body(...), _: str = Depends(auth)) -> dict[str, Any]:
        context = return_context(payload)
        email = str(payload.get("email") or "").strip().lower()
        if not EMAIL_RE.match(email):
            raise HTTPException(422, "a valid email is required")
        platform_admin.registration_policy(email)
        ok, retry = magic_limiter.check(email)
        if not ok:
            raise HTTPException(429, f"too many links requested; try again in {retry}s")
        try:
            _token, link = accounts.issue_magic_link(users, email, s.site_url, **context)
        except Exception as e:
            log.warning("could not store sign-in token: %s", e)
            raise HTTPException(503, "sign-in is not enabled on this deployment (read-only lake)") from e
        out: dict[str, Any] = {"sent": False}
        if s.smtp_host:
            from filings_hub.ingest.alerts import send_email

            body = (
                "Sign in to Disclosure with this link (valid for 15 minutes):\n\n"
                f"{link}\n\nIf you did not ask for it, ignore this email."
            )
            try:
                out["sent"] = send_email(email, "Your Disclosure sign-in link", body, s)
            except Exception as e:
                log.error("magic link email failed: %s", e)
        if s.auth_dev_links:
            out["dev_link"] = link
        if not out["sent"] and not s.auth_dev_links:
            raise HTTPException(503, "email sign-in is not configured (SMTP_HOST)")
        return out

    @app.post("/auth/signup")
    def signup(payload: dict[str, Any] = Body(...), _: str = Depends(auth)) -> dict[str, Any]:
        """New account: the profile rides with the sign-in link and lands on the user when it is redeemed."""
        context = return_context(payload)
        problem = accounts.validate_signup(payload, platform_admin.configuration()["business_email_only"])
        if problem:
            raise HTTPException(422, problem)
        email = str(payload["email"]).strip().lower()
        platform_admin.registration_policy(email)
        ok, retry = magic_limiter.check(email)
        if not ok:
            raise HTTPException(429, f"too many links requested; try again in {retry}s")
        profile = {k: str(payload.get(k) or "").strip()[:200] for k in accounts.PROFILE_FIELDS}
        profile["marketing_opt_in"] = bool(payload.get("marketing_opt_in"))
        profile["terms_accepted_at"] = date.today().isoformat()
        try:
            _token, link = accounts.issue_magic_link(users, email, s.site_url, profile, **context)
        except Exception as e:
            log.warning("could not store sign-up token: %s", e)
            raise HTTPException(503, "sign-up is not enabled on this deployment (read-only lake)") from e
        out: dict[str, Any] = {"sent": False}
        if s.smtp_host:
            from filings_hub.ingest.alerts import send_email

            body = (
                f"Welcome to Disclosure, {profile['first_name']}.\n\nFinish creating your account with this link "
                f"(valid for 15 minutes):\n\n{link}\n\nIf you did not sign up, ignore this email."
            )
            try:
                out["sent"] = send_email(email, "Finish creating your Disclosure account", body, s)
            except Exception as e:
                log.error("sign-up email failed: %s", e)
        if s.auth_dev_links:
            out["dev_link"] = link
        if not out["sent"] and not s.auth_dev_links:
            raise HTTPException(503, "email sign-in is not configured (SMTP_HOST)")
        return out

    @app.post("/auth/verify")
    def verify_link(
        payload: dict[str, Any] = Body(...), _: str = Depends(auth), user_agent: str = Header(default="")
    ) -> dict[str, Any]:
        token = str(payload.get("token") or "")
        user = accounts.redeem_magic_link(users, token) if token else None
        if user is None:
            raise HTTPException(401, "that sign-in link is invalid or has expired")
        return {
            "session": signer.sign(user.id, device_label=str(payload.get("device_label") or user_agent)),
            "user": user.to_dict(),
        }

    @app.post("/auth/google")
    def google_signin(
        payload: dict[str, Any] = Body(...), _: str = Depends(auth), user_agent: str = Header(default="")
    ) -> dict[str, Any]:
        if not (s.google_client_id and s.google_client_secret):
            raise HTTPException(503, "Google sign-in is not configured")
        code = str(payload.get("code") or "")
        redirect_uri = str(payload.get("redirect_uri") or "")
        email = accounts.google_email_for_code(
            code, redirect_uri, s.google_client_id, s.google_client_secret, http=getattr(app.state, "google_http", None)
        )
        if not email:
            raise HTTPException(401, "Google did not confirm an email for that code")
        user = accounts.get_or_create_user(users, email)
        return {
            "session": signer.sign(user.id, device_label=str(payload.get("device_label") or user_agent)),
            "user": user.to_dict(),
        }

    @app.get("/me")
    def me(user: accounts.User = Depends(current_user)) -> dict[str, Any]:
        return {"user": {**user.to_dict(), "is_admin": user.email.lower() in admin_emails}}

    # -- preferences -------------------------------------------------------------------------------
    @app.get("/me/watchlist")
    def get_watchlist(user: accounts.User = Depends(current_user)) -> dict[str, Any]:
        value = next((p.value for p in users.list_prefs(user.id) if p.ident == ("global", "", "watchlist")), [])
        return {"user_id": user.id, "companies": value if isinstance(value, list) else []}

    @app.post("/me/watchlist")
    def mutate_watchlist(
        payload: dict[str, Any] = Body(...), user: accounts.User = Depends(current_user)
    ) -> dict[str, Any]:
        if payload.get("expected_user_id") != user.id:
            raise HTTPException(409, "account changed; reload the watchlist before making changes")
        action = payload.get("action")
        if action not in ("toggle", "remove"):
            raise HTTPException(422, "action must be toggle or remove")
        cik = payload.get("cik")
        if type(cik) is not int or cik <= 0:
            raise HTTPException(422, "a positive integer CIK is required")
        rows = database.query("SELECT cik, name, ticker FROM companies WHERE cik = ?", [cik])
        if action == "toggle" and not rows:
            raise HTTPException(404, "company not found")
        company = rows[0] if rows else {"cik": cik, "name": "", "ticker": None}
        try:
            companies = users.mutate_watchlist(user.id, company, action)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"user_id": user.id, "companies": companies, "followed": any(c.get("cik") == cik for c in companies)}

    @app.get("/me/prefs")
    def list_prefs(user: accounts.User = Depends(current_user)) -> dict[str, Any]:
        return {
            "user_id": user.id,
            "prefs": [p.to_dict() for p in users.list_prefs(user.id)],
            "defaults": accounts.DEFAULTS,
        }

    @app.put("/me/prefs")
    def put_pref(payload: dict[str, Any] = Body(...), user: accounts.User = Depends(current_user)) -> dict[str, Any]:
        scope = str(payload.get("scope") or "global")
        scope_key = str(payload.get("scope_key") or "")
        key = str(payload.get("key") or "")
        source = str(payload.get("source") or "explicit")
        value = payload.get("value")
        problem = accounts.validate_pref(scope, scope_key, key, value, source)
        if problem:
            raise HTTPException(422, problem)
        old = next((p.value for p in users.list_prefs(user.id) if p.ident == (scope, scope_key, key)), None)
        pref = accounts.Pref(scope=scope, scope_key=scope_key, key=key, value=value, source=source)
        users.put_pref(user.id, pref)
        users.add_event(
            user.id, {"key": key, "scope": scope, "old": old, "new": value, "source": source, "at": pref.updated_at}
        )
        return {"pref": pref.to_dict()}

    @app.delete("/me/prefs")
    def delete_pref(
        scope: str, key: str, scope_key: str = "", user: accounts.User = Depends(current_user)
    ) -> dict[str, Any]:
        """Reset one preference to its default (the scope below takes over)."""
        removed = users.delete_pref(user.id, scope, scope_key, key)
        return {"removed": removed}

    @app.get("/me/prefs/resolve")
    def resolve_prefs(
        cik: int | None = None,
        sic: str | None = None,
        statement: str | None = None,
        user: accounts.User = Depends(current_user),
    ) -> dict[str, Any]:
        """Every preference that applies to this context, with the scope that answered."""
        if cik is not None and sic is None:
            rows = database.query("SELECT sic FROM companies WHERE cik = ?", [cik])
            sic = rows[0]["sic"] if rows else None
        return {
            "context": {"cik": cik, "sic": sic, "statement": statement},
            "prefs": accounts.resolve(users.list_prefs(user.id), cik, sic, statement),
        }

    @app.post("/me/prefs/export")
    def export_prefs(user: accounts.User = Depends(current_user)) -> dict[str, Any]:
        return {"version": 1, "email": user.email, "prefs": [p.to_dict() for p in users.list_prefs(user.id)]}

    @app.post("/me/prefs/import")
    def import_prefs(
        payload: dict[str, Any] = Body(...), user: accounts.User = Depends(current_user)
    ) -> dict[str, Any]:
        prefs = payload.get("prefs")
        if not isinstance(prefs, list) or len(prefs) > 2000:
            raise HTTPException(422, "prefs must be a list (at most 2000)")
        n = 0
        for p in prefs:
            if not isinstance(p, dict):
                continue
            scope, sk, key = str(p.get("scope") or "global"), str(p.get("scope_key") or ""), str(p.get("key") or "")
            source = str(p.get("source") or "explicit")
            if accounts.validate_pref(scope, sk, key, p.get("value"), source):
                continue
            users.put_pref(
                user.id, accounts.Pref(scope=scope, scope_key=sk, key=key, value=p.get("value"), source=source)
            )
            n += 1
        return {"imported": n}

    @app.post("/me/prefs/reset")
    def reset_prefs(user: accounts.User = Depends(current_user)) -> dict[str, Any]:
        return {"removed": users.delete_all_prefs(user.id)}

    # -- UI events, proposals, the option touch report --------------------------------------------
    @app.post("/me/events")
    def post_event(payload: dict[str, Any] = Body(...), user: accounts.User = Depends(current_user)) -> dict[str, Any]:
        """A UI event (export downloaded, card swapped, proposal shown...). Stored with the preference
        events so the touch report sees both."""
        problem = accounts.validate_event(payload)
        if problem:
            raise HTTPException(422, problem)
        users.add_event(user.id, accounts.ui_event(str(payload["name"]), payload.get("props") or {}))
        return {"ok": True}

    @app.get("/me/proposals")
    def get_proposals(user: accounts.User = Depends(current_user)) -> dict[str, Any]:
        """Choices made on several companies that could become the default everywhere."""
        return {"proposals": accounts.proposals(users.list_prefs(user.id))}

    @app.post("/me/proposals")
    def act_on_proposal(
        payload: dict[str, Any] = Body(...), user: accounts.User = Depends(current_user)
    ) -> dict[str, Any]:
        key, action = str(payload.get("key") or ""), str(payload.get("action") or "")
        if key not in accounts.PROPOSABLE:
            raise HTTPException(422, f"key must be one of {', '.join(accounts.PROPOSABLE)}")
        if action == "accept":
            pref = accounts.accept_proposal(users, user.id, key, payload.get("value"))
            return {"accepted": True, "pref": pref.to_dict()}
        if action == "dismiss":
            return {"dismissed": accounts.dismiss_proposal(users, user.id, key, payload.get("value"))}
        raise HTTPException(422, "action must be accept or dismiss")

    @app.get("/metrics/prefs")
    def metrics_prefs(days: int = Query(30, ge=1, le=365), _: accounts.User = Depends(current_admin)) -> dict[str, Any]:
        """Which options people touch: preference writes by key, scope and value; UI events by name."""
        events = users.recent_events(days)
        return accounts.touch_report(events, days)

    @app.get("/coverage")
    def coverage(_: str = Depends(auth)) -> dict[str, Any]:
        from filings_hub.coverage import coverage_summary

        return coverage_summary(database)

    @app.get("/metrics")
    def metrics(days: int = Query(30, ge=1, le=365), _: accounts.User = Depends(current_admin)) -> dict[str, Any]:
        """Phase 4 dashboard feed: filings/day, refresh runs, checks pass rate."""
        filings_per_day = database.query(
            "SELECT filed_date, count(*) AS filings FROM filings "
            "WHERE filed_date >= (SELECT max(filed_date) FROM filings) - ? "
            "GROUP BY filed_date ORDER BY filed_date",
            [days],
        )
        runs = database.query(
            "SELECT run_id, kind, status, started_at, duration_seconds, index_dates, new_filings, ciks_refreshed, "
            "facts_rows, statements_built, fsds_quarters_loaded, db_loaded "
            "FROM run_log ORDER BY started_at DESC LIMIT ?",
            [days],
        )
        checks = (
            []
            if database.is_remote_lake
            else database.query(
                f"SELECT fiscal_year, count(*) AS periods, "
                f"sum(CASE WHEN checks_passed THEN 1 ELSE 0 END) AS passed, "
                f"sum(CASE WHEN checks_passed IS NOT NULL THEN 1 ELSE 0 END) AS applicable, "
                f"sum(CASE WHEN statements_source = 'facts_fallback' THEN 1 ELSE 0 END) AS provisional "
                f"FROM {database.periods_table} GROUP BY fiscal_year ORDER BY fiscal_year DESC LIMIT 10"
            )
        )
        for c in checks:
            c["pass_rate"] = (c["passed"] / c["applicable"]) if c["applicable"] else None
        totals = database.query(
            "SELECT (SELECT count(*) FROM companies) AS companies, (SELECT count(*) FROM filings) AS filings, "
            f"(SELECT count(*) FROM {'periods' if database.is_remote_lake else database.periods_table}) AS periods, "
            + (
                "NULL AS filings_with_statements"
                if database.is_remote_lake
                else "(SELECT count(DISTINCT accession) FROM statements) AS filings_with_statements"
            )
        )
        return {
            "totals": totals[0] if totals else {},
            "filings_per_day": filings_per_day,
            "runs": runs,
            "checks_by_fiscal_year": checks,
        }

    @app.get("/quality/failed")
    def quality_failed(
        limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), _: accounts.User = Depends(current_admin)
    ) -> dict[str, Any]:
        """Phase 4 data-quality queue: statements whose arithmetic checks failed, newest first."""
        if database.is_remote_lake:
            return {
                "total": None,
                "limit": limit,
                "offset": offset,
                "failed": [],
                "note": "The failed-checks queue scans every statement partition and is not served from a remote lake.",
            }
        rows = database.query(
            "SELECT k.accession, k.cik, c.name, c.ticker, k.statement, k.check_name, k.lhs, k.rhs, k.difference, "
            "k.detail, k.source, f.form, f.filed_date, f.filing_index_url "
            "FROM statement_checks k LEFT JOIN companies c ON c.cik = k.cik "
            "LEFT JOIN filings f ON f.accession = k.accession AND f.cik = k.cik "
            "WHERE NOT k.passed ORDER BY f.filed_date DESC NULLS LAST, k.accession, k.statement LIMIT ? OFFSET ?",
            [limit, offset],
        )
        total = database.query("SELECT count(*) AS n FROM statement_checks WHERE NOT passed")[0]["n"]
        return {"total": total, "limit": limit, "offset": offset, "failed": rows}

    from filings_hub.platform.catalog import attach_catalog_routes
    from filings_hub.platform.financials import attach_financial_routes

    attach_financial_routes(app, database=database, auth=auth, resolve_cik=resolve_cik)
    attach_catalog_routes(app, database=database, auth=auth)
    from filings_hub.api.research import attach_research_search_routes
    from filings_hub.platform.compare import attach_compare_routes

    get_research_index = attach_research_search_routes(app, database=database, storage=storage, auth=auth)
    from filings_hub.api.research_questions import attach_research_question_routes
    from filings_hub.research_provider import provider_from_settings

    research_provider = research_provider or provider_from_settings(s)
    attach_research_question_routes(
        app,
        get_index=get_research_index,
        security=account_security,
        provider=research_provider,
        auth=auth,
        current_user=current_user,
    )
    attach_compare_routes(app, database=database, auth=auth, resolve_cik=resolve_cik)
    return app


def app_factory() -> FastAPI:
    return create_app()
