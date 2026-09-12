from datetime import date

import pyarrow as pa

from filings_hub.ingest import checks as C
from filings_hub.ingest import sync_statements as S
from filings_hub.ingest.fsds import load_all_fsds, loaded_quarters
from filings_hub.lake import layout
from filings_hub.lake.duck import Duck
from filings_hub.lake.storage import Storage
from filings_hub.testing import edgar_fixtures as fx


def _rows(storage: Storage, sql: str, params=None):
    duck = Duck(storage)
    try:
        duck.create_views()
        return duck.fetch_dicts(sql, params or [])
    finally:
        duck.close()


def test_fsds_tables_loaded_typed(built_lake: Storage):
    assert loaded_quarters(built_lake) == ["2025q4", "2026q1"]
    sub = _rows(
        built_lake,
        "SELECT adsh, cik, period, fy, fp, filed FROM fsds_sub WHERE quarter = '2025q4' ORDER BY adsh",
    )
    apple = next(r for r in sub if r["cik"] == fx.APPLE)
    assert (
        apple["period"] == date(2025, 9, 30)
        and apple["fy"] == 2025
        and apple["fp"] == "FY"
        and apple["filed"] == date(2025, 10, 31)
    )
    num = _rows(built_lake, "SELECT count(*) AS n FROM fsds_num WHERE coreg IS NOT NULL")
    assert num[0]["n"] == 2  # the co-registrant rows are kept in the lake but excluded from statements


def test_apple_fy2025_income_statement_line_order(built_lake: Storage):
    rows = _rows(
        built_lake,
        "SELECT line_order, concept, label, is_abstract, is_subtotal, parent_concept, value, value_presented, period_start, period_end, unit "
        "FROM statements WHERE accession = ? AND statement = 'IS' AND is_primary_period ORDER BY line_order",
        [fx.APPLE_10K_FY2025],
    )
    expected = [t for t in fx.APPLE_PRE if t[0] == "IS"]
    assert [r["concept"] for r in rows] == [t[3] for t in expected]
    assert [r["label"] for r in rows] == [t[4] for t in expected]  # the company's own labels
    assert [r["line_order"] for r in rows] == list(range(1, len(expected) + 1))
    by = {r["concept"]: r for r in rows}
    assert by["IncomeStatementAbstract"]["is_abstract"] and by["IncomeStatementAbstract"]["value"] is None
    assert by["GrossProfit"]["is_subtotal"] and not by["ResearchAndDevelopmentExpense"]["is_subtotal"]
    assert by["ResearchAndDevelopmentExpense"]["parent_concept"] == "OperatingExpenses"
    assert by["NetIncomeLoss"]["parent_concept"] is None
    assert by["RevenueFromContractWithCustomerExcludingAssessedTax"]["value"] == 416_161_000_000
    # exact 52/53-week dates come from the facts join, not the month-end-rounded FSDS date
    assert by["NetIncomeLoss"]["period_start"] == date(2024, 9, 29) and by["NetIncomeLoss"]["period_end"] == date(
        2025, 9, 27
    )
    assert by["EarningsPerShareDiluted"]["unit"] == "USD/shares" and by["EarningsPerShareDiluted"]["value"] == 7.46


def test_negating_labels_flip_presented_sign(built_lake: Storage):
    rows = _rows(
        built_lake,
        "SELECT concept, value, value_presented FROM statements WHERE accession = ? AND statement = 'CF' AND is_primary_period AND concept = 'PaymentsForRepurchaseOfCommonStock'",
        [fx.APPLE_10K_FY2025],
    )
    assert rows == [
        {
            "concept": "PaymentsForRepurchaseOfCommonStock",
            "value": 95_000_000_000.0,
            "value_presented": -95_000_000_000.0,
        }
    ]


def test_comparative_columns_kept_but_not_primary(built_lake: Storage):
    rows = _rows(
        built_lake,
        "SELECT period_end, qtrs, is_primary_period, value FROM statements WHERE accession = ? AND concept = 'NetIncomeLoss' AND statement = 'IS' ORDER BY period_end",
        [fx.APPLE_10K_FY2025],
    )
    assert [(r["period_end"].isoformat(), r["is_primary_period"]) for r in rows] == [
        ("2024-09-28", False),
        ("2025-09-27", True),
    ]
    assert rows[0]["value"] == 93_737_000_000  # the restated comparative, as presented in the FY2025 10-K


