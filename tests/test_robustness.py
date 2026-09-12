"""Shapes real EDGAR data takes that the happy-path fixtures do not: the pipeline must build, not crash.

Each case is something the SEC actually publishes -- a half-year `fp`, a null period on `sub`, a custom
tag versioned by its accession, a company whose facts file is empty, a submissions page missing arrays.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest

from filings_hub.ingest import sync_facts, sync_statements
from filings_hub.ingest.backfill import run_backfill
from filings_hub.ingest.submissions import parse_company_header, parse_filings
from filings_hub.lake import layout
from filings_hub.lake.duck import Duck
from filings_hub.lake.storage import Storage
from filings_hub.testing import edgar_fixtures as fx


def _fsds_zip(tables: dict[str, list[str]]) -> bytes:
    cols = {"sub": fx.SUB_COLS, "num": fx.NUM_COLS, "pre": fx.PRE_COLS, "tag": fx.TAG_COLS}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for t, rows in tables.items():
            zf.writestr(f"{t}.txt", "\t".join(cols[t]) + "\n" + "\n".join(rows) + "\n")
    return buf.getvalue()


@pytest.fixture()
def seeded(tmp_path):
    st = Storage(str(tmp_path / "lake"))
    fx.seed_raw(st, date(2026, 9, 11))
    return st


def _statements(st: Storage, accession: str) -> list[dict]:
    duck = Duck(st)
    try:
        duck.create_views()
        return duck.fetch_dicts(
            "SELECT statement, line_order, concept, label, value, is_primary_period, checks_passed "
            "FROM statements WHERE accession = ? ORDER BY statement, line_order, period_end",
            [accession],
        )
    finally:
        duck.close()


def test_odd_fsds_rows_build_without_crashing(seeded):
    """One quarter carrying: fp = H1 (a half-year filer), a NULL period and NULL fy, a custom tag whose
    version is the accession, a NULL plabel, a NULL value, a negative line number, an empty tag row."""
    adsh = "0009999999-26-000001"
    fx.COMPANIES[9999999] = {**fx.COMPANIES[fx.APPLE], "name": "Odd Filer", "filings": []}
    try:
        sub = fx._fsds_row(
            fx.SUB_COLS,
            adsh=adsh,
            cik=9999999,
            name="ODD FILER",
            fye="0630",
            form="10-Q",
            period="",
            fy="",
            fp="H1",
            filed="20260515",
            instance=f"{adsh}.xml",
        )
        pre = [
            fx._fsds_row(
                fx.PRE_COLS,
                adsh=adsh,
                report=2,
                line=1,
                stmt="IS",
                inpth=0,
                rfile="H",
                tag="Revenues",
                version="us-gaap/2025",
                plabel="",
                negating=0,
            ),
            fx._fsds_row(
                fx.PRE_COLS,
                adsh=adsh,
                report=2,
                line=2,
                stmt="IS",
                inpth=0,
                rfile="H",
                tag="odd_SpecialCharge",
                version=adsh,
                plabel="Special charge",
                negating=1,
            ),
            fx._fsds_row(
                fx.PRE_COLS,
                adsh=adsh,
                report=2,
                line=-1,
                stmt="IS",
                inpth=0,
                rfile="H",
                tag="NetIncomeLoss",
                version="us-gaap/2025",
                plabel="Net income",
                negating=0,
            ),
            fx._fsds_row(
                fx.PRE_COLS,
                adsh=adsh,
                report=4,
                line=1,
                stmt="BS",
                inpth=0,
                rfile="H",
                tag="Assets",
                version="us-gaap/2025",
                plabel="Total assets",
                negating=0,
            ),
        ]
        num = [
            fx._fsds_row(
                fx.NUM_COLS,
                adsh=adsh,
                tag="Revenues",
                version="us-gaap/2025",
                ddate="20260331",
                qtrs=2,
                uom="USD",
                value=100,
            ),
            fx._fsds_row(
                fx.NUM_COLS,
                adsh=adsh,
                tag="odd_SpecialCharge",
                version=adsh,
                ddate="20260331",
                qtrs=2,
                uom="USD",
                value="",
            ),
            fx._fsds_row(
                fx.NUM_COLS,
                adsh=adsh,
                tag="NetIncomeLoss",
                version="us-gaap/2025",
                ddate="20260331",
                qtrs=2,
                uom="USD",
                value=7,
            ),
            fx._fsds_row(
                fx.NUM_COLS,
                adsh=adsh,
                tag="Assets",
                version="us-gaap/2025",
                ddate="20260331",
                qtrs=0,
                uom="USD",
                value=900,
            ),
        ]
        tag = [
            fx._fsds_row(
                fx.TAG_COLS,
                tag="Revenues",
                version="us-gaap/2025",
                custom=0,
                abstract=0,
                datatype="monetary",
                iord="D",
                crdr="C",
                tlabel="Revenues",
            ),
            fx._fsds_row(
                fx.TAG_COLS,
                tag="odd_SpecialCharge",
                version=adsh,
                custom=1,
                abstract=0,
                datatype="monetary",
                iord="",
                crdr="",
                tlabel="",
            ),
            fx._fsds_row(
                fx.TAG_COLS,
                tag="Assets",
                version="us-gaap/2025",
                custom=0,
                abstract=0,
                datatype="monetary",
                iord="I",
                crdr="D",
                tlabel="Assets",
            ),
            # NetIncomeLoss deliberately has no tag row at all
        ]
        seeded.write_bytes(layout.raw_fsds_zip("2026q2"), _fsds_zip({"sub": [sub], "num": num, "pre": pre, "tag": tag}))
        run = run_backfill(seeded, workers=1, skip_download=True, load_db=False, today=date(2026, 9, 11))
        assert run.status == "ok", run.summary()
        rows = _statements(seeded, adsh)
        by_concept = {r["concept"]: r for r in rows}
        assert set(by_concept) == {"Revenues", "odd_SpecialCharge", "NetIncomeLoss", "Assets"}
        # a null plabel falls back to something displayable, never a crash
        assert by_concept["Revenues"]["label"] in (None, "", "Revenues")
        # a custom tag with no iord and a null value keeps its line
        assert by_concept["odd_SpecialCharge"]["value"] is None
        # a NULL sub.period means no column can be primary except structure rows: nothing crashes,
        # nothing is claimed
        assert all(r["checks_passed"] is None for r in rows)
        # fp = H1 is not a quarter code the plan names: all durations are kept rather than dropped
        assert by_concept["Revenues"]["value"] == 100.0
    finally:
        del fx.COMPANIES[9999999]


def test_empty_fsds_tables_load_and_build(seeded):
    seeded.write_bytes(layout.raw_fsds_zip("2026q2"), _fsds_zip({"sub": [], "num": [], "pre": [], "tag": []}))
    run = run_backfill(seeded, workers=1, skip_download=True, load_db=False, today=date(2026, 9, 11))
    assert run.status == "ok", run.summary()


def test_companyfacts_with_no_facts_and_odd_entries(tmp_path):
    st = Storage(str(tmp_path / "lake"))
    docs = {
        1: {"cik": 1, "entityName": "Empty", "facts": {}},
        2: {"cik": 2, "entityName": "Null units", "facts": {"us-gaap": {"Assets": {"label": None, "units": None}}}},
        3: {
            "cik": 3,
            "entityName": "Odd entries",
            "facts": {
                "us-gaap": {
                    "Assets": {
                        "label": "A",
                        "units": {
                            "USD": [
                                {
                                    "end": "2025-12-31",
                                    "val": 1,
                                    "accn": None,
                                    "fy": None,
                                    "fp": None,
                                    "form": None,
                                    "filed": None,
                                },
                                {
                                    "end": "2025-12-31",
                                    "val": 2,
                                    "accn": "x",
                                    "fy": 2025,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2026-02-01",
                                    "frame": "CY2025Q4I",
                                },
                                {
                                    "end": "2025-12-31",
                                    "val": 2,
                                    "accn": "x",
                                    "fy": 2025,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2026-02-01",
                                    "frame": "CY2025Q4I",
                                },
                            ]
                        },
                    }
                }
            },
        },
    }
    for cik, doc in docs.items():
        n = sync_facts.load_companyfacts_json(st, doc)
        assert n == {1: 0, 2: 0, 3: 3}[cik]
    duck = Duck(st)
    try:
        duck.view("facts", f"{layout.FACTS}/*/*.parquet")
        cur = duck.fetch_dicts("SELECT value, is_current FROM facts WHERE cik = 3 ORDER BY filed NULLS FIRST, value")
    finally:
        duck.close()
    # the entry with no filing date sorts last for currency; the two identical entries tie
    assert sum(1 for r in cur if r["is_current"]) == 1


def test_submissions_with_missing_arrays_and_garbage():
    doc = fx.submissions_doc(fx.APPLE)
    recent = doc["filings"]["recent"]
    recent["items"] = recent["items"][:2]  # shorter than accessionNumber
    recent["size"] = ["", None, *recent["size"][2:]]
    recent["filingDate"] = ["not-a-date", *recent["filingDate"][1:]]
    recent["acceptanceDateTime"] = ["garbage", *recent["acceptanceDateTime"][1:]]
    doc["fiscalYearEnd"] = None
    doc["tickers"] = None
    rows = parse_filings(doc, "submissions_api")
    assert len(rows) == len(fx.APPLE_FILINGS)
    assert rows[0]["filed_date"] is None and rows[0]["year"] is None and rows[0]["acceptance_datetime"] is None
    header = parse_company_header(doc)
    assert header["fiscal_year_end"] is None and header["tickers"] == []


def test_fallback_with_facts_but_no_report_date_or_template():
    rows, checks = sync_statements.build_fallback_rows(
        1,
        "acc",
        "10-Q",
        date(2026, 5, 1),
        date(2026, 3, 31),
        None,
        [
            {
                "taxonomy": "us-gaap",
                "concept": "Assets",
                "unit": "USD",
                "period_start": None,
                "period_end": date(2026, 3, 31),
                "value": 1.0,
                "duration_days": None,
                "label": None,
            }
        ],
        None,
    )
    assert rows and rows[0]["label"] == "Assets" and checks == []
