"""Daily refresh: yesterday's daily index -> new filings -> refreshed companies -> statements -> Postgres.

One scheduler entry runs `filings-hub refresh` at 06:00 ET. Every run writes a `run_log` row.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pyarrow as pa

from filings_hub.ingest import (
    bulk,
    digest,
    documents,
    fsds,
    metrics,
    sync_facts,
    sync_filings,
    sync_statements,
    sync_universe,
)
from filings_hub.ingest.alerts import notify
from filings_hub.ingest.edgar_client import EdgarClient
from filings_hub.ingest.periods import RESULTS_FORMS, base_form
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
        ("steps", pa.list_(pa.string())),  # "name=seconds" per pipeline step, in order
    ]
)

REFRESH_FORMS = (*RESULTS_FORMS, "8-K")
MAX_CATCHUP_DAYS = 7  # maximum batch size; old work is retained, never truncated by age
# Downloaded bytes are a cache, never an ingestion checkpoint. A pending record is written before
# any work starts and survives process termination; it is completed only after all pipeline stages.
REFRESH_STATE = "refresh_state"


def _write_state(storage: Storage, rel: str, record: dict[str, Any]) -> None:
    data = json.dumps(record)
    if storage.is_remote:  # object PUT publishes a complete object
        storage.write_text(rel, data)
    else:
        tmp = f"{rel}.{uuid.uuid4().hex}.tmp"
        storage.write_text(tmp, data)
        storage.fs.mv(storage.full(tmp), storage.full(rel))


def _index_states(storage: Storage) -> dict[date, dict[str, Any]]:
    return {
        date.fromisoformat(p.rsplit("/", 1)[-1][:-5]): json.loads(storage.read_text(p))
        for p in storage.glob(f"{REFRESH_STATE}/dates/*.json")
    }


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
    emails_sent: int = 0
    steps: list[str] = field(default_factory=list)

    def step(self, name: str, seconds: float) -> None:
        self.steps.append(f"{name}={seconds:.0f}")
        log.info("step %s: %.0fs", name, seconds)

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
            "steps": self.steps,
        }

    def summary(self) -> str:
        return (
            f"run {self.run_id} [{self.kind}] {self.status}: dates={','.join(self.index_dates) or '-'} "
            f"new_filings={self.new_filings} ciks={self.ciks_refreshed} facts={self.facts_rows} "
            f"statements={self.statements_built} fsds={self.fsds_quarters_loaded} failures={len(self.failures)}"
            + (f" error={self.error}" if self.error else "")
        )


def write_run_log(storage: Storage, run: RunLog, database_url: str | None = None) -> None:
    rel = f"{layout.RUN_LOG}/{run.started_at:%Y%m%dT%H%M%S}_{run.run_id}.parquet"
    storage.write_parquet(rel, pa.Table.from_pylist([run.row()], schema=RUN_LOG_SCHEMA))
    if database_url:
        from filings_hub.db.run_log import publish_run_log

        try:
            publish_run_log(database_url, run.row())
        except Exception as error:
            # Preserve the finalized record in the authoritative lake even when Postgres itself is
            # unavailable, and report publication failure rather than claiming serving parity.
            failure = f"run log publication failed: {type(error).__name__}: {error}"
            run.failures.append(failure)
            run.error = run.error or failure
            run.finish("failed")
            storage.write_parquet(rel, pa.Table.from_pylist([run.row()], schema=RUN_LOG_SCHEMA))
            log.exception("finalized run log could not be published to Postgres")


def last_indexed_date(storage: Storage) -> date | None:
    """Most recent completed date, independent of downloaded raw indices."""
    return max((d for d, state in _index_states(storage).items() if state["status"] == "complete"), default=None)


def _catchup_start(storage: Storage, today: date, since: date | None = None) -> date:
    rel = f"{REFRESH_STATE}/catchup.json"
    saved = date.fromisoformat(json.loads(storage.read_text(rel))["since"]) if storage.exists(rel) else None
    if saved or since:
        return min(d for d in (saved, since) if d is not None)
    last = last_indexed_date(storage)
    return last + timedelta(days=1) if last else today - timedelta(days=1)


def index_dates_to_process(
    storage: Storage, today: date, requested: date | None = None, since: date | None = None
) -> list[date]:
    if requested:
        return [requested]
    yesterday = today - timedelta(days=1)
    states = _index_states(storage)
    start = _catchup_start(storage, today, since)
    fresh = {start + timedelta(days=i) for i in range((yesterday - start).days + 1)} - states.keys()
    retries = {d for d, state in states.items() if state["status"] != "complete" and d <= yesterday}
    # Recover indices cached by older versions that never wrote a completion checkpoint. Replaying
    # is intentional: a raw file cannot prove that its companies, statements and database were loaded.
    for p in storage.glob(f"{layout.RAW}/daily-index/*/master.*.idx"):
        d = datetime.strptime(p.rsplit("/", 1)[-1], "master.%Y%m%d.idx").date()
        if d not in states and d <= yesterday:
            retries.add(d)
    fresh -= retries
    # Rotate retries by their last attempt and reserve capacity for fresh backlog. Otherwise a
    # handful of permanent holiday 404s would occupy every slot and starve newly published indices.
    ordered_retries = sorted(retries, key=lambda d: (states.get(d, {}).get("attempted_at", ""), d))
    retry_slots = min(len(ordered_retries), max(1, MAX_CATCHUP_DAYS // 2)) if fresh else MAX_CATCHUP_DAYS
    selected = ordered_retries[:retry_slots]
    selected += sorted(fresh)[: MAX_CATCHUP_DAYS - len(selected)]
    selected += ordered_retries[retry_slots : retry_slots + MAX_CATCHUP_DAYS - len(selected)]
    return sorted(selected)


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
    """Fetch recent quarters and resume interrupted loads/builds from durable pending records."""
    have = set(fsds.raw_quarters(storage))
    candidates = [q for q in bulk.fsds_quarters(today) if q not in have][-2:]
    pending = {
        p.rsplit("/", 1)[-1][:-5]
        for p in storage.glob(f"{REFRESH_STATE}/fsds/*.json")
        if json.loads(storage.read_text(p))["status"] != "complete"
    }
    got = []
    for quarter in sorted(set(candidates) | pending):
        # Write before downloading: otherwise a crash after caching a ZIP loses the remaining work.
        rel = f"{REFRESH_STATE}/fsds/{quarter}.json"
        _write_state(storage, rel, {"status": "pending"})
        if bulk.download_fsds(storage, client, [quarter]):
            got.append(quarter)
        else:
            storage.delete(rel)  # unpublished; still a candidate on the next scheduled run
    if got:
        # These helpers otherwise regard one existing partition as a completed quarter. Force only
        # our pending quarters so a partially written load/build is reconstructed on retry.
        fsds.load_all_fsds(storage, got, force=True)
        sync_statements.build_all_fsds(storage, got, force=True)
    return got


def run_refresh(
    storage: Storage,
    client: EdgarClient,
    today: date | None = None,
    index_date: date | None = None,
    load_db: bool = True,
    database_url: str | None = None,
    alert: bool = True,
    since: date | None = None,
) -> RunLog:
    today = today or date.today()
    run = RunLog()
    t0 = time.monotonic()
    touched_results: set[int] = set()
    touched_any: set[int] = set()
    new_accessions: set[str] = set()
    notify_accessions: set[str] = set()
    days: list[date] = []
    states: dict[date, dict[str, Any]] = {}
    serving_url = database_url if load_db else None
    try:
        if load_db and serving_url is None:
            from filings_hub.config import get_settings

            serving_url = get_settings().database_url or None
        # 1. daily index -> new filings (stub rows)
        stub_rows: list[dict[str, Any]] = []
        if since and index_date:
            raise ValueError("choose either an index date or a catch-up start, not both")
        if since and since >= today:
            raise ValueError("catch-up start must be before today")
        if index_date is None:
            start = _catchup_start(storage, today, since)
            _write_state(storage, f"{REFRESH_STATE}/catchup.json", {"since": start.isoformat()})
        days = index_dates_to_process(storage, today, index_date, since)
        states = _index_states(storage)
        known = set()
        if storage.exists(layout.COMPANIES):
            known = set(storage.read_parquet(layout.COMPANIES).column("cik").to_pylist())
        for day in days:
            previous = states.get(day, {})
            states[day] = {
                **previous,
                "status": "pending",
                "run_id": run.run_id,
                "attempted_at": datetime.now(UTC).isoformat(),
                # Pre-checkpoint raw caches have unknown delivery history. Recover their data without
                # automatically resending old news; fresh work and its retries keep notifications.
                "notify": previous.get("notify", not storage.exists(layout.raw_daily_index(day))),
            }
            _write_state(storage, f"{REFRESH_STATE}/dates/{day}.json", states[day])
        for day in days:
            text = fetch_daily_index(storage, client, day)
            states[day]["index_available"] = text is not None
            if text is None:
                log.info("no daily index for %s (weekend/holiday?)", day)
                continue
            run.index_dates.append(day.isoformat())
            rows = sync_filings.parse_daily_index(text)
            stub_rows.extend(rows)
            state = states[day]
            if state["notify"]:
                notify_accessions.update(r["accession"] for r in rows)
            # Keep newly discovered CIKs across retries, even if their header was written before a
            # later stage failed and they no longer count as "new" against the companies table.
            state["ciks"] = sorted(
                set(state.get("ciks", []))
                | sync_filings.touched_ciks(rows, REFRESH_FORMS)
                | ({r["cik"] for r in rows} - known)
            )
            state["results_ciks"] = sorted(
                set(state.get("results_ciks", [])) | sync_filings.touched_ciks(rows, tuple(RESULTS_FORMS))
            )
            _write_state(storage, f"{REFRESH_STATE}/dates/{day}.json", state)
            touched_any.update(state["ciks"])
            touched_results.update(state["results_ciks"])
        run.new_filings = sync_filings.upsert_filings(storage, stub_rows)
        new_accessions = {r["accession"] for r in stub_rows}

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

        # 2b. exhibit-level contents for the new results filings and 8-Ks (the documents analysts open)
        new_rows = [r for r in api_rows if r["accession"] in notify_accessions]
        # ... plus a bounded catch-up for the refreshed companies' recent history (ensure_documents skips
        # what the lake already has, and caps fetches per company), so a company gets its documents the
        # first time it files rather than one filing at a time
        recent_cutoff = today - timedelta(days=400)
        doc_rows = [
            r
            for r in api_rows
            if (digest.is_results_filing(r) or base_form(r.get("form") or "") == "8-K")
            and (r["accession"] in new_accessions or (r.get("filed_date") and r["filed_date"] >= recent_cutoff))
        ]
        for cik in sorted({int(r["cik"]) for r in doc_rows}):
            mine = [r for r in doc_rows if int(r["cik"]) == cik]
            try:
                _, doc_failures = documents.ensure_documents(storage, client, cik, mine)
                run.failures.extend(f"documents cik {cik} {f}" for f in doc_failures)
            except Exception as e:
                run.failures.append(f"documents cik {cik}: {e}")
                log.exception("documents failed for CIK %s", cik)

        # 3. periods (all: cheap and keeps labels consistent)
        rebuild_periods(storage)

        # 4. FSDS: pick up a newly published quarter, then provisional statements for new filings
        run.fsds_quarters_loaded = maybe_load_new_fsds(storage, client, today)
        for cik in sorted(touched_results):
            try:
                run.statements_built += sync_statements.fill_fallbacks_for_cik(
                    storage, cik, rebuild_accessions={r["accession"] for r in stub_rows if r["cik"] == cik}
                )
            except Exception as e:
                run.failures.append(f"statements cik {cik}: {e}")
                log.exception("fallback statements failed for CIK %s", cik)

        # 4b. key numbers for the companies whose statements changed
        if touched_results or run.fsds_quarters_loaded:
            try:
                if run.fsds_quarters_loaded:
                    metrics.build_company_metrics(storage)
                else:
                    metrics.upsert_company_metrics(storage, touched_results)
            except Exception as e:
                run.failures.append(f"metrics: {e}")
                log.exception("company metrics failed")

        # 5. serving tables
        if load_db:
            from filings_hub.db.load import load_incremental

            if serving_url:
                load_incremental(
                    storage,
                    serving_url,
                    ciks=touched_any | touched_results,
                    accessions=new_accessions,
                    fsds_quarters=run.fsds_quarters_loaded,
                )
                run.db_loaded = True

        # 6. email digests for subscribers whose companies filed results
        if new_rows and not run.failures:
            try:
                names = {}
                if storage.exists(layout.COMPANIES):
                    t = storage.read_parquet(layout.COMPANIES).select(["cik", "name"])
                    names = dict(zip(t.column("cik").to_pylist(), t.column("name").to_pylist(), strict=True))
                from filings_hub.config import get_settings

                run.emails_sent = digest.send_digests(storage, new_rows, names, site_url=get_settings().site_url)
            except Exception as e:
                run.emails_sent = getattr(e, "sent", 0)
                run.failures.append(f"digests: {e}")
                log.exception("digests failed")

        weekday = (
            all(date.fromisoformat(d).weekday() < 5 for d in run.index_dates)
            if run.index_dates
            else (today - timedelta(days=1)).weekday() < 5
        )
        if not run.failures:
            for day in days:
                # A weekday 404 may be delayed publication. Keep it retryable even when a newer
                # index succeeds; weekends alone are safe to acknowledge without an index.
                status = "pending" if day.weekday() < 5 and not states[day].get("index_available") else "complete"
                _write_state(storage, f"{REFRESH_STATE}/dates/{day}.json", {**states[day], "status": status})
            for quarter in run.fsds_quarters_loaded:
                _write_state(storage, f"{REFRESH_STATE}/fsds/{quarter}.json", {"status": "complete"})
        # A retry can have no newly inserted rows while still successfully finishing existing work.
        status = "failed" if run.failures else ("ok" if stub_rows or not weekday else "empty")
        run.finish(status)
    except Exception as e:
        run.error = f"{type(e).__name__}: {e}"
        run.failures.append(traceback.format_exc()[-2000:])
        run.finish("failed")
        log.exception("refresh failed")
    finally:
        write_run_log(storage, run, serving_url)
        log.info("%s (%.0fs)", run.summary(), time.monotonic() - t0)
        if alert and run.status in ("failed", "empty"):
            notify(f"filings-hub refresh {run.status}", run.summary())
    return run
