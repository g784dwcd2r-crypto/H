"""Rebuild the periods table from filings + companies (cheap: seconds for all of EDGAR)."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from filings_hub.ingest.periods import RESULTS_FORMS, build_periods_for_company, periods_table
from filings_hub.lake import layout
from filings_hub.lake.duck import Duck
from filings_hub.lake.storage import Storage

log = logging.getLogger(__name__)

BATCH_CIKS = 2000


def _period_filings(duck: Duck, ciks: list[int]) -> dict[int, list[dict[str, Any]]]:
    forms = ", ".join(f"'{f}'" for f in RESULTS_FORMS)
    rows = duck.fetch_dicts(
        f"""
        SELECT cik, accession, form, filed_date, report_date, items, primary_doc_url
        FROM filings
        WHERE (replace(upper(form), '/A', '') IN ({forms})
               OR (upper(form) LIKE '8-K%' AND list_contains(items, '2.02')))
          AND cik IN (SELECT unnest(?::BIGINT[]))
        ORDER BY cik, filed_date
        """,
        [ciks],
    )
    by_cik: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_cik[r["cik"]].append(r)
    return by_cik


def rebuild_periods(storage: Storage, ciks: list[int] | None = None) -> int:
    """Rebuild periods for `ciks` (default: every CIK with filings). Other companies' rows are kept."""
    duck = Duck(storage)
    try:
        if not duck.view("filings", f"{layout.FILINGS}/*/*.parquet"):
            log.warning("no filings; periods not built")
            return 0
        fye: dict[int, str | None] = {}
        if duck.view("companies", layout.COMPANIES, hive=False):
            for r in duck.fetch_dicts("SELECT cik, fiscal_year_end FROM companies"):
                fye[r["cik"]] = r["fiscal_year_end"]
        if ciks:
            targets = sorted(set(ciks))
        else:
            targets = [r[0] for r in duck.sql("SELECT DISTINCT cik FROM filings ORDER BY cik").fetchall()]
        out: list[dict[str, Any]] = []
        for i in range(0, len(targets), BATCH_CIKS):
            batch = targets[i : i + BATCH_CIKS]
            for cik, fl in _period_filings(duck, batch).items():
                out.extend(build_periods_for_company(cik, fl, fye.get(cik)))
        if ciks and storage.exists(layout.PERIODS):
            keep_set = set(targets)
            out += [r for r in storage.read_parquet(layout.PERIODS).to_pylist() if r["cik"] not in keep_set]
        out.sort(key=lambda r: (r["cik"], r["period_end"]))
        storage.write_parquet(layout.PERIODS, periods_table(out))
        log.info("periods: %d rows", len(out))
        return len(out)
    finally:
        duck.close()