def test_bank_has_no_gross_profit_and_checks_pass(built_lake: Storage):
    rows = _rows(
        built_lake,
        "SELECT concept, checks_passed FROM statements WHERE accession = ? AND statement = 'IS' AND is_primary_period ORDER BY line_order",
        [fx.JPM_10K_FY2025],
    )
    concepts = [r["concept"] for r in rows]
    assert "GrossProfit" not in concepts and "InterestIncomeExpenseNet" in concepts
    assert all(r["checks_passed"] for r in rows)
    checks = _rows(
        built_lake,
        "SELECT statement, check_name, passed FROM statement_checks WHERE accession = ? ORDER BY statement",
        [fx.JPM_10K_FY2025],
    )
    assert checks == [
        {"statement": "BS", "check_name": "assets_eq_liabilities_and_equity", "passed": True},
        {"statement": "IS", "check_name": "income_after_tax", "passed": True},
    ]


def test_broken_balance_sheet_fails_check(built_lake: Storage):
    rows = _rows(
        built_lake,
        "SELECT DISTINCT statement, checks_passed FROM statements WHERE accession = ? ORDER BY statement",
        [fx.BROKEN_10K],
    )
    assert rows == [
        {"statement": "BS", "checks_passed": False},
        {"statement": "IS", "checks_passed": True},
    ]
    chk = _rows(
        built_lake,
        "SELECT passed, lhs, rhs, difference FROM statement_checks WHERE accession = ? AND statement = 'BS'",
        [fx.BROKEN_10K],
    )
    assert chk == [{"passed": False, "lhs": 100_000_000.0, "rhs": 90_000_000.0, "difference": 10_000_000.0}]


def test_ifrs_40f_filer_statements(built_lake: Storage):
    rows = _rows(
        built_lake,
        "SELECT statement, concept, taxonomy, checks_passed FROM statements WHERE accession = ? AND is_primary_period ORDER BY statement, line_order",
        [fx.RBC_40F_FY2025],
    )
    assert [r["concept"] for r in rows] == [
        "Assets",
        "Liabilities",
        "Equity",
        "EquityAndLiabilities",
        "Revenue",
        "ProfitLoss",
    ]
    assert all(r["taxonomy"] == "ifrs-full/2025" for r in rows)
    assert all(r["checks_passed"] for r in rows if r["statement"] == "BS")


def test_fallback_uses_company_template(built_lake: Storage):
    fsds_lines = _rows(
        built_lake,
        "SELECT statement, line_order, concept, label FROM statements WHERE accession = ? AND is_primary_period AND statement IN ('IS','BS','CF') ORDER BY statement, line_order",
        [fx.APPLE_10Q_Q1_2026],
    )
    fb_lines = _rows(
        built_lake,
        "SELECT statement, line_order, concept, label, source FROM statements WHERE accession = ? AND is_primary_period AND statement IN ('IS','BS','CF') ORDER BY statement, line_order",
        [fx.APPLE_10Q_Q2_2026],
    )
    assert all(r["source"] == "facts_fallback" for r in fb_lines)
    assert [(r["statement"], r["concept"], r["label"]) for r in fb_lines] == [
        (r["statement"], r["concept"], r["label"]) for r in fsds_lines
    ]
    prim = _rows(
        built_lake,
        "SELECT statement, qtrs, period_start, period_end FROM statements WHERE accession = ? AND is_primary_period AND concept IN ('NetIncomeLoss','NetCashProvidedByUsedInOperatingActivities') ORDER BY statement",
        [fx.APPLE_10Q_Q2_2026],
    )
    # IS primary column is the quarter, CF primary column is the year-to-date (the only one reported)
    assert [(r["statement"], r["qtrs"], r["period_start"].isoformat()) for r in prim] == [
        ("CF", 2, "2025-09-28"),
        ("IS", 1, "2025-12-28"),
    ]


