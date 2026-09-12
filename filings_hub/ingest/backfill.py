"""Bulk backfill: raw bulk files -> universe -> filings -> periods -> facts -> FSDS -> statements -> Postgres."""

from __future__ import annotations

import logging
import time
from datetime import date

from filings_hub.ingest import bulk, fsds, sync_facts, sync_filings, sync_statements, sync_universe
from filings_hub.ingest.edgar_client import client_from_settings
from filings_hub.ingest.refresh import RunLog, write_run_log
from filings_hub.ingest.sync_periods import rebuild_periods
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage

log = logging.getLogger(__name__)


def run_backfill(
    storage: Storage,
    workers: int = 4,
    skip_download: bool = False,
    fsds_since: str = "2009q1",
    load_db: bool = True,
    today: date | None = None,
    database_url: str | None = None,
) -> RunLog:
    today = today or date.today()
    run = RunLog(kind="backfill")
    t0 = time.monotonic()
    try:
        if not skip_download:
            with client_from_settings() as client:
                since = (int(fsds_since[:4]), int(fsds_since[-1]))
                bulk.download_company_tickers(storage, client, today)
                bulk.download_submissions(storage, client, today)
                bulk.download_companyfacts(storage, client, today)
                bulk.download_fsds(storage, client, bulk.fsds_quarters(today, since))
        sub_zip = bulk.latest_raw(storage, "submissions")
        facts_zip = bulk.latest_raw(storage, "companyfacts")
        tickers_json = bulk.latest_raw(storage, "company_tickers")
        if not sub_zip or not facts_zip:
            raise RuntimeError("raw bulk files missing; run without --skip-download")

        step = time.monotonic()
        headers = sync_filings.load_bulk_submissions(storage, sub_zip)
        run.new_filings = sync_filings.count_filings(storage)
        log.info("step filings: %.0fs", time.monotonic() - step)

        step = time.monotonic()
        companies, _ = sync_universe.sync_universe(
            storage, headers, storage.read_bytes(tickers_json) if tickers_json else None, today
        )
        run.ciks_refreshed = companies.num_rows
        log.info("step universe: %.0fs", time.monotonic() - step)

        step = time.monotonic()
        rebuild_periods(storage)
        log.info("step periods: %.0fs", time.monotonic() - step)

        step = time.monotonic()
        facts = sync_facts.load_bulk_companyfacts(storage, facts_zip, workers=workers)
        run.facts_rows = facts["rows"]
        run.failures.extend(facts["failures"])
        log.info("step facts: %.0fs", time.monotonic() - step)

        step = time.monotonic()
        quarters = [q for q in fsds.raw_quarters(storage) if q >= fsds_since]
        run.fsds_quarters_loaded = fsds.load_all_fsds(storage, quarters)
        built = sync_statements.build_all_fsds(storage, quarters)
        log.info("step fsds+statements (%d quarters): %.0fs", len(built), time.monotonic() - step)

        step = time.monotonic()
        run.statements_built = sync_statements.fill_all_fallbacks(storage)
        log.info("step fallbacks: %.0fs", time.monotonic() - step)

        if load_db:
            url = database_url
            if url is None:
                from filings_hub.config import get_settings

                url = get_settings().database_url
            if url:
                from filings_hub.db.load import load_full

                step = time.monotonic()
                load_full(storage, url)
                run.db_loaded = True
                log.info("step load: %.0fs", time.monotonic() - step)
        run.finish("ok")
    except Exception as e:
        run.error = f"{type(e).__name__}: {e}"
        run.finish("failed")
        log.exception("backfill failed")
    finally:
        write_run_log(storage, run)
        log.info("%s (%.0fs)", run.summary(), time.monotonic() - t0)
    return run


__all__ = ["layout", "run_backfill"]
