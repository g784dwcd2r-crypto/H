"""The per-check error report: which rule fails, how badly, and for whom."""

from datetime import date

import pyarrow as pa

from filings_hub import check_report as cr
from filings_hub.ingest.sync_statements import CHECKS_SCHEMA
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage

# check_name, statement, lhs, rhs, passed
ROWS = [
    ("assets_eq_liabilities_and_equity", "BS", 1_000_000, 1_000_000, True),  # exact pass
    ("assets_eq_liabilities_and_equity", "BS", 1_000_000, 1_000_010, True),  # tiny pass
    ("assets_eq_liabilities_and_equity", "BS", 1_000_000, 1_007_000, False),  # just-over fail (~1.4x)
    ("assets_eq_liabilities_and_equity", "BS", 1_000_000, 1_500_000, False),  # >10x fail (worst)
    ("gross_profit", "IS", 500, 512, False),  # mid fail (~4.7x, 2.3% off)
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
    st.write_parquet(
        f"{layout.statement_checks_cik_dir(42)}/c.parquet", pa.Table.from_pylist(rows, schema=CHECKS_SCHEMA)
    )
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


def test_explain_shows_value_vs_presented_for_a_company(tmp_path):
    """explain() surfaces a company's failing check and the raw vs display-signed values behind it."""
    st = Storage(str(tmp_path))
    # a failing balance-sheet check for cik 7: lhs (Assets) came in negative, rhs positive
    st.write_parquet(
        f"{layout.statement_checks_cik_dir(7)}/c.parquet",
        pa.Table.from_pylist(
            [
                {
                    "accession": "z1",
                    "cik": 7,
                    "statement": "BS",
                    "check_name": "assets_eq_liabilities_and_equity",
                    "passed": False,
                    "lhs": -100.0,
                    "rhs": 100.0,
                    "difference": -200.0,
                    "detail": "",
                    "source": "fsds",
                }
            ],
            schema=CHECKS_SCHEMA,
        ),
    )
    # the statement lines: Assets filed as -100 but presented as +100 (negating); Liabilities +100
    st.write_parquet(
        f"{layout.statements_cik_dir(7)}/s.parquet",
        pa.table(
            {
                "cik": [7, 7],
                "accession": ["z1", "z1"],
                "statement": ["BS", "BS"],
                "concept": ["Assets", "Liabilities"],
                "value": [-100.0, 100.0],
                "value_presented": [100.0, 100.0],
                "negating": [True, False],
                "is_primary_period": [True, True],
                "segments": ["", ""],
                "period_end": [None, None],
                "line_order": [1, 2],
            }
        ),
    )
    rep = cr.explain(st, 7)
    assert len(rep["fails"]) == 1 and rep["fails"][0]["check_name"] == "assets_eq_liabilities_and_equity"
    by_concept = {ln["concept"]: ln for ln in rep["lines"]}
    assert by_concept["Assets"]["value"] == -100.0 and by_concept["Assets"]["value_presented"] == 100.0
    assert by_concept["Assets"]["negating"] is True
    text = cr.format_explain(rep)
    assert "Assets" in text and "negating" in text


# -- reasons and the named list ---------------------------------------------------------------------

# check_name, lhs, rhs -> the reason the report should give
REASON_ROWS = [
    # Two shapes of sign gap, told apart by which side is negative. Where the company reports the
    # negative one, it has said "loss" and printed the amount positive underneath, which is the
    # filing being clear rather than wrong; where it reports the positive one, a line is inverted.
    ("eps_basic", 0.61, -0.61, "sign: a loss reported as a positive amount"),
    ("gross_profit", -100.0, 100.0, "sign: the two sides are exact negatives"),
    ("eps_basic", 12.0, 0.012, "scale: off by a factor of 1,000 or 1,000,000"),
    ("eps_basic", 4.0, 1.0, "period: off by a factor of 2 to 4"),
    ("gross_profit", 100.0, 0.0, "one side is zero"),
    ("gross_profit", 1_000_000.0, 1_007_000.0, "just over the tolerance"),
    ("gross_profit", 1_000_000.0, 1_500_000.0, "unexplained"),
    # 8 % off: 1.5x the approximate check's 5 % (just over); it would be 8x the exact check's 1 %
    ("eps_basic_approx", 1.0, 1.08, "just over the tolerance"),
]


def _seed_reasons(st: Storage) -> None:
    rows = [
        {
            "accession": f"r{i}",
            "cik": 9,
            "statement": "IS",
            "check_name": name,
            "passed": False,
            "lhs": lhs,
            "rhs": rhs,
            "difference": lhs - rhs,
            "detail": "",
            "source": "fsds",
        }
        for i, (name, lhs, rhs, _) in enumerate(REASON_ROWS)
    ]
    st.write_parquet(
        f"{layout.statement_checks_cik_dir(9)}/c.parquet", pa.Table.from_pylist(rows, schema=CHECKS_SCHEMA)
    )
    st.write_parquet(layout.COMPANIES, pa.table({"cik": [9], "name": ["Reason Co"]}))


def test_every_failure_gets_a_reason(tmp_path):
    st = Storage(str(tmp_path))
    _seed_reasons(st)
    rep = cr.failure_report(st)
    got = {(r["check_name"], r["reason"]): r["n"] for r in rep["reasons"]}
    for name, _, _, reason in REASON_ROWS:
        assert got.get((name, reason), 0) >= 1, (name, reason, got)
    assert set(r["reason"] for r in rep["reasons"]) <= set(cr.REASONS)
    assert all(w["reason"] in cr.REASONS for w in rep["worst"])
    text = cr.format_failure_report(rep)
    assert "why:" in text and "sign: the two sides are exact negatives" in text


def test_export_writes_the_named_list(tmp_path):
    import csv

    st = Storage(str(tmp_path))
    _seed_reasons(st)
    out = tmp_path / "failures.csv"
    assert cr.export_failures(st, str(out)) == len(REASON_ROWS)
    rows = list(csv.DictReader(out.open()))
    assert len(rows) == len(REASON_ROWS)
    assert {r["name"] for r in rows} == {"Reason Co"}
    assert {r["reason"] for r in rows} == {reason for _, _, _, reason in REASON_ROWS}
    assert set(rows[0]) >= {"cik", "name", "accession", "check_name", "reason", "lhs", "rhs", "tolerance_multiple"}
    assert cr.export_failures(Storage(str(tmp_path / "empty")), str(tmp_path / "e.csv")) == 0


def test_the_approximate_eps_check_is_labelled_and_tolerated_at_five_percent(tmp_path):
    st = Storage(str(tmp_path))
    _seed_reasons(st)
    rep = cr.failure_report(st)
    assert "approximate" in cr.CHECK_LABELS["eps_basic_approx"]
    approx = {(r["check_name"], r["reason"]): r["n"] for r in rep["reasons"]}
    assert approx[("eps_basic_approx", "just over the tolerance")] == 1
    text = cr.format_failure_report(rep)
    assert "approximate (inferred numerator, 5 %)" in text  # fits the 52-character label column


def test_dig_shows_the_lines_used_the_reasons_and_a_sample_with_the_numbers(tmp_path):
    st = Storage(str(tmp_path))
    rows = [
        {
            "accession": f"d{i}",
            "cik": 5,
            "statement": "IS",
            "check_name": "income_after_tax",
            "passed": passed,
            "lhs": lhs,
            "rhs": rhs,
            "difference": lhs - rhs,
            "source": "fsds",
            "detail": f"Pretax - Tax = {line}",
        }
        for i, (lhs, rhs, passed, line) in enumerate(
            [
                (80.0, 80.0, True, "ProfitLoss"),
                (80.0, 70.0, False, "IncomeLossFromContinuingOperations"),
                (80.0, 60.0, False, "IncomeLossFromContinuingOperations"),
                (80.0, 80.0, True, "IncomeLossFromContinuingOperations"),
            ]
        )
    ]
    st.write_parquet(
        f"{layout.statement_checks_cik_dir(5)}/c.parquet", pa.Table.from_pylist(rows, schema=CHECKS_SCHEMA)
    )
    st.write_parquet(layout.COMPANIES, pa.table({"cik": [5], "name": ["Dig Co"]}))
    st.write_parquet(
        f"{layout.statements_cik_dir(5)}/s.parquet",
        pa.table(
            {
                "cik": [5, 5],
                "accession": ["d1", "d1"],
                "form": ["10-K", "10-K"],
                "statement": ["IS", "IS"],
                "concept": ["ProfitLoss", "NetIncomeLossAttributableToNoncontrollingInterest"],
                "value": [80.0, 10.0],
                "is_primary_period": [True, True],
                "is_parenthetical": [False, False],
                "segments": ["", ""],
            }
        ),
    )
    rep = cr.dig(st, "income_after_tax", examples=5)
    by = {r["line"]: r for r in rep["by_rhs"]}
    assert (
        by["IncomeLossFromContinuingOperations"]["ran"] == 3 and by["IncomeLossFromContinuingOperations"]["failed"] == 2
    )
    assert by["ProfitLoss"]["failed"] == 0
    assert rep["by_lhs"][0]["line"] == "Pretax - Tax"
    assert {r["reason"] for r in rep["reasons"]} <= set(cr.REASONS)
    sample = {s["accession"]: s for s in rep["sample"]}
    assert set(sample) == {"d1", "d2"} and sample["d1"]["name"] == "Dig Co" and sample["d1"]["form"] == "10-K"
    assert "IS:ProfitLoss=80" in sample["d1"]["values"]
    # d1 is short by 10 and carries a minority-interest line worth exactly 10: the gap has a name.
    gaps = {g["concept"]: g for g in rep["gap_concepts"]}
    assert gaps["NetIncomeLossAttributableToNoncontrollingInterest"]["is_gap"] == 1
    assert gaps["NetIncomeLossAttributableToNoncontrollingInterest"]["failures"] == 2
    text = cr.format_dig(rep)
    assert "IncomeLossFromContinuingOperations" in text and "Dig Co" in text and "ProfitLoss=80" in text
    assert "What the gap is worth" in text and "NetIncomeLossAttributableToNoncontrollingInterest" in text
    assert cr.format_dig(cr.dig(Storage(str(tmp_path / "empty")), "x")) == "no statement_checks in the lake"


def test_export_xlsx_is_readable_by_a_reviewer(tmp_path):
    """The spreadsheet a reviewer opens: a summary, every failure with the company named, and ids
    written as text so a spreadsheet does not turn a CIK into scientific notation."""
    from openpyxl import load_workbook

    st = Storage(str(tmp_path))
    _seed_reasons(st)
    out = tmp_path / "failures.xlsx"
    assert cr.export_failures_xlsx(st, str(out)) == len(REASON_ROWS)

    wb = load_workbook(out)
    assert wb.sheetnames == ["Summary", "Failures"]
    summary = "\n".join(str(c.value) for row in wb["Summary"].iter_rows() for c in row if c.value)
    n = len(REASON_ROWS)
    assert f"{n} of {n} checks fail" in summary and "By check" in summary and "By reason" in summary
    assert "never silently corrected" in summary  # the posture is stated where a reviewer reads it

    ws = wb["Failures"]
    assert [c.value for c in ws[1]][:6] == ["Company", "CIK", "Filing", "Statement", "Check", "Why"]
    assert ws.freeze_panes == "A2" and ws.auto_filter.ref
    body = list(ws.iter_rows(min_row=2, values_only=True))
    assert len(body) == len(REASON_ROWS)
    assert {r[0] for r in body} == {"Reason Co"}
    assert {r[1] for r in body} == {"9"} and all(isinstance(r[1], str) for r in body)  # CIK as text
    assert {r[5] for r in body} == {reason for _, _, _, reason in REASON_ROWS}
    assert any("Gross profit" in str(r[4]) for r in body)  # the plain-language name, not gross_profit
    assert cr.export_failures_xlsx(Storage(str(tmp_path / "empty")), str(tmp_path / "e.xlsx")) == 0


def test_two_currency_filings_names_the_filers_that_print_both(tmp_path):
    """A convenience translation is one concept, one date, one filing, carrying two currencies."""
    st = Storage(str(tmp_path))
    rows = [
        # A Chinese filer printing renminbi and a dollar translation of the same two lines.
        ("Revenues", "CNY", 700_000_000.0),
        ("Revenues", "USD", 100_000_000.0),
        ("NetIncomeLoss", "CNY", 70_000_000.0),
        ("NetIncomeLoss", "USD", 10_000_000.0),
    ]
    st.write_parquet(
        f"{layout.facts_cik_dir(7)}/f.parquet",
        pa.table(
            {
                "cik": [7] * len(rows),
                "accession": ["a1"] * len(rows),
                "concept": [c for c, _, _ in rows],
                "unit": [u for _, u, _ in rows],
                "period_end": [date(2025, 12, 31)] * len(rows),
                "value": [v for _, _, v in rows],
            }
        ),
    )
    # A dollar-only filer, which must not appear.
    st.write_parquet(
        f"{layout.facts_cik_dir(8)}/f.parquet",
        pa.table(
            {
                "cik": [8],
                "accession": ["b1"],
                "concept": ["Revenues"],
                "unit": ["USD"],
                "period_end": [date(2025, 12, 31)],
                "value": [5.0],
            }
        ),
    )
    st.write_parquet(layout.COMPANIES, pa.table({"cik": [7, 8], "name": ["Yangtze Co", "Domestic Inc"]}))

    rows_out = cr.two_currency_filings(st)
    assert [r["cik"] for r in rows_out] == [7]
    only = rows_out[0]
    assert only["name"] == "Yangtze Co" and only["filings"] == 1
    assert only["currencies"] == "CNY, USD"
    assert only["implied_rate"] == 7.0  # both lines imply the same rate, which is the giveaway
    text = cr.format_two_currency_filings(rows_out)
    assert "Yangtze Co" in text and "Domestic Inc" not in text
    assert cr.format_two_currency_filings([]).startswith("No filing")
