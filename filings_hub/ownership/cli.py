"""Operator commands for current SEC ownership XML, with bounded work on every invocation."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date

import typer

from filings_hub.config import get_settings
from filings_hub.lake.storage import Storage
from filings_hub.ownership.ingest import filing_metadata, process_filing, sync_ownership
from filings_hub.ownership.store import OwnershipStore
from filings_hub.research_index import open_index

app = typer.Typer(
    help="Current ownership XML: discover, ingest, map securities, inspect coverage and send opt-in alerts."
)


@contextmanager
def resources():
    settings = get_settings()
    storage = Storage(settings.resolved_lake_root())
    index = open_index(storage, settings.database_url)
    try:
        yield OwnershipStore(index, storage), storage
    finally:
        index.close()


def _day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError as exc:
        raise typer.BadParameter("Dates must be YYYY-MM-DD") from exc


@app.command()
def sync(
    index_date: str | None = typer.Option(None, "--date", help="Replay one completed SEC daily index"),
    since: str | None = typer.Option(None, help="Start/resume a bounded catch-up from this date"),
    max_days: int = typer.Option(7, min=1, max=31),
    max_filings: int = typer.Option(50, min=1, max=500),
    send_alerts: bool = typer.Option(False, help="Deliver separately opted-in ownership emails after ingestion"),
) -> None:
    """Default first run starts yesterday; later runs resume discovery and the retained filing queue."""
    from filings_hub.ingest.edgar_client import client_from_settings

    if index_date and since:
        raise typer.BadParameter("--date and --since cannot be combined")
    start, selected = _day(since), _day(index_date)
    with resources() as (store, storage), client_from_settings() as client:
        result = sync_ownership(
            store, client, since=start, index_date=selected, max_days=max_days, max_filings=max_filings
        )
        if send_alerts:
            from filings_hub.ownership.digest import send_ownership_digests

            result["emails_sent"] = send_ownership_digests(store, storage, site_url=get_settings().site_url)
        typer.echo(json.dumps(result, indent=2, default=str))
        raise typer.Exit(0 if result["status"] == "ok" else 1)


@app.command()
def filing(
    filer_cik: int,
    accession: str,
    form: str,
    filed_date: str,
) -> None:
    """Load/retry one known filing, including an explicitly chosen comparison baseline. Sends no email."""
    from filings_hub.ingest.edgar_client import client_from_settings

    try:
        metadata = filing_metadata(filer_cik, accession, form, filed_date)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    with resources() as (store, _), client_from_settings() as client:
        result = process_filing(store, client, metadata)
        typer.echo(json.dumps(result, indent=2, default=str))
        raise typer.Exit(1 if result["status"] == "failed" else 0)


@app.command()
def map_security(cusip: str, cik: int, security_title: str, source_url: str) -> None:
    """Register an exact, evidence-backed CUSIP/issuer/class mapping. Conflicts are rejected."""
    with resources() as (store, _):
        try:
            result = store.map_security(cusip, cik, security_title, source_url)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo(json.dumps(result, indent=2, default=str))


@app.command()
def coverage(cik: int | None = None) -> None:
    """Inspect parsed, pending, failed, unsupported and unmatched observations."""
    with resources() as (store, _):
        typer.echo(json.dumps(store.coverage(cik), indent=2, default=str))


@app.command()
def notify() -> None:
    """Retry pending opt-in ownership notifications using durable per-flow delivery receipts."""
    from filings_hub.ownership.digest import send_ownership_digests

    with resources() as (store, storage):
        typer.echo(
            json.dumps({"emails_sent": send_ownership_digests(store, storage, site_url=get_settings().site_url)})
        )


@app.command()
def skip_date(index_date: str, reason: str) -> None:
    """Record an operator-verified date with no SEC index (for example a market holiday)."""
    selected = _day(index_date)
    if not selected or selected >= date.today() or len(reason.strip()) < 10:
        raise typer.BadParameter("A past date and a specific reason of at least 10 characters are required")
    with resources() as (store, _):
        store.set_state(f"skip-date:{selected}", {"reason": reason.strip(), "recorded_at": date.today().isoformat()})
        typer.echo(f"Recorded {selected}: {reason.strip()}. The next sync can advance this date.")
