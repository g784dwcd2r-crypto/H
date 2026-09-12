"""Parse EDGAR submissions JSON (bulk zip entries or the per-company API) into rows."""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any

import orjson
import pyarrow as pa

from filings_hub.ingest.edgar_client import EdgarClient

CIK_FILE_RE = re.compile(r"^CIK(\d{10})\.json$")
PAGE_FILE_RE = re.compile(r"^CIK(\d{10})-submissions-(\d+)\.json$")

FILINGS_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("cik", pa.int64()),
        ("form", pa.string()),
        ("filed_date", pa.date32()),
        ("report_date", pa.date32()),
        ("acceptance_datetime", pa.timestamp("s")),
        ("act", pa.string()),
        ("file_number", pa.string()),
        ("film_number", pa.string()),
        ("items", pa.list_(pa.string())),
        ("size", pa.int64()),
        ("is_xbrl", pa.bool_()),
        ("is_inline_xbrl", pa.bool_()),
        ("primary_doc", pa.string()),
        ("primary_doc_description", pa.string()),
        ("primary_doc_url", pa.string()),
        ("filing_index_url", pa.string()),
        ("source", pa.string()),  # submissions_bulk | submissions_api | daily_index
        ("year", pa.int32()),  # partition column (filed year)
    ]
)

COMPANY_HEADER_SCHEMA = pa.schema(
    [
        ("cik", pa.int64()),
        ("name", pa.string()),
        ("entity_type", pa.string()),
        ("sic", pa.string()),
        ("sic_description", pa.string()),
        ("category", pa.string()),
        ("state_of_incorporation", pa.string()),
        ("state_of_incorporation_description", pa.string()),
        ("fiscal_year_end", pa.string()),
        ("ein", pa.string()),
        ("tickers", pa.list_(pa.string())),
        ("exchanges", pa.list_(pa.string())),
        ("former_names", pa.list_(pa.string())),
        ("business_state", pa.string()),
        ("business_city", pa.string()),
        ("website", pa.string()),
        ("phone", pa.string()),
    ]
)


def _date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _items(s: str | None) -> list[str]:
    if not s:
        return []
    return [i.strip() for i in s.split(",") if i.strip()]


def _str(v: Any) -> str | None:
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def parse_company_header(data: dict[str, Any]) -> dict[str, Any]:
    cik = int(data["cik"])
    addr = (data.get("addresses") or {}).get("business") or {}
    return {
        "cik": cik,
        "name": _str(data.get("name")),
        "entity_type": _str(data.get("entityType")),
        "sic": _str(data.get("sic")),
        "sic_description": _str(data.get("sicDescription")),
        "category": _str(data.get("category")),
        "state_of_incorporation": _str(data.get("stateOfIncorporation")),
        "state_of_incorporation_description": _str(data.get("stateOfIncorporationDescription")),
        "fiscal_year_end": _str(data.get("fiscalYearEnd")),
        "ein": _str(data.get("ein")),
        "tickers": [t for t in (data.get("tickers") or []) if t],
        "exchanges": [e or "" for e in (data.get("exchanges") or [])],
        "former_names": [f.get("name") for f in (data.get("formerNames") or []) if f.get("name")],
        "business_state": _str(addr.get("stateOrCountry")),
        "business_city": _str(addr.get("city")),
        "website": _str(data.get("website")),
        "phone": _str(data.get("phone")),
    }


def parse_filings(data: dict[str, Any], source: str) -> list[dict[str, Any]]:
    """Rows from `filings.recent` (already merged with overflow pages)."""
    cik = int(data["cik"])
    recent = (data.get("filings") or {}).get("recent") or {}
    accs = recent.get("accessionNumber") or []
    n = len(accs)

    def col(name: str) -> list[Any]:
        v = recent.get(name) or []
        return v if len(v) == n else v + [None] * (n - len(v))

    forms = col("form")
    filed = col("filingDate")
    report = col("reportDate")
    acc_dt = col("acceptanceDateTime")
    act = col("act")
    file_no = col("fileNumber")
    film_no = col("filmNumber")
    items = col("items")
    size = col("size")
    is_xbrl = col("isXBRL")
    is_ixbrl = col("isInlineXBRL")
    pdoc = col("primaryDocument")
    pdesc = col("primaryDocDescription")

    rows = []
    for i in range(n):
        accession = accs[i]
        if not accession:
            continue
        fd = _date(filed[i])
        primary = _str(pdoc[i])
        rows.append(
            {
                "accession": accession,
                "cik": cik,
                "form": _str(forms[i]) or "",
                "filed_date": fd,
                "report_date": _date(report[i]),
                "acceptance_datetime": _dt(acc_dt[i]),
                "act": _str(act[i]),
                "file_number": _str(file_no[i]),
                "film_number": _str(film_no[i]),
                "items": _items(items[i]),
                "size": int(size[i]) if size[i] not in (None, "") else None,
                "is_xbrl": bool(is_xbrl[i]),
                "is_inline_xbrl": bool(is_ixbrl[i]),
                "primary_doc": primary,
                "primary_doc_description": _str(pdesc[i]),
                "primary_doc_url": EdgarClient.primary_doc_url(cik, accession, primary) if primary else None,
                "filing_index_url": EdgarClient.filing_index_url(cik, accession),
                "source": source,
                "year": fd.year if fd else None,
            }
        )
    return rows


def merge_pages(base: dict[str, Any], pages: list[dict[str, Any]]) -> dict[str, Any]:
    recent = (base.setdefault("filings", {})).setdefault("recent", {})
    for page in pages:
        for k, v in page.items():
            if isinstance(v, list):
                recent.setdefault(k, []).extend(v)
    return base


def iter_bulk_submissions(zip_path: str) -> Iterator[dict[str, Any]]:
    """Yield merged submissions JSON per company from submissions.zip."""
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        pages: dict[str, list[tuple[int, str]]] = {}
        for n in names:
            m = PAGE_FILE_RE.match(n)
            if m:
                pages.setdefault(m.group(1), []).append((int(m.group(2)), n))
        for n in names:
            m = CIK_FILE_RE.match(n)
            if not m:
                continue
            data = orjson.loads(zf.read(n))
            if not data.get("cik"):
                data["cik"] = int(m.group(1))
            extra = [orjson.loads(zf.read(p)) for _, p in sorted(pages.get(m.group(1), []))]
            yield merge_pages(data, extra)


def filings_table(rows: list[dict[str, Any]]) -> pa.Table:
    return pa.Table.from_pylist(rows, schema=FILINGS_SCHEMA)


def company_header_table(rows: list[dict[str, Any]]) -> pa.Table:
    return pa.Table.from_pylist(rows, schema=COMPANY_HEADER_SCHEMA)