def test_fallback_without_template_uses_taxonomy_hints():
    facts = [
        {
            "taxonomy": "us-gaap",
            "concept": "NetIncomeLoss",
            "unit": "USD",
            "period_start": date(2025, 1, 1),
            "period_end": date(2025, 12, 31),
            "value": 5.0,
            "duration_days": 364,
            "label": "Net income",
        },
        {
            "taxonomy": "us-gaap",
            "concept": "Revenues",
            "unit": "USD",
            "period_start": date(2025, 1, 1),
            "period_end": date(2025, 12, 31),
            "value": 50.0,
            "duration_days": 364,
            "label": "Revenues",
        },
        {
            "taxonomy": "us-gaap",
            "concept": "Assets",
            "unit": "USD",
            "period_start": None,
            "period_end": date(2025, 12, 31),
            "value": 100.0,
            "duration_days": None,
            "label": "Assets",
        },
        {
            "taxonomy": "us-gaap",
            "concept": "LiabilitiesAndStockholdersEquity",
            "unit": "USD",
            "period_start": None,
            "period_end": date(2025, 12, 31),
            "value": 100.0,
            "duration_days": None,
            "label": "L&SE",
        },
        {
            "taxonomy": "us-gaap",
            "concept": "PaymentsToAcquirePropertyPlantAndEquipment",
            "unit": "USD",
            "period_start": date(2025, 1, 1),
            "period_end": date(2025, 12, 31),
            "value": 7.0,
            "duration_days": 364,
            "label": "Capex",
        },
        {
            "taxonomy": "us-gaap",
            "concept": "OtherComprehensiveIncomeLossNetOfTax",
            "unit": "USD",
            "period_start": date(2025, 1, 1),
            "period_end": date(2025, 12, 31),
            "value": 1.0,
            "duration_days": 364,
            "label": "OCI",
        },
        {
            "taxonomy": "us-gaap",
            "concept": "StockIssuedDuringPeriodValueNewIssues",
            "unit": "USD",
            "period_start": date(2025, 1, 1),
            "period_end": date(2025, 12, 31),
            "value": 2.0,
            "duration_days": 364,
            "label": "Issued",
        },
        {
            "taxonomy": "us-gaap",
            "concept": "MysteryCustomConcept",
            "unit": "USD",
            "period_start": date(2025, 1, 1),
            "period_end": date(2025, 12, 31),
            "value": 3.0,
            "duration_days": 364,
            "label": "Mystery",
        },
        {
            "taxonomy": "us-gaap",
            "concept": "Revenues",
            "unit": "USD",
            "period_start": date(2025, 10, 1),
            "period_end": date(2025, 12, 31),
            "value": 12.0,
            "duration_days": 91,
            "label": "Revenues",
        },  # Q4 in a 10-K note: filtered
        {
            "taxonomy": "dei",
            "concept": "EntityCommonStockSharesOutstanding",
            "unit": "shares",
            "period_start": None,
            "period_end": date(2026, 1, 31),
            "value": 9.0,
            "duration_days": None,
            "label": "shares",
        },
    ]
    rows, checks = S.build_fallback_rows(1, "acc", "10-K", date(2026, 2, 1), date(2025, 12, 31), 4, facts, None)
    by_stmt = {}
    for r in rows:
        by_stmt.setdefault(r["statement"], []).append(r["concept"])
    assert by_stmt["IS"] == ["Revenues", "NetIncomeLoss", "MysteryCustomConcept"]
    assert by_stmt["BS"] == ["Assets", "LiabilitiesAndStockholdersEquity"]
    assert by_stmt["CF"] == ["PaymentsToAcquirePropertyPlantAndEquipment"]
    assert by_stmt["CI"] == ["OtherComprehensiveIncomeLossNetOfTax"] and by_stmt["EQ"] == [
        "StockIssuedDuringPeriodValueNewIssues"
    ]
    assert all(r["is_primary_period"] for r in rows)
    assert {(c["statement"], c["check_name"], c["passed"]) for c in checks} == {
        ("BS", "assets_eq_liabilities_and_equity", True)
    }
    bs_rows = [r for r in rows if r["statement"] == "BS"]
    assert all(r["checks_passed"] for r in bs_rows) and all(
        r["checks_passed"] is None for r in rows if r["statement"] == "IS"
    )
    assert pa.Table.from_pylist(rows, schema=S.STATEMENTS_SCHEMA).num_rows == len(rows)


def test_fallback_template_drops_empty_lines_and_headers():
    template = [
        {
            "statement": "IS",
            "is_parenthetical": False,
            "line_order": 1,
            "concept": "IncomeStatementAbstract",
            "label": "IS",
            "negating": False,
            "is_abstract": True,
            "standard_label": None,
            "taxonomy": "us-gaap/2025",
        },
        {
            "statement": "IS",
            "is_parenthetical": False,
            "line_order": 2,
            "concept": "Revenues",
            "label": "Sales",
            "negating": False,
            "is_abstract": False,
            "standard_label": None,
            "taxonomy": "us-gaap/2025",
        },
        {
            "statement": "IS",
            "is_parenthetical": False,
            "line_order": 3,
            "concept": "GoneConcept",
            "label": "Gone",
            "negating": False,
            "is_abstract": False,
            "standard_label": None,
            "taxonomy": "us-gaap/2025",
        },
        {
            "statement": "IS",
            "is_parenthetical": False,
            "line_order": 4,
            "concept": "EmptyHeaderAbstract",
            "label": "Empty",
            "negating": False,
            "is_abstract": True,
            "standard_label": None,
            "taxonomy": "us-gaap/2025",
        },
    ]
    facts = [
        {
            "taxonomy": "us-gaap",
            "concept": "Revenues",
            "unit": "USD",
            "period_start": date(2025, 10, 1),
            "period_end": date(2025, 12, 31),
            "value": 1.0,
            "duration_days": 91,
            "label": "Revenues",
        }
    ]
    rows, _ = S.build_fallback_rows(1, "acc", "10-Q", date(2026, 2, 1), date(2025, 12, 31), 1, facts, template)
    assert [(r["concept"], r["line_order"], r["label"]) for r in rows] == [
        ("IncomeStatementAbstract", 1, "IS"),
        ("Revenues", 2, "Sales"),
    ]


