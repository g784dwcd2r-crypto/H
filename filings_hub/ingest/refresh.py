"""Daily refresh: yesterday's daily index -> new filings -> refreshed companies -> statements -> Postgres.

One scheduler entry runs `filings-hub refresh` at 06:00 ET. Every run writes a `run_log` row.
"""

from __future__ import annotations

import logging
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pyarrow as pa

from filings_hub.ingest import bulk, fsds, sync_facts, sync_filings, sync_statements, sync_universe
from filings_hub.ingest.alerts import notify
from filings_hub.ingest.edgar_client import EdgarClient
from filings_hub.ingest.periods import RESULTS_FORMS
from filings_hub.ingest.submissions import company_header_table
from filings_hub.ingest.sync_periods import rebuild_periods
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage

log = logging.getLogger(__name__)

RUN_LOG_SCHEMA = pa.schema(
    [
        ("run_id", pa.string()),
        ("kind", pa.string()),  # refresh | backfill | load
        ("started_at", pa.timestamp("s")),
        ("finished_at", pa.timestamp("s")),
        ("duration_seconds", pa.float64()),
        ("status", pa.string()),  # ok | failed | empty
        ("index_dates", pa.list_(pa.string())),
        ("new_filings", pa.int64()),
        ("ciks_refreshed", pa.int64()),
        ("facts_rows", pa.int64()),
        ("statements_built", pa.int64()),
        ("fsds_quarters_loaded", pa.list_(pa.string())),
        ("failures", pa.list_(pa.string())),
        ("error", pa.string()),
        ("db_loaded", pa.bool_()),
    ]
)

REFRESH_FORMS = (*RESULTS_FORMS, "8-K")
MAX_CATCHUP_DAYS = 7


@dataclass
class RunLog:
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    kind: str = "refresh"
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0, tzinfo=None))
    finished_at: datetime | None = None
    status: str = "running"
    index_dates: list[str] = field(default_factory=list)
    new_filings: int = 0
    ciks_refreshed: int = 0
    facts_rows: int = 0
    statements_built: int = 0
    fsds_quarters_loaded: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    error: str | None = None
    db_loaded: bool = False

    def finish(self, status: str) -> RunLog:
        self.finished_at = datetime.now(UTC).replace(microsecond=0, tzinfo=None)
        self.status = status
        return self

    def row(self) -> dict[str, Any]:
        dur = (self.finished_at - self.started_at).total_seconds() if self.finished_at else None
        return {
            "run_id": self.run_id,
            "kind": self.kind,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": dur,
            "status": self.status,
            "index_dates": self.index_dates,
            "new_filings": self.new_filings,
            "ciks_refreshed": self.ciks_refreshed,
            "facts_rows": self.facts_rows,
            "statements_built": self.statements_built,
            "fsds_quarters_loaded": self.fsds_quarters_loaded,
            "failures": self.failures[:200],
            "error": self.error,
            "db_loaded": self.db_loaded,
        }

    def summary(self) -> str:
        return (
            f"run {self.run_id} [{self.kind}] {self.status}: dates={','.join(self.index_dates) or '-'} "
            f"new_filings={self.new_filings} ciks={self.ciks_refreshed} facts={self.facts_rows} "
            f"statements={self.statements_built} fsds={self.fsds_quarters_loaded} failures={len(self.failures)}"
            + (f" error={self.error}" if self.error else "")
        )


def write_run_log(storage: Storage, run: RunLog) -> None:
    storage.write_parquet(
        f"{layout.RUN_LOG}/{run.started_at:%Y%m%dT%H%M%S}_{run.run_id}.parquet",
        pa.Table.from_pylist([run.row()], schema=RUN_LOG_SCHEMA),
    )


def last_indexed_date(storage: Storage) -> date | None:
    """Most recent daily-index date any successful refresh processed (from the raw layer)."""
    days: list[date] = []
    for year_dir in storage.ls(f"{layout.RAW}/daily-index"):
        for f in storage.ls(year_dir):
            name = f.rsplit("/", 1)[-1]
            if name.startswith("master.") and name.endswith(".idx"):
                d = name[len("master.") : -len(".idx")]
                days.append(date(int(d[:4]), int(d[4:6]), int(d[6:])))
    return max(days) if days else None


def index_dates_to_process(storage: Storage, today: date, requested: date | None = None) -> list[date]:
    if requested:
        return [requested]
    yesterday = today - timedelta(days=1)
    last = last_indexed_date(storage)
    if last is None:
        return [yesterday]
    start = max(last + timedelta(days=1), yesterday - timedelta(days=MAX_CATCHUP_DAYS - 1))
    return [start + timedelta(days=i) for i in range((yesterday - start).days + 1)]


def fetch_daily_index(storage: Storage, client: EdgarClient, day: date) -> str | None:
    rel = layout.raw_daily_index(day)
    if storage.exists(rel):
        return storage.read_text(rel)
    text = client.fetch_daily_index(day)
    if text is None:
        return None
    storage.write_text(rel, text)
    return text


