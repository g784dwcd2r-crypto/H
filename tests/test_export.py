import io

import pytest
from openpyxl import load_workbook

from filings_hub.db.database import Database
from filings_hub.export.excel import export_excel, workbook_from_grid
from filings_hub.export.grid import Grid, build_grid, merge_line_order
from filings_hub.testing import edgar_fixtures as fx


def test_merge_line_order():
    assert merge_line_order([["a", "b", "c"], ["a", "x", "c"]]) == ["a", "x", "b", "c"]
    assert merge_line_order([["a", "b"], ["z", "a"]]) == ["z", "a", "b"]
    assert merge_line_order([[], ["q"]]) == ["q"]
    assert merge_line_order([["a", "b"], ["b", "a"]]) == ["a", "b"]  # newest order wins


def test_grid_apple(db: Database):
    g = build_grid(db, fx.APPLE, ["FY2025", "Q1 2026", "Q2 2026"])
    assert [p.period_label for p in g.periods] == ["FY2025", "Q1 2026", "Q2 2026"]
    assert g.periods[2].is_provisional and not g.periods[1].is_provisional
    codes = {s.code: s for s in g.statements}
    assert set(codes) == {"IS", "BS", "CF"}
    rev = next(ln for ln in codes["IS"].lines if ln.concept == "RevenueFromContractWithCustomerExcludingAssessedTax")
    assert rev.values == {
        "FY2025": 416_161_000_000.0,
        "Q1 2026": 140_000_000_000.0,
        "Q2 2026": 100_000_000_000.0,
    }
    assert rev.label == "Total net sales" and rev.is_subtotal
    d = g.to_dict()
    assert (
        d["periods"][0]["accession"] == fx.APPLE_10K_FY2025
        and d["statements"][0]["lines"][1]["values"]["FY2025"] == 416_161_000_000.0
    )


def test_grid_default_limit_and_unknown(db: Database):
    g = build_grid(db, fx.APPLE, None, limit=3)
    assert len(g.periods) == 3 and g.periods[-1].period_label == "Q3 2026"
    with pytest.raises(KeyError):
        build_grid(db, 999999)


def test_excel_roundtrip_matches_statements(db: Database):
    data = export_excel(db, fx.APPLE, ["FY2024", "FY2025", "Q1 2026"])
    wb = load_workbook(io.BytesIO(data))
    assert wb.sheetnames == ["Income Statement", "Balance Sheet", "Cash Flow", "Source"]
    ws = wb["Income Statement"]
    assert ws["A1"].value == "Apple Inc. (AAPL)"
    assert ws.column_dimensions["B"].hidden
    header = [c.value for c in ws[4]]
    assert header[:3] == ["Line item", "Concept", "Unit"] and header[3:] == [
        "FY2024 (provisional)",
        "FY2025",
        "Q1 2026",
    ]
    rows = {r[1].value: r for r in ws.iter_rows(min_row=7) if r[1].value}
    ni = rows["NetIncomeLoss"]
    assert [c.value for c in ni[3:]] == [93_736_000_000, 112_861_000_000, 41_000_000_000]
    assert all(isinstance(c.value, int | float) for c in ni[3:])  # numbers, not text
    assert ni[3].number_format.startswith("#,##0")
    eps = rows["EarningsPerShareDiluted"]
    assert eps[2].value == "USD/shares" and eps[4].value == 7.46 and eps[4].number_format.startswith("0.00")
    cf = wb["Cash Flow"]
    cf_rows = {r[1].value: r for r in cf.iter_rows(min_row=7) if r[1].value}
    assert cf_rows["PaymentsForRepurchaseOfCommonStock"][4].value == -95_000_000_000  # negatives as negatives
    # column totals: net income equals what the statements table holds for each filing
    for j, acc in enumerate([fx.APPLE_10K_FY2024, fx.APPLE_10K_FY2025, fx.APPLE_10Q_Q1_2026]):
        v = db.query(
            "SELECT value_presented FROM statements WHERE accession = ? AND statement = 'IS' AND concept = 'NetIncomeLoss' AND is_primary_period",
            [acc],
        )
        assert ni[3 + j].value == v[0]["value_presented"]
    src = wb["Source"]
    assert src["A2"].value == "FY2024" and src["D3"].value == fx.APPLE_10K_FY2025
    assert src["F3"].hyperlink.target.endswith("-index.htm")
    assert src["I2"].value.startswith("provisional") and src["J3"].value == "passed"
    # no formulas anywhere
    for sheet in wb.worksheets:
        for row in sheet.iter_rows():
            for c in row:
                assert not (isinstance(c.value, str) and c.value.startswith("="))


def test_workbook_with_no_statements():
    g = Grid(cik=1, company_name="Empty Co", ticker=None, periods=[], statements=[])
    wb = workbook_from_grid(g)
    assert wb.sheetnames == ["No statements", "Source"]


def test_repeated_concepts_key_on_their_label(db: Database):
    """A concept presented twice -- "beginning balances" and "ending balances" carry the same concept --
    must key on what distinguishes the lines. Keying by position alone meant that when one filing
    presented fewer occurrences than another, every later occurrence shifted up and the values landed on
    the wrong row."""
    from filings_hub.export.grid import _keyed_lines

    rows = [
        {"concept": "Cash", "label": "Cash, beginning balances"},
        {"concept": "Ops", "label": "Operating activities"},
        {"concept": "Cash", "label": "Cash, ending balances"},
    ]
    keys = [k for k, _ in _keyed_lines(rows)]
    assert len(set(keys)) == 3
    # dropping the opening line must not rename the closing one
    without_opening = [k for k, _ in _keyed_lines(rows[1:])]
    assert without_opening[-1] == keys[-1]
    # a genuinely identical line (same concept and label) still gets a distinct key
    twice = [k for k, _ in _keyed_lines([rows[0], rows[0]])]
    assert twice[0] != twice[1]


def test_grid_aligns_opening_and_closing_cash_across_filings(db: Database):
    """The cash flow statement's opening and closing balances share one concept: each must keep its own
    row across every period column."""
    g = build_grid(db, fx.APPLE, ["FY2025", "Q1 2026", "Q2 2026"])
    cf = next(s for s in g.statements if s.code == "CF")
    cash = [ln for ln in cf.lines if ln.concept == fx.CASH_CONCEPT]
    assert len(cash) == 2
    opening, closing = cash
    assert "beginning" in opening.label and "ending" in closing.label
    for label, key in (("FY2025", fx.P_FY2025), ("Q1 2026", fx.P_Q1_2026), ("Q2 2026", fx.P_H1_2026)):
        want_open, want_close = fx.APPLE_CASH[key]
        assert opening.values[label] == float(want_open), (label, "opening")
        assert closing.values[label] == float(want_close), (label, "closing")
    # and each column reconciles against its own change line
    change = next(ln for ln in cf.lines if ln.label.startswith("Increase/(Decrease)"))
    for label in ("FY2025", "Q1 2026", "Q2 2026"):
        assert opening.values[label] + change.values[label] == closing.values[label], label
