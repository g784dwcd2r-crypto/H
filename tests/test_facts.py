from datetime import date

import duckdb
import pyarrow as pa

from filings_hub.ingest import sync_facts
from filings_hub.lake import layout
from filings_hub.lake.duck import Duck
from filings_hub.lake.storage import Storage
from filings_hub.testing import edgar_fixtures as fx


def test_parse_and_finalize_companyfacts():
    rows = sync_facts.parse_companyfacts(fx.companyfacts_docs()[fx.APPLE])
    t = sync_facts.finalize_facts(pa.Table.from_pylist(rows, schema=sync_facts.FACTS_SCHEMA))
    rev = [
        r
        for r in t.to_pylist()
        if r["concept"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
        and r["period_end"] == date(2024, 9, 28)
    ]
    assert len(rev) == 2  # original + restated
    cur = {r["accession"]: r["is_current"] for r in rev}
    assert cur[fx.APPLE_10K_FY2025] is True and cur[fx.APPLE_10K_FY2024] is False
    assert {r["duration_kind"] for r in rev} == {"annual"}
    dei = [r for r in t.to_pylist() if r["taxonomy"] == "dei"]
    assert dei and dei[0]["duration_kind"] == "instant" and dei[0]["unit"] == "shares"


def test_duration_kind_sql_matches_python():
    con = duckdb.connect()
    for days in (None, 79, 80, 91, 100, 101, 180, 182, 270, 275, 360, 366, 380, 381, 1000):
        expected = sync_facts.duration_kind(days)
        got = con.execute(
            f"SELECT {sync_facts.DURATION_KINDS_SQL} FROM (SELECT ?::DATE AS period_start, ?::INTEGER AS duration_days)",
            [None if days is None else "2020-01-01", days],
        ).fetchone()[0]
        assert got == expected, days


def test_empty_and_bad_values():
    doc = {
        "cik": 1,
        "facts": {
            "us-gaap": {
                "X": {
                    "label": "x",
                    "units": {
                        "USD": [
                            {
                                "end": "2020-12-31",
                                "val": None,
                                "accn": "a",
                                "fy": 2020,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2021-02-01",
                            },
                            {
                                "end": "",
                                "val": 1,
                                "accn": "a",
                                "fy": 2020,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2021-02-01",
                            },
                            {
                                "end": "2020-12-31",
                                "val": "12.5",
                                "accn": "a",
                                "fy": "",
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2021-02-01",
                            },
                            {
                                "end": "2020-12-31",
                                "val": "n/a",
                                "accn": "a",
                                "fy": 2020,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2021-02-01",
                            },
                        ]
                    },
                }
            }
        },
    }
    rows = sync_facts.parse_companyfacts(doc)
    assert len(rows) == 1 and rows[0]["value"] == 12.5 and rows[0]["fy"] is None
    assert sync_facts.finalize_facts(sync_facts.FACTS_SCHEMA.empty_table()).num_rows == 0


def test_apple_revenue_matches_10q(built_lake: Storage):
    duck = Duck(built_lake)
    duck.view("facts", f"{layout.FACTS}/*/*.parquet")
    row = duck.fetch_dicts(
        "SELECT value, accession FROM facts WHERE cik = ? AND concept = 'RevenueFromContractWithCustomerExcludingAssessedTax' "
        "AND period_start = DATE '2025-09-28' AND period_end = DATE '2025-12-27' AND is_current",
        [fx.APPLE],
    )
    assert row == [{"value": 140_000_000_000.0, "accession": fx.APPLE_10Q_Q1_2026}]
    hist = duck.fetch_dicts(
        "SELECT value, is_current FROM facts WHERE cik = ? AND concept = 'RevenueFromContractWithCustomerExcludingAssessedTax' "
        "AND period_end = DATE '2024-09-28' ORDER BY filed",
        [fx.APPLE],
    )
    assert hist == [
        {"value": 391_035_000_000.0, "is_current": False},
        {"value": 391_036_000_000.0, "is_current": True},
    ]
    duck.close()


def test_bulk_loader_with_workers(tmp_path):
    st = Storage(str(tmp_path))
    st.write_bytes("cf.zip", fx.companyfacts_zip_bytes())
    r = sync_facts.load_bulk_companyfacts(st, "cf.zip", workers=2, batch=1)
    assert r["companies"] == 4 and r["failures"] == [] and r["rows"] > 0
    assert st.exists(f"{layout.facts_cik_dir(fx.APPLE)}/part-0.parquet")


def test_bulk_loader_reports_bad_company(tmp_path):
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CIK0000000001.json", b"{not json")
    st = Storage(str(tmp_path))
    st.write_bytes("cf.zip", buf.getvalue())
    r = sync_facts.load_bulk_companyfacts(st, "cf.zip", workers=1)
    assert r["companies"] == 0 and len(r["failures"]) == 1
