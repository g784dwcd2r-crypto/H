from datetime import date

import orjson
import pyarrow as pa

from filings_hub.ingest import sync_filings, sync_universe
from filings_hub.ingest.submissions import (
    COMPANY_HEADER_SCHEMA,
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
    # every field of the document: addresses, owner org, flags, the former-names list with its dates
    assert (
        h["mailing_city"] == "CUPERTINO"
        and h["mailing_zip"] == "95014"
        and h["business_street1"] == "ONE APPLE PARK WAY"
    )
    assert h["business_is_foreign"] is False and h["owner_org"] == "06 Technology" and h["phone"] == "(408) 996-1010"
    assert h["insider_transaction_for_issuer_exists"] is True and h["insider_transaction_for_owner_exists"] is False
    assert '"from":"1997-07-28"' in h["former_names_json"]
    # a key the parser has no column for is kept verbatim, never dropped
    assert h["header_extra"] == '{"someFutureField":{"added":"by the SEC after this parser was written"}}'
    assert set(h) == set(COMPANY_HEADER_SCHEMA.names)


def test_parse_filings_rows():
    rows = parse_filings(fx.submissions_doc(fx.APPLE), source="submissions_api")
    by_acc = {r["accession"]: r for r in rows}
    k = by_acc[fx.APPLE_10K_FY2025]
    assert k["form"] == "10-K" and k["filed_date"] == date(2025, 10, 31) and k["report_date"] == date(2025, 9, 27)
    assert k["is_xbrl"] and k["is_inline_xbrl"] and k["year"] == 2025 and k["core_type"] == "10-K"
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
    row = companies.to_pylist()[0]
    assert row["mailing_zip"] == "95014" and row["owner_org"] == "06 Technology" and row["header_extra"]
    assert isinstance(companies, pa.Table)


def test_upsert_keys_on_cik_and_accession_for_cofiled_documents(tmp_path):
    """One EDGAR accession can belong to several CIKs: a parent and its operating partnership file a
    combined 10-K under a single accession, and the daily index lists one line per co-filer. Keying the
    merge on accession alone made each co-filer's row delete the other's."""
    st = Storage(str(tmp_path))
    parent, op_unit = 1063761, 1022344
    accession = "0001063761-26-000010"
    fx.COMPANIES[parent] = {**fx.COMPANIES[fx.APPLE], "name": "Simon Property Group Inc", "filings": []}
    fx.COMPANIES[op_unit] = {**fx.COMPANIES[fx.APPLE], "name": "Simon Property Group LP", "filings": []}
    try:
        text = fx.daily_index_text(date(2026, 2, 20), [(parent, "10-K", accession), (op_unit, "10-K", accession)])
        rows = sync_filings.parse_daily_index(text)
        assert len(rows) == 2
        assert sync_filings.upsert_filings(st, rows) == 2

        stored = {(r["cik"], r["accession"]) for r in _all_filings(st)}
        assert stored == {(parent, accession), (op_unit, accession)}

        # refreshing one co-filer from the API must not remove the other's row
        api_row = dict(rows[0], source="submissions_api", report_date=date(2025, 12, 31))
        sync_filings.upsert_filings(st, [api_row], replace_ciks=[parent])
        after = {(r["cik"], r["accession"], r["source"]) for r in _all_filings(st)}
        assert after == {
            (parent, accession, "submissions_api"),
            (op_unit, accession, "daily_index"),
        }
    finally:
        del fx.COMPANIES[parent], fx.COMPANIES[op_unit]


def test_daily_index_stub_does_not_downgrade_only_its_own_cik(tmp_path):
    st = Storage(str(tmp_path))
    accession = "0000000001-26-000001"
    rich = [
        {**r, "cik": cik, "source": "submissions_api"}
        for cik, r in (
            (
                11,
                sync_filings.parse_daily_index(fx.daily_index_text(date(2026, 2, 20), [(fx.APPLE, "10-K", accession)]))[
                    0
                ],
            ),
        )
    ]
    sync_filings.upsert_filings(st, rich)
    stub = sync_filings.parse_daily_index(fx.daily_index_text(date(2026, 2, 20), [(fx.APPLE, "10-K", accession)]))
    stub[0]["cik"] = 11
    assert sync_filings.upsert_filings(st, stub) == 0  # same (cik, accession) and poorer: not written
    assert [r["source"] for r in _all_filings(st)] == ["submissions_api"]


def _all_filings(storage: Storage) -> list[dict]:
    rows = []
    for f in storage.glob(f"{layout.FILINGS}/*/*.parquet"):
        rows.extend(storage.read_parquet(f).to_pylist())
    return rows
