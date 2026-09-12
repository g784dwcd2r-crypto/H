"""Bulk backfill: raw bulk files -> universe -> filings -> periods -> facts -> FSDS -> statements -> Postgres."""

from __future__ import annotations

import logging
import time
from datetime import date

from filings_hub.ingest import bulk, fsds, sync_facts, sync_filings, sync_statements, sync_universe
from filings_hub.ingest.edgar_client import EdgarClient, client_from_settings
from filings_hub.ingest.refresh import RunLog, write_run_log
from filings_hub.ingest.sync_periods import rebuild_periods
from filings_hub.lake import layout
from filings_hub.lake.duck import Duck
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
    client: EdgarClient | None = None,
) -> RunLog:
    today = today or date.today()
    run = RunLog(kind="backfill")
    t0 = time.monotonic()
    own_client = client is None and not skip_download
    if own_client:
        client = client_from_settings()
    try:
        if not skip_download:
            assert client is not None
            since = (int(fsds_since[:4]), int(fsds_since[-1]))
            bulk.download_company_tickers(storage, client, today)
            bulk.download_submissions(storage, client, today)
            bulk.download_companyfacts(storage, client, today)
            bulk.download_fsds(storage, client, bulk.fsds_quarters(today, since))
        sub_zip = bulk.latest_raw(storage, "submissions")
        facts_zip = bulk.latest_raw(storage, "companyfacts")  # an older day's zip beats no zip
        tickers_json = bulk.latest_raw(storage, "company_tickers")
        if not sub_zip or (not facts_zip and skip_download):
            raise RuntimeError("raw bulk files missing; run without --skip-download")

        step = time.monotonic()
        headers = sync_filings.load_bulk_submissions(storage, sub_zip)
        run.new_filings = sync_filings.count_filings(storage)
        run.step("filings", time.monotonic() - step)

        step = time.monotonic()
        companies, _ = sync_universe.sync_universe(
            storage, headers, storage.read_bytes(tickers_json) if tickers_json else None, today
        )
        run.ciks_refreshed = companies.num_rows
        run.step("universe", time.monotonic() - step)

        step = time.monotonic()
        rebuild_periods(storage)
        run.step("periods", time.monotonic() - step)

        step = time.monotonic()
        if facts_zip:
            facts = sync_facts.load_bulk_companyfacts(storage, facts_zip, workers=workers)
            facts_step = "facts"
        else:
            # companyfacts.zip is not being served: every company that ever filed financial statements
            # goes through the per-company API instead (same JSON, same loader, ~10 req/s).
            assert client is not None
            facts = sync_facts.load_api_companyfacts(storage, client, reporting_ciks(storage), today, workers)
            facts_step = "facts[api]"
        run.facts_rows = facts["rows"]
        run.failures.extend(facts["failures"])
        run.step(facts_step, time.monotonic() - step)

        step = time.monotonic()
        quarters = [q for q in fsds.raw_quarters(storage) if q >= fsds_since]
        run.fsds_quarters_loaded = fsds.load_all_fsds(storage, quarters)
        run.step("fsds_load", time.monotonic() - step)
        # rows the loader could not read are never silent: over the threshold they go in the run log
        for entry in fsds.load_log(storage):
            if entry["raw_rows"] and entry["rejected_rows"] / entry["raw_rows"] > fsds.REJECT_WARN_RATIO:
                run.failures.append(
                    f"fsds {entry['quarter']} {entry['table']}: {entry['rejected_rows']:,} of "
                    f"{entry['raw_rows']:,} rows rejected; first: {(entry['reject_examples'] or [''])[0]}"
                )
        step = time.monotonic()
        built = sync_statements.build_all_fsds(storage, quarters)
        run.step(f"statements[{len(built)}q]", time.monotonic() - step)

        step = time.monotonic()
        run.statements_built = sync_statements.fill_all_fallbacks(storage)
        run.step("fallbacks", time.monotonic() - step)

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
                run.step("load", time.monotonic() - step)
        run.finish("ok")
    except Exception as e:
        run.error = f"{type(e).__name__}: {e}"
        run.finish("failed")
        log.exception("backfill failed")
    finally:
        if own_client and client is not None:
            client.close()
        write_run_log(storage, run)
        log.info("%s (%.0fs)", run.summary(), time.monotonic() - t0)
    return run


def reporting_ciks(storage: Storage) -> list[int]:
    """CIKs with at least one financial report on file (the companies whose facts exist at all)."""
    duck = Duck(storage)
    try:
        if not duck.view("companies", layout.COMPANIES, hive=False):
            return []
        return [
            int(c)
            for c in duck.fetch_column(
                "SELECT cik FROM companies WHERE last_financial_report_date IS NOT NULL ORDER BY cik"
            )
        ]
    finally:
        duck.close()


__all__ = ["layout", "run_backfill"]
