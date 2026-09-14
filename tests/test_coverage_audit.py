"""Step 4: the coverage-and-applicability audit. Controlled lake with known gaps, then a real smoke."""

from datetime import date

import pyarrow as pa

from filings_hub import coverage_audit as ca
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage

# cik, name, exchange, sic, is_active, is_listed, lfr_form, lfr_date
COMPANIES = [
    (1, "Apple", "Nasdaq", "3571", True, True, "10-K", date(2025, 9, 27)),   # complete: statements + a check
    (2, "Foreign SA", "NYSE", "1234", True, True, "20-F", date(2025, 6, 30)),  # gap: foreign filer
    (3, "DarkCo", "NYSE", "1234", False, True, "10-K", date(2016, 3, 1)),      # gap: gone dark
    (4, "Blank Acquisition Corp", "Nasdaq", "6770", True, True, "10-K", date(2025, 1, 1)),  # gap: SPAC
    (5, "Normal Inc", "Nasdaq", "3571", True, True, "10-K", date(2025, 1, 1)),  # gap: unexplained
    (6, "NoCheckCo", "Nasdaq", "3571", True, True, "10-K", date(2025, 1, 1)),   # statements but zero checks
    (7, "ShellCo", None, "6770", False, False, None, None),                     # never filed financials
]


def _seed(st: Storage) -> None:
    st.write_parquet(
        layout.COMPANIES,
        pa.table(
            {
                "cik": [c[0] for c in COMPANIES],
                "name": [c[1] for c in COMPANIES],
                "exchange": [c[2] for c in COMPANIES],
                "sic": [c[3] for c in COMPANIES],
                "is_active": [c[4] for c in COMPANIES],
                "is_listed": [c[5] for c in COMPANIES],
                "last_financial_report_form": [c[6] for c in COMPANIES],
                "last_financial_report_date": [c[7] for c in COMPANIES],
            }
        ),
    )
    # statements for cik 1 and 6; a check only for cik 1
    for cik, acc in [(1, "a1"), (6, "a6")]:
        st.write_parquet(
            f"{layout.statements_cik_dir(cik)}/s.parquet",
            pa.table({"cik": [cik], "accession": [acc]}),
        )
    st.write_parquet(
        f"{layout.statement_checks_cik_dir(1)}/c.parquet",
        pa.table(
            {"cik": [1], "accession": ["a1"], "passed": [True], "check_name": ["gross_profit"], "statement": ["IS"]}
        ),
    )


def test_audit_counts_tiers_gaps_and_silent_failures(tmp_path):
    st = Storage(str(tmp_path))
    _seed(st)
    rep = ca.coverage_audit(st)

    assert rep["companies"] == 7
    nn = rep["tiers"]["nyse_nasdaq"]
    assert nn["companies"] == 6  # ciks 1..6
    assert nn["with_statements"] == 2  # ciks 1 and 6
    assert nn["with_any_check"] == 1  # only cik 1
    assert nn["zero_applicable_check"] == 1  # cik 6: has statements, no check ran
    assert rep["tiers"]["everything_else"]["companies"] == 1  # cik 7

    gap = rep["gaps"]["nyse_nasdaq"]
    assert gap["total"] == 4  # ciks 2, 3, 4, 5
    assert gap["reasons"] == {
        "foreign filer (20-F / 40-F)": 1,
        "gone dark (no recent filing)": 1,
        "blank-check / SPAC": 1,
        "unexplained - investigate": 1,
    }
    assert [g["name"] for g in gap["unexplained"]] == ["Normal Inc"]

    assert rep["zero_applicable_check_total"] == 1
    assert rep["gross_profit_rate"] == 1.0  # gross_profit ran on the one income statement checked


def test_shell_company_that_never_filed_is_not_a_gap(tmp_path):
    st = Storage(str(tmp_path))
    _seed(st)
    rep = ca.coverage_audit(st)
    # cik 7 filed no financial report, so it is expected to have no statements: not counted as missing
    assert rep["gaps"]["everything_else"]["total"] == 0


def test_empty_lake_says_so(tmp_path):
    rep = ca.coverage_audit(Storage(str(tmp_path)))
    assert rep["companies"] == 0 and "no companies" in rep["message"]


def test_format_report_reads(tmp_path):
    st = Storage(str(tmp_path))
    _seed(st)
    text = ca.format_report(ca.coverage_audit(st))
    assert "Coverage audit: 7 companies" in text
    assert "getting no arithmetic check" in text.lower()
    assert "Gross-profit check applies to 100.0 %" in text


def test_runs_on_the_real_built_lake(built_lake):
    rep = ca.coverage_audit(built_lake)
    assert rep["companies"] > 0
    assert set(rep["tiers"]) <= set(ca.TIERS)
    assert 0.0 <= rep["gross_profit_rate"] <= 1.0
    assert isinstance(rep["zero_applicable_check_total"], int)
    assert isinstance(ca.format_report(rep), str) and ca.format_report(rep)
