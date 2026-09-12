from datetime import date

import orjson
import pyarrow as pa

from filings_hub.ingest import sync_filings, sync_universe
from filings_hub.ingest.submissions import (
    FILINGS_SCHEMA,
    filings_table,
    iter_bulk_submissions,
    parse_company_header,
    parse_filings,
)
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage
from filings_hub.testing import edgar_fixtures as fx


def test_parse_company_header():
    h = parse_company_header(fx.submissions_doc(fx.APPLE))
    assert h["cik"] == 320193 and h["fiscal_year_end"] == "0927" and h["tickers"] == ["AAPL"]
    assert h["former_names"] == ["APPLE COMPUTER INC"] and h["business_state"] == "CA"


def test_parse_filings_rows():
    rows = parse_filings(fx.submissions_doc(fx.APPLE), source="submissions_api")
    by_acc = {r["accession"]: r for r in rows}
    k = by_acc[fx.APPLE_10K_FY2025]
    assert k["form"] == "10-K" and k["filed_date"] == date(2025, 10, 31) and k["report_date"] == date(2025, 9, 27)
    assert k["is_xbrl"] and k["is_inline_xbrl"] and k["year"] == 2025
    assert k["primary_doc_url"] == "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm"
    assert k["filing_index_url"].endswith("/0000320193-25-000079-index.htm")
    assert k["acceptance_datetime"].year == 2025
    er = by_acc[fx._acc(fx.APPLE, 2025, 77)]
    assert er["items"] == ["2.02", "9.01"]
    assert by_acc[fx._acc(fx.APPLE, 2025, 85)]["report_date"] is None  # DEF 14A has no period
    assert filings_table(rows).schema == FILINGS_SCHEMA


def test_bulk_zip_merges_overflow_pages(tmp_path):
    p = tmp_path / "submissions.zip"
    p.write_bytes(fx.submissions_zip_bytes())
    docs = {int(d["cik"]): d for d in iter_bulk_submissions(str(p))}
    assert set(docs) == set(fx.COMPANIES)
    assert len(docs[fx.APPLE]["filings"]["recent"]["accessionNumber"]) == len(fx.APPLE_FILINGS)


def test_parse_daily_index():
    text = fx.daily_index_text(
        date(2026, 9, 10),
        [(fx.APPLE, "8-K", "0000320193-26-000099"), (fx.JPM, "4", "0000019617-26-000050")],
    )
    rows = sync_filings.parse_daily_index(text)
    assert [r["accession"] for r in rows] == ["0000320193-26-000099", "0000019617-26-000050"]
    assert rows[0]["filed_date"] == date(2026, 9, 10) and rows[0]["year"] == 2026 and rows[0]["source"] == "daily_index"
    assert (
        rows[0]["filing_index_url"]
        == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000099/0000320193-26-000099-index.htm"
    )
    assert sync_filings.parse_daily_index("garbage\n\n") == []


def test_upsert_filings_semantics(tmp_path):
    st = Storage(str(tmp_path))
    rich = parse_filings(fx.submissions_doc(fx.APPLE), source="submissions_api")
    assert sync_filings.upsert_filings(st, rich) == len(rich)
    assert sync_filings.count_filings(st) == len(rich)
    # a daily-index stub never downgrades a rich row, but new stubs are added
    stub_existing = sync_filings.parse_daily_index(
        fx.daily_index_text(date(2025, 10, 31), [(fx.APPLE, "10-K", fx.APPLE_10K_FY2025)])
    )
    stub_new = sync_filings.parse_daily_index(
        fx.daily_index_text(date(2026, 9, 10), [(fx.APPLE, "8-K", "0000320193-26-000099")])
    )
    assert sync_filings.upsert_filings(st, stub_existing + stub_new) == 1
    t = sync_filings.filings_for_cik(st, fx.APPLE)
    row = {r["accession"]: r for r in t.to_pylist()}
    assert row[fx.APPLE_10K_FY2025]["source"] == "submissions_api"
    assert row["0000320193-26-000099"]["source"] == "daily_index"
    # replace_ciks drops everything for the CIK in the touched years and re-inserts
    subset = [r for r in rich if r["year"] == 2026]
    sync_filings.upsert_filings(st, subset, replace_ciks=[fx.APPLE])
    t = sync_filings.filings_for_cik(st, fx.APPLE)
    assert "0000320193-26-000099" not in t.column("accession").to_pylist()
    assert sync_filings.upsert_filings(st, []) == 0
    assert sync_filings.touched_ciks(rich, ("10-K",)) == {fx.APPLE}
    assert sync_filings.touched_ciks(rich, ("10-K",)) == sync_filings.touched_ciks(
        [r for r in rich if r["form"] == "10-K/A"], ("10-K",)
    )


def test_parse_company_tickers_both_formats():
    rows = sync_universe.parse_company_tickers(fx.company_tickers_exchange_json())
    assert {r["ticker"] for r in rows if r["cik"] == fx.TWO_TICKER} == {"GOOGL", "GOOG"}
    legacy = orjson.dumps({"0": {"cik_str": 320193, "ticker": "aapl", "title": "Apple Inc."}})
    assert sync_universe.parse_company_tickers(legacy) == [
        {"cik": 320193, "ticker": "AAPL", "exchange": None, "name": "Apple Inc."}
    ]


def test_universe_tables(built_lake: Storage):
    companies = {r["cik"]: r for r in built_lake.read_parquet(layout.COMPANIES).to_pylist()}
    tickers = built_lake.read_parquet(layout.TICKERS).to_pylist()
    apple = companies[fx.APPLE]
    assert apple["ticker"] == "AAPL" and apple["exchange"] == "Nasdaq" and apple["is_active"] and apple["is_listed"]
    assert apple["fiscal_year_end"] == "0927" and apple["last_financial_report_form"] == "10-Q"
    rbc = companies[fx.RBC]
    assert rbc["last_financial_report_form"] == "40-F" and rbc["ticker"] == "RY"
    two = [t for t in tickers if t["cik"] == fx.TWO_TICKER]
    assert {t["ticker"] for t in two} == {"GOOGL", "GOOG"} and sum(t["is_primary"] for t in two) == 1
    old = companies[fx.OLD]
    assert not old["is_listed"] and not old["is_active"] and old["ticker"] is None
    assert old["last_financial_report_date"] == date(2019, 3, 15)


def test_build_companies_without_stats():
    from filings_hub.ingest.submissions import company_header_table

    headers = company_header_table([parse_company_header(fx.submissions_doc(fx.APPLE))])
    tickers = sync_universe.build_tickers([], headers)
    assert tickers.to_pylist()[0]["source"] == "submissions"
    companies = sync_universe.build_companies(headers, tickers, None)
    assert companies.num_rows == 1 and companies.to_pylist()[0]["filing_count"] == 0
    assert isinstance(companies, pa.Table)
