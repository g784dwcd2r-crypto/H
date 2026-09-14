"""Step 2: a reused ticker symbol must resolve to the company that still holds it, not the dead one."""

from datetime import date

import pyarrow as pa

from filings_hub.db.database import Database
from filings_hub.ingest.sync_universe import TICKERS_SCHEMA, mark_current_owner
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage


def _companies(rows: list[tuple[int, bool, date | None, int]]) -> pa.Table:
    return pa.table(
        {
            "cik": [r[0] for r in rows],
            "is_active": [r[1] for r in rows],
            "last_filing_date": [r[2] for r in rows],
            "filing_count": [r[3] for r in rows],
        }
    )


def _tickers(rows: list[tuple[int, str]]) -> pa.Table:
    return pa.Table.from_pylist(
        [{"cik": c, "ticker": t, "exchange": None, "is_primary": True, "source": "x"} for c, t in rows],
        schema=TICKERS_SCHEMA,
    )


def test_current_owner_is_the_live_company():
    tickers = _tickers([(100, "SHARE"), (200, "SHARE")])
    companies = _companies([(100, True, date(2026, 9, 1), 50), (200, False, date(2018, 1, 1), 10)])
    out = {r["cik"]: r["is_current"] for r in mark_current_owner(tickers, companies).to_pylist()}
    assert out == {100: True, 200: False}


def test_single_owner_is_always_current():
    out = mark_current_owner(_tickers([(300, "SOLO")]), _companies([(300, False, None, 0)])).to_pylist()
    assert out[0]["is_current"] is True  # even a defunct sole owner keeps the symbol


def test_all_dead_falls_to_the_most_recent():
    tickers = _tickers([(400, "GONE"), (500, "GONE")])
    companies = _companies([(400, False, date(2015, 5, 1), 20), (500, False, date(2019, 5, 1), 5)])
    out = {r["cik"]: r["is_current"] for r in mark_current_owner(tickers, companies).to_pylist()}
    assert out == {400: False, 500: True}  # 500 filed more recently


def test_two_live_owners_fall_to_the_most_recent():
    tickers = _tickers([(600, "DUAL"), (700, "DUAL")])
    companies = _companies([(600, True, date(2026, 6, 30), 40), (700, True, date(2026, 9, 30), 40)])
    out = {r["cik"]: r["is_current"] for r in mark_current_owner(tickers, companies).to_pylist()}
    assert out == {600: False, 700: True}


def test_resolve_and_search_pick_the_current_owner(tmp_path):
    """The exact queries the API runs, over a real DuckDB view, land on the live company only."""
    st = Storage(str(tmp_path))
    tickers = mark_current_owner(
        _tickers([(100, "SHARE"), (200, "SHARE"), (300, "SOLO")]),
        _companies([(100, True, date(2026, 9, 1), 50), (200, False, date(2018, 1, 1), 10), (300, True, date(2026, 1, 1), 5)]),
    )
    st.write_parquet(layout.TICKERS, tickers)
    db = Database("", st)
    try:
        # resolve_cik ordering
        resolved = db.query(
            "SELECT cik FROM tickers WHERE ticker = ? ORDER BY (is_current IS TRUE) DESC, is_primary DESC LIMIT 1",
            ["SHARE"],
        )
        assert resolved[0]["cik"] == 100

        # the search exact-ticker branch never surfaces the dead company
        found = db.query("SELECT cik FROM tickers WHERE ticker = ? AND is_current IS NOT FALSE", ["SHARE"])
        assert [r["cik"] for r in found] == [100]

        # a single-owner symbol still resolves
        assert db.query("SELECT cik FROM tickers WHERE ticker = ? AND is_current IS NOT FALSE", ["SOLO"])[0]["cik"] == 300
    finally:
        db.close()


def test_pipeline_sets_one_current_owner_per_symbol(built_lake):
    """The real universe build fills is_current, and no symbol has two current owners."""
    rows = built_lake.read_parquet(layout.TICKERS).to_pylist()
    assert rows and all(r["is_current"] is not None for r in rows)
    from collections import Counter

    current_per_symbol = Counter(r["ticker"] for r in rows if r["is_current"])
    assert current_per_symbol and max(current_per_symbol.values()) == 1
