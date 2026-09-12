"""Download EDGAR bulk sources into raw/. Never re-hit the SEC for bytes we already have.

Sources:
  submissions.zip   all company submission indexes   (~1.5 GB)
  companyfacts.zip  all XBRL company facts           (~1 GB)
  FSDS              Financial Statement Data Sets, one zip per quarter since 2009q1
  company_tickers_exchange.json
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date

from filings_hub.ingest.edgar_client import (
    COMPANY_TICKERS_EXCHANGE_URL,
    COMPANYFACTS_BULK_URL,
    SUBMISSIONS_BULK_URL,
    EdgarClient,
)
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage

log = logging.getLogger(__name__)

FSDS_FIRST_QUARTER = (2009, 1)


def quarter_of(day: date) -> str:
    return f"{day.year}q{(day.month - 1) // 3 + 1}"


def fsds_quarters(until: date | None = None, since: tuple[int, int] = FSDS_FIRST_QUARTER) -> list[str]:
    """All FSDS quarter names from 2009q1 up to the quarter containing `until` (default today)."""
    until = until or date.today()
    y, q = since
    out = []
    while (y, q) <= (until.year, (until.month - 1) // 3 + 1):
        out.append(f"{y}q{q}")
        q += 1
        if q == 5:
            y, q = y + 1, 1
    return out


def download_to(storage: Storage, client: EdgarClient, url: str, rel: str, force: bool = False) -> bool:
    """Stream `url` into the lake at `rel`. Returns True if downloaded, False if already present."""
    if storage.exists(rel) and not force:
        log.info("raw present, skipping download: %s", rel)
        return False
    tmp = rel + ".part"
    log.info("downloading %s -> %s", url, rel)
    with client.stream(url) as resp, storage.open(tmp, "wb") as out:
        for chunk in resp.iter_bytes(chunk_size=8 * 1024 * 1024):
            out.write(chunk)
    storage.fs.mv(storage.full(tmp), storage.full(rel))
    return True


def download_submissions(storage: Storage, client: EdgarClient, day: date | None = None) -> str:
    day = day or date.today()
    rel = layout.raw_submissions_zip(day)
    download_to(storage, client, SUBMISSIONS_BULK_URL, rel)
    return rel


def download_companyfacts(storage: Storage, client: EdgarClient, day: date | None = None) -> str:
    day = day or date.today()
    rel = layout.raw_companyfacts_zip(day)
    download_to(storage, client, COMPANYFACTS_BULK_URL, rel)
    return rel


def download_company_tickers(storage: Storage, client: EdgarClient, day: date | None = None) -> str:
    day = day or date.today()
    rel = layout.raw_company_tickers(day)
    download_to(storage, client, COMPANY_TICKERS_EXCHANGE_URL, rel)
    return rel


def download_fsds(storage: Storage, client: EdgarClient, quarters: Iterable[str] | None = None) -> list[str]:
    """Download FSDS quarterly zips. Quarters not yet published (404) are skipped, not errors."""
    got: list[str] = []
    for quarter in quarters or fsds_quarters():
        rel = layout.raw_fsds_zip(quarter)
        if storage.exists(rel):
            got.append(quarter)
            continue
        url = client.fsds_url(quarter)
        resp = client.get_optional(url)
        if resp is None:
            log.info("FSDS %s not published yet (404)", quarter)
            continue
        storage.write_bytes(rel, resp.content)
        got.append(quarter)
        log.info("downloaded FSDS %s (%d bytes)", quarter, len(resp.content))
    return got


def latest_raw(storage: Storage, source: str) -> str | None:
    """Most recent dated raw file for `source` in {submissions, companyfacts, company_tickers}."""
    names = {
        "submissions": "submissions.zip",
        "companyfacts": "companyfacts.zip",
        "company_tickers": "company_tickers_exchange.json",
    }
    days = storage.ls(f"{layout.RAW}/{source}")
    for d in sorted(days, reverse=True):
        rel = f"{d}/{names[source]}"
        if storage.exists(rel):
            return rel
    return None


def download_all(storage: Storage, client: EdgarClient, day: date | None = None) -> dict[str, object]:
    day = day or date.today()
    return {
        "company_tickers": download_company_tickers(storage, client, day),
        "submissions": download_submissions(storage, client, day),
        "companyfacts": download_companyfacts(storage, client, day),
        "fsds": download_fsds(storage, client),
    }
