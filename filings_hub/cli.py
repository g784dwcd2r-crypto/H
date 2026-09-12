"""Command line: backfill, refresh, export, load, api, demo."""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

import typer

from filings_hub.config import get_settings

app = typer.Typer(
    add_completion=False,
    help="Filings Hub: SEC EDGAR -> period hub -> as-reported statements -> Excel.",
)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _storage():
    from filings_hub.lake.storage import Storage

    return Storage(get_settings().resolved_lake_root())


@app.command()
def backfill(
    workers: int = typer.Option(4, help="processes for companyfacts parsing"),
    skip_download: bool = typer.Option(False, help="use the newest raw files already in the lake"),
    fsds_since: str = typer.Option("2009q1", help="first FSDS quarter to load (yyyyqn)"),
    load_db: bool = typer.Option(True, help="load serving tables into Postgres when DATABASE_URL is set"),
    verbose: bool = False,
) -> None:
    """Bulk backfill from empty lake to loaded serving tables."""
    _setup_logging(verbose)
    from filings_hub.ingest.backfill import run_backfill

    run = run_backfill(
        _storage(),
        workers=workers,
        skip_download=skip_download,
        fsds_since=fsds_since,
        load_db=load_db,
    )
    typer.echo(run.summary())
    raise typer.Exit(0 if run.status == "ok" else 1)


@app.command()
def refresh(
    index_date: str | None = typer.Option(
        None, "--date", help="daily index date (YYYY-MM-DD); default = catch up to yesterday"
    ),
    load_db: bool = typer.Option(True, help="load serving tables into Postgres when DATABASE_URL is set"),
    alert: bool = typer.Option(True, help="send alerts on failure / empty weekday"),
    verbose: bool = False,
) -> None:
    """Daily refresh: daily index -> new filings -> facts -> statements -> Postgres -> run_log."""
    _setup_logging(verbose)
    from filings_hub.ingest.edgar_client import client_from_settings
    from filings_hub.ingest.refresh import run_refresh

    with client_from_settings() as client:
        run = run_refresh(
            _storage(),
            client,
            index_date=date.fromisoformat(index_date) if index_date else None,
            load_db=load_db,
            alert=alert,
        )
    typer.echo(run.summary())
    raise typer.Exit(0 if run.status in ("ok", "empty") else 1)


@app.command()
def export(
    company: str = typer.Argument(help="CIK or ticker"),
    periods: str | None = typer.Option(None, help='comma-separated labels, e.g. "FY2025,Q1 2026"; default = latest 8'),
    limit: int = typer.Option(8, help="number of latest periods when --periods is not given"),
    out: Path | None = typer.Option(None, help="output .xlsx (default <ticker-or-cik>-statements.xlsx)"),
    verbose: bool = False,
) -> None:
    """Export as-reported statements to Excel."""
    _setup_logging(verbose)
    from filings_hub.db.database import Database
    from filings_hub.export.excel import export_excel

    storage = _storage()
    db = Database(get_settings().database_url, storage)
    try:
        cik = int(company) if company.isdigit() else _resolve_ticker(db, company)
        labels = [p.strip() for p in periods.split(",") if p.strip()] if periods else None
        data = export_excel(db, cik, labels, limit)
    finally:
        db.close()
    out = out or Path(f"{company.upper()}-statements.xlsx")
    out.write_bytes(data)
    typer.echo(f"wrote {out} ({len(data):,} bytes)")


def _lookup_cik(db, ident: str) -> int | None:
    """CIK for a ticker or numeric CIK string; None when unknown."""
    if ident.isdigit():
        return int(ident)
    rows = db.query("SELECT cik FROM tickers WHERE ticker = ? ORDER BY is_primary DESC LIMIT 1", [ident.upper()])
    return int(rows[0]["cik"]) if rows else None


def _resolve_ticker(db, ticker: str) -> int:
    cik = _lookup_cik(db, ticker)
    if cik is None:
        typer.echo(f"unknown ticker {ticker}", err=True)
        raise typer.Exit(2)
    return cik


@app.command()
def load(
    full: bool = typer.Option(True, help="full reload (default) instead of incremental for --ciks"),
    ciks: str | None = typer.Option(None, help="comma-separated CIKs for an incremental load"),
    all_periods: bool = typer.Option(False, help="load comparative period columns too (bigger)"),
    verbose: bool = False,
) -> None:
    """Load serving tables from the lake into Postgres (DATABASE_URL)."""
    _setup_logging(verbose)
    from filings_hub.db.load import load_full, load_incremental

    url = get_settings().database_url
    if not url:
        typer.echo("DATABASE_URL is not set", err=True)
        raise typer.Exit(2)
    if ciks:
        counts = load_incremental(_storage(), url, {int(c) for c in ciks.split(",")}, all_periods=all_periods)
    else:
        counts = load_full(_storage(), url, all_periods=all_periods)
    typer.echo(str(counts))


