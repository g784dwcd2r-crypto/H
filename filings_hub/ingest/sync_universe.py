"""Universe: companies + tickers tables from company_tickers_exchange.json and submissions headers."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import orjson
import pyarrow as pa

from filings_hub.ingest.submissions import COMPANY_HEADER_SCHEMA, company_header_table
from filings_hub.lake import layout
from filings_hub.lake.duck import Duck
from filings_hub.lake.storage import Storage

log = logging.getLogger(__name__)

FINANCIAL_REPORT_FORMS = (
    "10-K",
    "10-Q",
    "10-KT",
    "10-QT",
    "20-F",
    "40-F",
    "10-K405",
    "10-KSB",
    "10-QSB",
)
ACTIVE_WINDOW_DAYS = 548
HEADERS = "companies/headers.parquet"  # 18 months: a filer with a financial report this recent is "active"

# Header columns copied onto the companies table as they are (everything the SEC says about the
# filer except the ticker lists, which the tickers table resolves into one primary listing).
HEADER_PASSTHROUGH = [
    f.name
    for f in COMPANY_HEADER_SCHEMA
    if f.name not in ("cik", "name", "sic", "sic_description", "tickers", "exchanges")
]

COMPANIES_SCHEMA = pa.schema(
    [
        ("cik", pa.int64()),
        ("name", pa.string()),
        ("ticker", pa.string()),
        ("exchange", pa.string()),
        ("sic", pa.string()),
        ("sic_description", pa.string()),
    ]
    + [COMPANY_HEADER_SCHEMA.field(n) for n in HEADER_PASSTHROUGH]
    + [
        ("is_listed", pa.bool_()),
        ("is_active", pa.bool_()),
        ("last_filing_date", pa.date32()),
        ("last_financial_report_date", pa.date32()),
        ("last_financial_report_form", pa.string()),
        ("filing_count", pa.int64()),
    ]
)

TICKERS_SCHEMA = pa.schema(
    [
        ("cik", pa.int64()),
        ("ticker", pa.string()),
        ("exchange", pa.string()),
        ("is_primary", pa.bool_()),  # this company's primary ticker (a company can list under several)
        ("is_current", pa.bool_()),  # this company currently owns the ticker symbol (see mark_current_owner)
        ("source", pa.string()),
    ]
)


def parse_company_tickers(raw: bytes) -> list[dict[str, Any]]:
    """Both SEC ticker files: company_tickers_exchange.json ({fields,data}) and company_tickers.json."""
    data = orjson.loads(raw)
    rows: list[dict[str, Any]] = []
    if isinstance(data, dict) and "fields" in data and "data" in data:
        idx = {f: i for i, f in enumerate(data["fields"])}
        for rec in data["data"]:
            ticker = rec[idx["ticker"]]
            if not ticker:
                continue
            rows.append(
                {
                    "cik": int(rec[idx["cik"]]),
                    "ticker": str(ticker).upper(),
                    "exchange": (rec[idx.get("exchange", -1)] if "exchange" in idx else None) or None,
                    "name": rec[idx["name"]] if "name" in idx else None,
                }
            )
    elif isinstance(data, dict):
        for rec in data.values():
            if isinstance(rec, dict) and rec.get("ticker"):
                rows.append(
                    {
                        "cik": int(rec["cik_str"]),
                        "ticker": str(rec["ticker"]).upper(),
                        "exchange": None,
                        "name": rec.get("title"),
                    }
                )
    return rows


def build_tickers(ticker_rows: list[dict[str, Any]], headers: pa.Table) -> pa.Table:
    """Union of SEC ticker file and submissions-header tickers; one primary per CIK."""
    seen: set[tuple[int, str]] = set()
    out: list[dict[str, Any]] = []
    for r in ticker_rows:
        key = (r["cik"], r["ticker"])
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "cik": r["cik"],
                "ticker": r["ticker"],
                "exchange": r.get("exchange"),
                "source": "company_tickers",
            }
        )
    for h in headers.select(["cik", "tickers", "exchanges"]).to_pylist():
        for i, t in enumerate(h["tickers"] or []):
            key = (h["cik"], t.upper())
            if key in seen:
                continue
            seen.add(key)
            ex = (h["exchanges"] or [None] * (i + 1))[i] if i < len(h["exchanges"] or []) else None
            out.append(
                {
                    "cik": h["cik"],
                    "ticker": t.upper(),
                    "exchange": ex or None,
                    "source": "submissions",
                }
            )
    # primary = first ticker listed for the CIK (SEC lists the primary listing first)
    primary_seen: set[int] = set()
    for r in out:
        r["is_primary"] = r["cik"] not in primary_seen
        primary_seen.add(r["cik"])
    return pa.Table.from_pylist(out, schema=TICKERS_SCHEMA)


def mark_current_owner(tickers: pa.Table, companies: pa.Table) -> pa.Table:
    """Set `is_current`: for each ticker symbol, which company owns it now.

    A symbol gets reused: a company delists and, years later, another company takes the same ticker.
    Both keep a row here (we never drop the history), so a bare `WHERE ticker = ?` matches two
    companies and a lookup can land on the dead one. `is_current` breaks that tie once, at build time,
    so every query stays a simple filter. The winner is the company still filing, most recently, with
    the most filings; a stable CIK order settles a true draw. A symbol with a single owner is current
    by definition, including one whose only owner is defunct.
    """
    by_cik = {
        r["cik"]: (bool(r["is_active"]), r["last_filing_date"], r["filing_count"] or 0)
        for r in companies.select(["cik", "is_active", "last_filing_date", "filing_count"]).to_pylist()
    }

    def rank(cik: int) -> tuple:
        active, last, count = by_cik.get(cik, (False, None, 0))
        # active first, then most recent filing, then most filings; None date loses. Negatives sort
        # descending under Python's ascending sort, so the winner is the minimum.
        return (not active, -(last.toordinal() if last else 0), -count, cik)

    rows = tickers.to_pylist()
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_ticker[r["ticker"]].append(r)
    for group in by_ticker.values():
        winner = min(group, key=lambda r: rank(r["cik"]))
        for r in group:
            r["is_current"] = r is winner
    return pa.Table.from_pylist(rows, schema=TICKERS_SCHEMA)


def build_companies(
    headers: pa.Table, tickers: pa.Table, filings_stats: pa.Table | None, today: date | None = None
) -> pa.Table:
    """Companies table. `filings_stats` (optional) has cik, last_filing_date, last_financial_report_date,
    last_financial_report_form, filing_count — from the filings table."""
    today = today or date.today()
    cutoff = today - timedelta(days=ACTIVE_WINDOW_DAYS)
    primary: dict[int, dict[str, Any]] = {}
    for t in tickers.to_pylist():
        if t["is_primary"]:
            primary[t["cik"]] = t
    stats: dict[int, dict[str, Any]] = {}
    if filings_stats is not None:
        for s in filings_stats.to_pylist():
            stats[s["cik"]] = s

    rows = []
    for h in headers.to_pylist():
        cik = h["cik"]
        p = primary.get(cik)
        st = stats.get(cik, {})
        last_fin = st.get("last_financial_report_date")
        is_listed = p is not None
        is_active = is_listed or (last_fin is not None and last_fin >= cutoff)
        rows.append(
            {
                "cik": cik,
                "name": h["name"],
                "ticker": p["ticker"] if p else None,
                "exchange": (p["exchange"] if p else None) or ((h["exchanges"] or [None])[0] or None),
                "sic": h["sic"],
                "sic_description": h["sic_description"],
                **{n: h.get(n) for n in HEADER_PASSTHROUGH},
                "is_listed": is_listed,
                "is_active": is_active,
                "last_filing_date": st.get("last_filing_date"),
                "last_financial_report_date": last_fin,
                "last_financial_report_form": st.get("last_financial_report_form"),
                "filing_count": st.get("filing_count", 0) or 0,
            }
        )
    rows.sort(key=lambda r: r["cik"])
    return pa.Table.from_pylist(rows, schema=COMPANIES_SCHEMA)


def filings_stats(duck: Duck) -> pa.Table | None:
    if not duck.view("filings", f"{layout.FILINGS}/*/*.parquet"):
        return None
    forms = ", ".join(f"'{f}'" for f in FINANCIAL_REPORT_FORMS)
    return duck.fetch_arrow(
        f"""
        WITH fin AS (
            SELECT cik, filed_date, form,
                   row_number() OVER (PARTITION BY cik ORDER BY filed_date DESC, accession DESC) AS rn
            FROM filings WHERE form IN ({forms})
        )
        SELECT f.cik,
               max(f.filed_date) AS last_filing_date,
               any_value(fin.filed_date) AS last_financial_report_date,
               any_value(fin.form) AS last_financial_report_form,
               count(*) AS filing_count
        FROM filings f LEFT JOIN fin ON fin.cik = f.cik AND fin.rn = 1
        GROUP BY f.cik
        """
    )


def sync_universe(
    storage: Storage, headers: pa.Table, ticker_json: bytes | None, today: date | None = None
) -> tuple[pa.Table, pa.Table]:
    """Write companies + tickers parquet. `headers` comes from the submissions pass."""
    ticker_rows = parse_company_tickers(ticker_json) if ticker_json else []
    tickers = build_tickers(ticker_rows, headers)
    duck = Duck(storage)
    try:
        stats = filings_stats(duck)
    finally:
        duck.close()
    companies = build_companies(headers, tickers, stats, today)
    # companies now carries is_active / last_filing_date / filing_count, so we can settle which
    # company currently owns each ticker symbol that more than one company has claimed.
    tickers = mark_current_owner(tickers, companies)
    storage.write_parquet(HEADERS, headers)
    storage.write_parquet(layout.COMPANIES, companies)
    storage.write_parquet(layout.TICKERS, tickers)
    log.info("universe: %d companies, %d tickers", companies.num_rows, tickers.num_rows)
    return companies, tickers


def upsert_headers(
    storage: Storage,
    new_headers: pa.Table,
    ticker_json: bytes | None = None,
    today: date | None = None,
) -> None:
    """Merge refreshed submission headers into the persisted headers table and rebuild the universe."""
    existing: dict[int, dict[str, Any]] = {}
    if storage.exists(HEADERS):
        for h in storage.read_parquet(HEADERS).to_pylist():
            existing[h["cik"]] = h
    for h in new_headers.to_pylist():
        existing[h["cik"]] = h
    headers = company_header_table(sorted(existing.values(), key=lambda r: r["cik"]))
    if ticker_json is None:
        from filings_hub.ingest.bulk import latest_raw

        rel = latest_raw(storage, "company_tickers")
        ticker_json = storage.read_bytes(rel) if rel else None
    sync_universe(storage, headers, ticker_json, today)
