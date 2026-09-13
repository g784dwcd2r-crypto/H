"""Filings table: bulk load from submissions.zip, then daily increments from the daily index."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import date
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from filings_hub.ingest.edgar_client import EdgarClient
from filings_hub.ingest.submissions import (
    FILINGS_SCHEMA,
    company_header_table,
    filings_table,
    iter_bulk_submissions,
    parse_company_header,
    parse_filings,
)
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage

log = logging.getLogger(__name__)

FLUSH_ROWS = 250_000
FILINGS_ORDER = [("cik", "ascending"), ("filed_date", "ascending"), ("accession", "ascending")]
FILINGS_ROW_GROUP = 50_000

DAILY_INDEX_LINE_RE = re.compile(r"^(\d+)\|(.*)\|(.+?)\|(\d{8})\|(edgar/data/\d+/(\S+)\.txt)\s*$")


# ---------------------------------------------------------------------------------------------
# Bulk load
# ---------------------------------------------------------------------------------------------
class _YearBuffers:
    """Accumulate filing rows per filed-year and flush to part files to bound memory."""

    def __init__(self, storage: Storage):
        self.storage = storage
        self.buf: dict[int, list[dict[str, Any]]] = {}
        self.parts: dict[int, int] = {}
        self.total = 0

    def add(self, rows: Iterable[dict[str, Any]]) -> None:
        for r in rows:
            y = r["year"]
            if y is None:
                continue
            self.buf.setdefault(y, []).append(r)
            self.total += 1
            if len(self.buf[y]) >= FLUSH_ROWS:
                self.flush(y)

    def flush(self, year: int) -> None:
        rows = self.buf.pop(year, [])
        if not rows:
            return
        n = self.parts.get(year, 0)
        # sorted by company and in small row groups: a per-company read of a year then touches one
        # or two row groups per file instead of every row of every file (see compact_filings)
        table = filings_table(rows).sort_by(FILINGS_ORDER)
        self.storage.write_parquet(
            f"{layout.filings_year_dir(year)}/part-{n:04d}.parquet", table, row_group_size=FILINGS_ROW_GROUP
        )
        self.parts[year] = n + 1

    def flush_all(self) -> None:
        for y in list(self.buf):
            self.flush(y)


def load_bulk_submissions(storage: Storage, zip_rel: str) -> pa.Table:
    """Rebuild filings/ from submissions.zip. Returns the company headers table (for sync_universe)."""
    storage.delete(layout.FILINGS)
    buffers = _YearBuffers(storage)
    headers: list[dict[str, Any]] = []
    with storage.local_copy(zip_rel) as local:
        for n, data in enumerate(iter_bulk_submissions(str(local)), 1):
            headers.append(parse_company_header(data))
            buffers.add(parse_filings(data, source="submissions_bulk"))
            if n % 2000 == 0:
                log.info("submissions: %d companies, %d filings", n, buffers.total)
    buffers.flush_all()
    log.info("filings bulk load done: %d companies, %d filings", len(headers), buffers.total)
    return company_header_table(headers)


# ---------------------------------------------------------------------------------------------
# Daily index
# ---------------------------------------------------------------------------------------------
def parse_daily_index(text: str, source: str = "daily_index") -> list[dict[str, Any]]:
    """Rows from an EDGAR master.YYYYMMDD.idx file (CIK|Company Name|Form Type|Date Filed|File Name)."""
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        m = DAILY_INDEX_LINE_RE.match(line)
        if not m:
            continue
        cik = int(m.group(1))
        form = m.group(3).strip()
        filed = date(int(m.group(4)[:4]), int(m.group(4)[4:6]), int(m.group(4)[6:]))
        accession = m.group(6)
        rows.append(
            {
                "accession": accession,
                "cik": cik,
                "form": form,
                "filed_date": filed,
                "report_date": None,
                "acceptance_datetime": None,
                "act": None,
                "file_number": None,
                "film_number": None,
                "items": [],
                "size": None,
                "is_xbrl": False,
                "is_inline_xbrl": False,
                "primary_doc": None,
                "primary_doc_description": None,
                "primary_doc_url": None,
                "filing_index_url": EdgarClient.filing_index_url(cik, accession),
                "source": source,
                "year": filed.year,
            }
        )
    return rows


# ---------------------------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------------------------
def _read_year(storage: Storage, year: int) -> pa.Table:
    files = storage.glob(f"{layout.filings_year_dir(year)}/*.parquet")
    if not files:
        return FILINGS_SCHEMA.empty_table()
    tables = [storage.read_parquet(f) for f in files]
    return pa.concat_tables([t.select(FILINGS_SCHEMA.names).cast(FILINGS_SCHEMA) for t in tables])


def upsert_filings(storage: Storage, rows: list[dict[str, Any]], replace_ciks: Iterable[int] = ()) -> int:
    """Insert/replace filings by (cik, accession). For `replace_ciks`, all existing rows of those CIKs
    in the touched years are dropped first (so a refreshed submissions API response is authoritative).

    Rows with `source='daily_index'` never overwrite richer rows for the same accession."""
    if not rows:
        return 0
    replace = set(replace_ciks)
    by_year: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        if r.get("year") is None:
            continue
        by_year.setdefault(r["year"], []).append(r)
    written = 0
    for year, new_rows in by_year.items():
        existing = _read_year(storage, year)
        # Keyed on (cik, accession), not accession alone: one accession can belong to several CIKs.
        # A parent and its operating partnership file a combined 10-K under a single accession and the
        # daily index lists one line per co-filer, so an accession-only key made each co-filer's row
        # delete the other's.
        new_by_key = {(r["cik"], r["accession"]): r for r in new_rows}
        keep_mask = []
        ex_acc = existing.column("accession").to_pylist()
        ex_cik = existing.column("cik").to_pylist()
        ex_src = existing.column("source").to_pylist()
        for acc, cik, src in zip(ex_acc, ex_cik, ex_src, strict=True):
            if cik in replace:
                keep_mask.append(False)
                continue
            key = (cik, acc)
            if key in new_by_key:
                if new_by_key[key]["source"] == "daily_index" and src != "daily_index":
                    del new_by_key[key]  # keep the richer existing row
                    keep_mask.append(True)
                else:
                    keep_mask.append(False)
                continue
            keep_mask.append(True)
        kept = existing.filter(pa.array(keep_mask, type=pa.bool_())) if len(keep_mask) else existing
        merged = pa.concat_tables([kept, filings_table(list(new_by_key.values()))])
        merged = merged.sort_by(FILINGS_ORDER)
        storage.replace_dir_with_parquet(layout.filings_year_dir(year), merged, row_group_size=FILINGS_ROW_GROUP)
        written += len(new_by_key)
    return written


def compact_filings(storage: Storage, years: Iterable[int] | None = None) -> dict[int, int]:
    """Rewrite each year of filings as one file sorted by company in small row groups.

    The bulk loader writes filings in arrival order, so a company's rows are scattered over every file
    of every year and a per-company read over object storage has to scan the whole table (27 million
    rows). Sorted files with 50k-row groups let the reader skip everything but the one or two groups
    holding the company, by the column statistics parquet keeps per group. Returns {year: rows}.
    """
    out: dict[int, int] = {}
    dirs = storage.ls(layout.FILINGS)
    found = sorted(int(d.rstrip("/").rsplit("=", 1)[-1]) for d in dirs if "year=" in d)
    for year in years or found:
        table = _read_year(storage, year)
        if table.num_rows == 0:
            continue
        merged = table.sort_by(FILINGS_ORDER)
        storage.replace_dir_with_parquet(layout.filings_year_dir(year), merged, row_group_size=FILINGS_ROW_GROUP)
        out[year] = merged.num_rows
        log.info("filings %d: %d rows compacted into one sorted file", year, merged.num_rows)
    return out


def filings_for_cik(storage: Storage, cik: int) -> pa.Table:
    from filings_hub.lake.duck import Duck

    duck = Duck(storage)
    try:
        if not duck.view("filings", f"{layout.FILINGS}/*/*.parquet"):
            return FILINGS_SCHEMA.empty_table()
        return duck.fetch_arrow("SELECT * FROM filings WHERE cik = ? ORDER BY filed_date, accession", [cik])
    finally:
        duck.close()


def refresh_cik_from_api(
    storage: Storage, client: EdgarClient, cik: int, day: date
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Per-company API path (same-day freshness). Stores the raw response under raw/ first."""
    import orjson

    data = client.fetch_submissions(cik)
    storage.write_bytes(layout.raw_api_submissions(day, cik), orjson.dumps(data))
    return parse_company_header(data), parse_filings(data, source="submissions_api")


def touched_ciks(rows: list[dict[str, Any]], forms_prefix: tuple[str, ...]) -> set[int]:
    out = set()
    for r in rows:
        f = (r.get("form") or "").upper()
        if any(f == p or f.startswith(p + "/") for p in forms_prefix):
            out.add(r["cik"])
    return out


def count_filings(storage: Storage) -> int:
    total = 0
    for f in storage.glob(f"{layout.FILINGS}/*/*.parquet"):
        total += storage.read_parquet(f).num_rows
    return total


__all__ = [
    "count_filings",
    "filings_for_cik",
    "load_bulk_submissions",
    "parse_daily_index",
    "refresh_cik_from_api",
    "touched_ciks",
    "upsert_filings",
]

_ = pc  # pyarrow.compute kept importable for callers doing filters
