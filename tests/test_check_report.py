"""The per-check error report: which rule fails, how badly, and for whom."""

import pyarrow as pa

from filings_hub import check_report as cr
from filings_hub.ingest.sync_statements import CHECKS_SCHEMA
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage

# check_name, statement, lhs, rhs, passed
ROWS = [
    ("assets_eq_liabilities_and_equity", "BS", 1_000_000, 1_000_000, True),   # exact pass
    ("assets_eq_liabilities_and_equity", "BS", 1_000_000, 1_000_010, True),   # tiny pass
    ("assets_eq_liabilities_and_equity", "BS", 1_000_000, 1_007_000, False),  # just-over fail (~1.4x)
    ("assets_eq_liabilities_and_equity", "BS", 1_000_000, 1_500_000, False),  # >10x fail (worst)
    ("gross_profit", "IS", 500, 512, False),                                  # mid fail (~4.7x, 2.3% off)
]


def _seed(st: Storage, with_company: bool = True) -> None:
    rows = []
    for i, (name, stmt, lhs, rhs, passed) in enumerate(ROWS):
        rows.append(
            {
                "accession": f"a{i}",
                "cik": 42,
                "statement": stmt,
                "check_name": name,
                "passed": passed,
                "lhs": float(lhs),
                "rhs": float(rhs),
                "difference": float(lhs) - float(rhs),
                "detail": "",
                "source": "fsds",
            }
        )
    st.write_parquet(f"{layout.statement_checks_cik_dir(42)}/c.parquet", pa.Table.from_pylist(rows, schema=CHECKS_SCHEMA))
    if with_company:
        st.write_parquet(layout.COMPANIES, pa.table({"cik": [42], "name": ["Acme Corp"]}))


def test_per_check_failure_counts_and_severity(tmp_path):
    st = Storage(str(tmp_path))
    _seed(st)
    rep = cr.failure_report(st)

    assert rep["total"] == 5
    assert rep["failed"] == 3
    assert rep["companies_checked"] == 1
    assert rep["companies_with_failure"] == 1

    by = {r["check_name"]: r for r in rep["per_check"]}
    bs = by["assets_eq_liabilities_and_equity"]
    assert bs["total"] == 4 and bs["passed"] == 2 and bs["failed"] == 2
    assert bs["just_over"] == 1 and bs["far"] == 1  # the ~1.4x and the huge one
    gp = by["gross_profit"]
    assert gp["failed"] == 1 and gp["mid"] == 1  # 8% off is between 2x and 10x of 0.5%


def test_worst_offenders_named_and_ordered(tmp_path):
    st = Storage(str(tmp_path))
    _seed(st)
    rep = cr.failure_report(st, examples=5)
    assert rep["worst"], "expected worst-offender rows"
    assert rep["worst"][0]["name"] == "Acme Corp"  # company name joined
    # ordered worst-first: the 50%-off balance sheet is the biggest miss
    assert rep["worst"][0]["check_name"] == "assets_eq_liabilities_and_equity"
    qs = [w["q"] for w in rep["worst"]]
    assert qs == sorted(qs, reverse=True)


def test_report_without_companies_still_runs(tmp_path):
    st = Storage(str(tmp_path))
    _seed(st, with_company=False)
    rep = cr.failure_report(st)
    assert rep["failed"] == 3
    assert rep["worst"][0]["name"] is None  # no companies table, falls back gracefully


def test_empty_lake(tmp_path):
    rep = cr.failure_report(Storage(str(tmp_path)))
    assert rep["total"] == 0 and "no statement_checks" in rep["message"]


def test_format_reads(tmp_path):
    st = Storage(str(tmp_path))
    _seed(st)
    text = cr.format_failure_report(cr.failure_report(st))
    assert "By check (worst first)" in text
    assert "Balance sheet balances" in text
    assert "Acme Corp" in text