def test_helpers():
    assert S.month_end_round(date(2025, 9, 27)) == date(2025, 9, 30)
    assert S.month_end_round(date(2025, 10, 3)) == date(2025, 9, 30)
    assert S.month_end_round(date(2026, 1, 2)) == date(2025, 12, 31)
    assert S.month_end_round(None) is None
    assert S.expected_qtrs(2, "10-Q") == {1, 2} and S.expected_qtrs(4, "10-K") == {4}
    assert S.expected_qtrs(4, "10-KT") is None and S.expected_qtrs(None, "10-Q") is None
    assert S._qtrs_est(None) == 0 and S._qtrs_est(91) == 1 and S._qtrs_est(182) == 2 and S._qtrs_est(365) == 4
    # instants belong on every statement (opening and closing balances are points in time); only the
    # balance sheet refuses durations, and a duration must match the filing's own fiscal period
    assert S._keep_period("BS", 0, {4}) and not S._keep_period("BS", 4, {4})
    assert S._keep_period("IS", 4, {4}) and not S._keep_period("IS", 1, {4}) and S._keep_period("IS", 1, None)
    assert S._keep_period("CF", 0, {4}) and S._keep_period("EQ", 0, {4}) and S._keep_period("CP", 0, {4})
    assert not S._keep_period("CP", 7, {4}) and S._keep_period("CP", 7, None)


def test_sql_and_python_subtotal_rules_agree(built_lake: Storage):
    rows = _rows(
        built_lake,
        "SELECT DISTINCT concept, label, is_abstract, is_subtotal FROM statements WHERE source = 'fsds'",
    )
    for r in rows:
        assert r["is_subtotal"] == C.is_subtotal(r["concept"], r["label"], r["is_abstract"]), r


def test_fsds_rebuild_supersedes_fallback(lake_copy: Storage):
    """Publishing FSDS 2026q2 (Apple's Q2 10-Q) must replace the provisional statements."""
    q2 = {
        "sub": [
            fx._sub(
                fx.APPLE_10Q_Q2_2026,
                fx.APPLE,
                "10-Q",
                "2026-03-31",
                2026,
                "Q2",
                "2026-05-01",
                "0930",
            )
        ],
        "num": fx._apple_num(
            fx.APPLE_10Q_Q2_2026,
            [fx.P_Q2_2026, fx.P_H1_2026],
            ["2026-03-28", "2025-09-27"],
            [fx.P_H1_2026],
        ),
        "pre": fx._apple_pre(fx.APPLE_10Q_Q2_2026),
        "tag": fx._tags_for(fx.APPLE_PRE),
    }
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        cols = {"sub": fx.SUB_COLS, "num": fx.NUM_COLS, "pre": fx.PRE_COLS, "tag": fx.TAG_COLS}
        for t, lines in q2.items():
            zf.writestr(f"{t}.txt", "\t".join(cols[t]) + "\n" + "\n".join(lines) + "\n")
    lake_copy.write_bytes(layout.raw_fsds_zip("2026q2"), buf.getvalue())
    assert lake_copy.exists(f"{layout.statements_cik_dir(fx.APPLE)}/fallback_{fx.APPLE_10Q_Q2_2026}.parquet")
    assert load_all_fsds(lake_copy) == ["2026q2"]
    assert S.build_all_fsds(lake_copy) == ["2026q2"]
    assert not lake_copy.exists(f"{layout.statements_cik_dir(fx.APPLE)}/fallback_{fx.APPLE_10Q_Q2_2026}.parquet")
    rows = _rows(
        lake_copy,
        "SELECT DISTINCT source, fsds_quarter FROM statements WHERE accession = ?",
        [fx.APPLE_10Q_Q2_2026],
    )
    assert rows == [{"source": "fsds", "fsds_quarter": "2026q2"}]
    # idempotent: building the same quarter again does not duplicate rows
    n1 = _rows(lake_copy, "SELECT count(*) AS n FROM statements WHERE fsds_quarter = '2026q2'")[0]["n"]
    S.build_all_fsds(lake_copy, ["2026q2"], force=True)
    n2 = _rows(lake_copy, "SELECT count(*) AS n FROM statements WHERE fsds_quarter = '2026q2'")[0]["n"]
    assert n1 == n2 > 0
    # nothing left to fall back on for Apple
    assert S.fill_fallbacks_for_cik(lake_copy, fx.APPLE) == 0
    assert S.fill_all_fallbacks(lake_copy, [fx.OLD]) == 0  # no XBRL facts -> nothing built