@app.command()
def api(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    """Run the Phase 2 API (uvicorn)."""
    import uvicorn

    uvicorn.run("filings_hub.api.app:app_factory", host=host, port=port, reload=reload, factory=True)


@app.command()
def demo(verbose: bool = False) -> None:
    """Seed the lake with synthetic EDGAR data and run the whole pipeline offline (no SEC access needed)."""
    _setup_logging(verbose)
    from filings_hub.ingest.backfill import run_backfill
    from filings_hub.testing.edgar_fixtures import seed_raw

    storage = _storage()
    seed_raw(storage)
    run = run_backfill(
        storage,
        workers=1,
        skip_download=True,
        load_db=bool(get_settings().database_url),
        today=date(2026, 9, 11),
    )
    typer.echo(run.summary())
    typer.echo("try: filings-hub export AAPL --out aapl.xlsx   or   filings-hub api")


if __name__ == "__main__":
    app()


@app.command()
def quality(
    since: int = typer.Option(2020, help="first fiscal year to include"),
    tickers_file: Path | None = typer.Option(None, help="text file with one ticker per line (e.g. the S&P 500)"),
    verbose: bool = False,
) -> None:
    """checks_passed rate by fiscal year and form (plan: >= 95 % on S&P 500 filings since 2020)."""
    _setup_logging(verbose)
    from filings_hub.db.database import Database

    db = Database(get_settings().database_url, _storage())
    try:
        params: list[object] = [since]
        filt = ""
        if tickers_file:
            tickers = [t.strip().upper() for t in tickers_file.read_text().splitlines() if t.strip()]
            filt = f" AND p.cik IN (SELECT cik FROM tickers WHERE ticker IN ({', '.join('?' for _ in tickers)}))"
            params.extend(tickers)
        rows = db.query(
            f"""
            SELECT p.fiscal_year, p.results_form AS form, count(*) AS filings,
                   sum(CASE WHEN p.checks_passed THEN 1 ELSE 0 END) AS passed,
                   sum(CASE WHEN p.checks_passed IS NULL THEN 1 ELSE 0 END) AS not_applicable,
                   sum(CASE WHEN p.statements_source = 'facts_fallback' THEN 1 ELSE 0 END) AS provisional
            FROM {db.periods_table} p WHERE p.fiscal_year >= ?{filt}
            GROUP BY 1, 2 ORDER BY 1, 2
            """,
            params,
        )
    finally:
        db.close()
    typer.echo(f"{'fy':>5} {'form':<8} {'filings':>8} {'passed':>8} {'n/a':>6} {'provisional':>12} {'pass rate':>10}")
    tot = {"filings": 0, "passed": 0, "na": 0}
    for r in rows:
        applicable = r["filings"] - r["not_applicable"]
        rate = (r["passed"] / applicable) if applicable else float("nan")
        tot["filings"] += r["filings"]
        tot["passed"] += r["passed"]
        tot["na"] += r["not_applicable"]
        typer.echo(
            f"{r['fiscal_year']:>5} {r['form']:<8} {r['filings']:>8} {r['passed']:>8} {r['not_applicable']:>6} "
            f"{r['provisional']:>12} {rate:>9.1%}"
        )
    applicable = tot["filings"] - tot["na"]
    if applicable:
        typer.echo(
            f"overall pass rate: {tot['passed'] / applicable:.1%} on {applicable} filings with applicable checks"
        )


@app.command()
def golden(
    tickers: str = typer.Argument(help="comma-separated tickers or CIKs"),
    periods: int = typer.Option(2, help="latest periods per company"),
    verbose: bool = False,
) -> None:
    """Golden-set spot check: latest periods with results filing, earnings release, statement source and checks."""
    _setup_logging(verbose)
    from filings_hub.db.database import Database

    db = Database(get_settings().database_url, _storage())
    try:
        for ident in [t.strip() for t in tickers.split(",") if t.strip()]:
            cik = _lookup_cik(db, ident)
            comp = db.query("SELECT name, ticker, fiscal_year_end FROM companies WHERE cik = ?", [cik]) if cik else []
            if not comp:
                typer.echo(f"{ident}: unknown")
                continue
            c = comp[0]
            typer.echo(f"\n{c['name']} ({c['ticker'] or cik}) FYE {c['fiscal_year_end']}")
            rows = db.query(
                f"SELECT * FROM {db.periods_table} WHERE cik = ? ORDER BY period_end DESC LIMIT ?", [cik, periods]
            )
            for p in rows:
                er = p["earnings_release_filed_date"] or "-"
                typer.echo(
                    f"  {p['period_label']:<9} end {p['period_end']}  {p['results_form']:<6} "
                    f"filed {p['results_filed_date']}"
                    f"  8-K 2.02 {er}  statements={p['statements_source'] or 'none':<14} checks={p['checks_passed']}"
                    f"  amendments={len(p['amendment_accessions'] or [])}  {p['results_primary_doc_url'] or ''}"
                )
    finally:
        db.close()