def maybe_load_new_fsds(storage: Storage, client: EdgarClient, today: date) -> list[str]:
    """Try the two most recent quarters not yet in raw/ (the SEC publishes a quarter ~1 month after it ends)."""
    have = set(fsds.raw_quarters(storage))
    candidates = [q for q in bulk.fsds_quarters(today) if q not in have][-2:]
    got = bulk.download_fsds(storage, client, candidates) if candidates else []
    loaded = fsds.load_all_fsds(storage, got) if got else []
    if loaded:
        sync_statements.build_all_fsds(storage, loaded)
    return loaded


def run_refresh(
    storage: Storage,
    client: EdgarClient,
    today: date | None = None,
    index_date: date | None = None,
    load_db: bool = True,
    database_url: str | None = None,
    alert: bool = True,
) -> RunLog:
    today = today or date.today()
    run = RunLog()
    t0 = time.monotonic()
    touched_results: set[int] = set()
    touched_any: set[int] = set()
    new_accessions: set[str] = set()
    try:
        # 1. daily index -> new filings (stub rows)
        stub_rows: list[dict[str, Any]] = []
        for day in index_dates_to_process(storage, today, index_date):
            text = fetch_daily_index(storage, client, day)
            if text is None:
                log.info("no daily index for %s (weekend/holiday?)", day)
                continue
            run.index_dates.append(day.isoformat())
            rows = sync_filings.parse_daily_index(text)
            stub_rows.extend(rows)
        run.new_filings = sync_filings.upsert_filings(storage, stub_rows)
        new_accessions = {r["accession"] for r in stub_rows}
        touched_any = sync_filings.touched_ciks(stub_rows, REFRESH_FORMS)
        touched_results = sync_filings.touched_ciks(stub_rows, tuple(RESULTS_FORMS))
        known = set()
        if storage.exists(layout.COMPANIES):
            known = set(storage.read_parquet(layout.COMPANIES).column("cik").to_pylist())
        new_ciks = {r["cik"] for r in stub_rows} - known
        touched_any |= new_ciks

        # 2. per-company API for touched CIKs: filings (authoritative), headers, facts
        headers: list[dict[str, Any]] = []
        api_rows: list[dict[str, Any]] = []
        refreshed: list[int] = []
        for cik in sorted(touched_any):
            try:
                header, rows = sync_filings.refresh_cik_from_api(storage, client, cik, today)
                headers.append(header)
                api_rows.extend(rows)
                refreshed.append(cik)
                if cik in touched_results:
                    run.facts_rows += sync_facts.refresh_cik_facts(storage, client, cik, today)
                run.ciks_refreshed += 1
            except Exception as e:
                run.failures.append(f"cik {cik}: {e}")
                log.exception("refresh failed for CIK %s", cik)
        # one pass over the year partitions for every refreshed company (not one rewrite per company)
        sync_filings.upsert_filings(storage, api_rows, replace_ciks=refreshed)
        if headers:
            sync_universe.upsert_headers(storage, company_header_table(headers), today=today)
        elif storage.exists(layout.COMPANIES):
            sync_universe.upsert_headers(storage, company_header_table([]), today=today)

        # 3. periods (all: cheap and keeps labels consistent)
        rebuild_periods(storage)

        # 4. FSDS: pick up a newly published quarter, then provisional statements for new filings
        run.fsds_quarters_loaded = maybe_load_new_fsds(storage, client, today)
        for cik in sorted(touched_results):
            try:
                run.statements_built += sync_statements.fill_fallbacks_for_cik(storage, cik)
            except Exception as e:
                run.failures.append(f"statements cik {cik}: {e}")
                log.exception("fallback statements failed for CIK %s", cik)

        # 5. serving tables
        if load_db:
            from filings_hub.db.load import load_incremental

            url = database_url
            if url is None:
                from filings_hub.config import get_settings

                url = get_settings().database_url
            if url:
                load_incremental(
                    storage,
                    url,
                    ciks=touched_any | touched_results,
                    accessions=new_accessions,
                    fsds_quarters=run.fsds_quarters_loaded,
                )
                run.db_loaded = True

        weekday = (
            all(date.fromisoformat(d).weekday() < 5 for d in run.index_dates)
            if run.index_dates
            else (today - timedelta(days=1)).weekday() < 5
        )
        status = "ok" if run.new_filings or not weekday else "empty"
        run.finish(status)
    except Exception as e:
        run.error = f"{type(e).__name__}: {e}"
        run.failures.append(traceback.format_exc()[-2000:])
        run.finish("failed")
        log.exception("refresh failed")
    finally:
        write_run_log(storage, run)
        log.info("%s (%.0fs)", run.summary(), time.monotonic() - t0)
        if alert and run.status in ("failed", "empty"):
            notify(f"filings-hub refresh {run.status}", run.summary())
    return run