def test_build_without_facts_enrichment(lake_copy: Storage):
    lake_copy.delete(layout.FACTS)
    S.build_fsds_quarter(lake_copy, "2026q1", enrich=True)  # facts missing -> estimated period_start
    rows = _rows(
        lake_copy,
        "SELECT period_start, period_end FROM statements WHERE accession = ? AND concept = 'NetIncomeLoss' AND is_primary_period",
        [fx.APPLE_10Q_Q1_2026],
    )
    assert rows == [{"period_start": date(2025, 10, 1), "period_end": date(2025, 12, 31)}]


def test_missing_fsds_table_raises(tmp_path):
    import pytest

    with pytest.raises(RuntimeError):
        S.build_fsds_quarter(Storage(str(tmp_path)), "2026q1")


def test_rebuild_periods_subset_keeps_other_companies(lake_copy: Storage):
    from filings_hub.ingest.sync_periods import rebuild_periods

    before = lake_copy.read_parquet(layout.PERIODS).num_rows
    assert rebuild_periods(lake_copy, [fx.APPLE]) == before
    rows = lake_copy.read_parquet(layout.PERIODS).to_pylist()
    assert {r["cik"] for r in rows} > {fx.APPLE, fx.JPM}
    lake_copy.delete(layout.FILINGS)
    assert rebuild_periods(lake_copy) == 0


def test_instants_presented_on_the_cash_flow_statement_survive(built_lake: Storage):
    """Opening and closing cash are instants (tag.iord = 'I', num.qtrs = 0) presented on a duration
    statement. Choosing values by statement rather than by concept dropped them, leaving the cash
    reconciliation blank; and the same concept on two lines made both show the closing balance."""
    for accession, key, source in (
        (fx.APPLE_10K_FY2025, fx.P_FY2025, "fsds"),
        (fx.APPLE_10Q_Q2_2026, fx.P_H1_2026, "facts_fallback"),
    ):
        rows = _rows(
            built_lake,
            "SELECT line_order, label, qtrs, value, source FROM statements WHERE accession = ? "
            "AND statement = 'CF' AND is_primary_period ORDER BY line_order",
            [accession],
        )
        assert {r["source"] for r in rows} == {source}
        by_label = {r["label"]: r for r in rows}
        opening = next(r for lbl, r in by_label.items() if "beginning" in lbl)
        closing = next(r for lbl, r in by_label.items() if "ending" in lbl)
        expected_open, expected_close = fx.APPLE_CASH[key]
        assert (opening["value"], opening["qtrs"]) == (float(expected_open), 0), accession
        assert (closing["value"], closing["qtrs"]) == (float(expected_close), 0), accession
        assert opening["line_order"] < closing["line_order"]
        # the statement reconciles: opening + change = closing
        change = next(r["value"] for lbl, r in by_label.items() if lbl.startswith("Increase/(Decrease)"))
        assert opening["value"] + change == closing["value"], accession
        # and the activity lines are still there, one column each
        assert len([r for r in rows if r["qtrs"] and r["qtrs"] > 0]) == 7


def test_one_primary_row_per_line(built_lake: Storage):
    """A line must contribute exactly one value to the filing's own column: an instant alongside a
    duration on the same line (an equity balance and the year's movement) produced two."""
    dupes = _rows(
        built_lake,
        "SELECT accession, statement, line_order, count(*) AS n FROM statements "
        "WHERE is_primary_period AND NOT is_abstract GROUP BY ALL HAVING n > 1",
    )
    assert dupes == []


def test_balance_sheet_comparative_column_is_not_primary(built_lake: Storage):
    """Both the current and prior period end are instants; only the filing's own date is its column."""
    rows = _rows(
        built_lake,
        "SELECT period_end, is_primary_period, value FROM statements WHERE accession = ? "
        "AND concept = 'Assets' AND statement = 'BS' ORDER BY period_end",
        [fx.APPLE_10Q_Q2_2026],
    )
    assert [(r["period_end"].isoformat(), r["is_primary_period"]) for r in rows] == [
        ("2025-09-27", False),
        ("2026-03-28", True),
    ]
