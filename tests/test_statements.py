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


def test_template_comes_from_the_same_kind_of_filing(lake_copy: Storage):
    """The FSDS also covers S-1, S-4 and 424B filings. Selecting the quarterly template as "anything
    that is not annual" let a prospectus become the template for every provisional 10-Q."""
    import pyarrow as pa

    from filings_hub.lake.duck import Duck

    # an S-1 filed after the last 10-Q, with its own line order and labels
    s1 = pa.Table.from_pylist(
        [
            {
                **row,
                "accession": "0000320193-26-000900",
                "form": "S-1",
                "filed_date": date(2026, 6, 15),
                "label": "Revenue, net (S-1 prospectus)",
                "concept": "RevenueFromContractWithCustomerExcludingAssessedTax",
                "line_order": 1,
                "source": "fsds",
            }
            for row in lake_copy.read_parquet(
                sorted(lake_copy.glob(f"{layout.statements_cik_dir(fx.APPLE)}/fsds_*.parquet"))[0]
            ).to_pylist()[:1]
        ],
        schema=S.STATEMENTS_SCHEMA,
    )
    lake_copy.write_parquet(f"{layout.statements_cik_dir(fx.APPLE)}/fsds_2026q2_s1.parquet", s1)

    duck = Duck(lake_copy)
    try:
        duck.create_views()
        quarterly = S._template_for(duck, fx.APPLE, "quarter")
        annual = S._template_for(duck, fx.APPLE, "annual")
    finally:
        duck.close()
    assert quarterly is not None and annual is not None
    assert all("S-1 prospectus" not in (r["label"] or "") for r in quarterly)
    assert all("S-1 prospectus" not in (r["label"] or "") for r in annual)
    # the quarterly template is the last 10-Q's structure
    assert [r["concept"] for r in quarterly if r["statement"] == "IS"] == [t[3] for t in fx.APPLE_PRE if t[0] == "IS"]


def test_fallback_template_ignores_lines_without_statement_or_position():
    """The FSDS `pre` table occasionally leaves statement or line blank; such a line has nowhere to go."""
    from datetime import date

    from filings_hub.ingest.sync_statements import build_fallback_rows

    template = [
        {
            "statement": None,
            "is_parenthetical": None,
            "line_order": None,
            "concept": "Revenues",
            "label": "x",
            "negating": False,
            "is_abstract": False,
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
    ]
    facts = [
        {
            "taxonomy": "us-gaap/2025",
            "concept": "Revenues",
            "unit": "USD",
            "value": 5.0,
            "label": "Revenues",
            "period_start": date(2026, 1, 1),
            "period_end": date(2026, 3, 31),
            "duration_days": 90,
        },
    ]
    rows, _checks = build_fallback_rows(
        1, "0000000001-26-000001", "10-Q", date(2026, 5, 1), date(2026, 3, 31), 1, facts, template
    )
    assert [r["concept"] for r in rows if r["statement"] == "IS"] == ["Revenues"]
    assert all(r["statement"] for r in rows)


def test_dimensional_num_rows_never_become_statement_lines(lake_copy: Storage):
    """A segment breakdown carries the same tag as the line total. It is loaded (nothing is dropped)
    but the statements builder takes the total only."""
    quarter = "2026q1"
    tables = {t: text.encode("utf-8") for t, text in fx.fsds_quarters()[quarter].items()}
    num = tables["num"].decode().splitlines()
    num.append(
        "0000320193-26-000007\tRevenueFromContractWithCustomerExcludingAssessedTax\tus-gaap/2025\t20251231\t1"
        "\tUSD\tStatementBusinessSegmentsAxis=AmericasSegmentMember;\t\t60000000000\t"
    )
    tables["num"] = ("\n".join(num) + "\n").encode()
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in tables.items():
            zf.writestr(f"{name}.txt", data)
    lake_copy.write_bytes(layout.raw_fsds_zip(quarter), buf.getvalue())
    load_all_fsds(lake_copy, [quarter], force=True)
    S.build_all_fsds(lake_copy, [quarter], force=True)
    rows = _rows(
        lake_copy,
        "SELECT value FROM statements WHERE accession = '0000320193-26-000007' AND statement = 'IS' "
        "AND concept = 'RevenueFromContractWithCustomerExcludingAssessedTax' AND is_primary_period",
    )
    assert [r["value"] for r in rows] == [140000000000.0]


def test_a_tag_reported_only_broken_out_still_becomes_statement_lines(lake_copy: Storage):
    """Triumph Financial's fee income is three product lines sharing one tag, with no total. Taking
    only undimensioned values made all three vanish, so the statement showed a subtotal its own lines
    did not reach. Each breakdown becomes its own line, carrying the axis=member that identifies it."""
    quarter = "2026q1"
    tables = {t: text.encode("utf-8") for t, text in fx.fsds_quarters()[quarter].items()}
    acc = "0000320193-26-000007"
    num = tables["num"].decode().splitlines()
    for member, value in (("DepositAccount", 1_212_000), ("CreditAndDebitCard", 1_960_000)):
        num.append(
            f"{acc}\tFeeIncomeOnlyBrokenOut\tus-gaap/2025\t20251231\t1\tUSD\tProductOrService={member};\t\t{value}\t"
        )
    tables["num"] = ("\n".join(num) + "\n").encode()
    pre = tables["pre"].decode().splitlines()
    pre.append(f"{acc}\t2\t99\tIS\t0\tH\tFeeIncomeOnlyBrokenOut\tus-gaap/2025\tFee income\t0")
    tables["pre"] = ("\n".join(pre) + "\n").encode()

    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in tables.items():
            zf.writestr(f"{name}.txt", data)
    lake_copy.write_bytes(layout.raw_fsds_zip(quarter), buf.getvalue())
    load_all_fsds(lake_copy, [quarter], force=True)
    S.build_all_fsds(lake_copy, [quarter], force=True)

    rows = _rows(
        lake_copy,
        "SELECT segments, value, label, line_order FROM statements "
        f"WHERE accession = '{acc}' AND concept = 'FeeIncomeOnlyBrokenOut' AND is_primary_period "
        "ORDER BY segments",
    )
    assert [r["segments"] for r in rows] == [
        "ProductOrService=CreditAndDebitCard;",
        "ProductOrService=DepositAccount;",
    ]
    assert [r["value"] for r in rows] == [1_960_000.0, 1_212_000.0]
    # the company's own presentation label is kept as it is; the member is a separate column
    assert {r["label"] for r in rows} == {"Fee income"}
    # two members presented under one tag are two ordered lines, not one
    assert len({r["line_order"] for r in rows}) == 2


def test_a_tag_reported_with_a_total_keeps_only_the_total(lake_copy: Storage):
    """Where the filing reports both, the statement line is the total. The breakdown is detail, and
    showing it as extra lines would double-count against the subtotal below."""
    quarter = "2026q1"
    tables = {t: text.encode("utf-8") for t, text in fx.fsds_quarters()[quarter].items()}
    acc = "0000320193-26-000007"
    tag = "RevenueFromContractWithCustomerExcludingAssessedTax"
    num = tables["num"].decode().splitlines()
    num.append(f"{acc}\t{tag}\tus-gaap/2025\t20251231\t1\tUSD\tProductOrService=IPhone;\t\t60000000000\t")
    tables["num"] = ("\n".join(num) + "\n").encode()

    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in tables.items():
            zf.writestr(f"{name}.txt", data)
    lake_copy.write_bytes(layout.raw_fsds_zip(quarter), buf.getvalue())
    load_all_fsds(lake_copy, [quarter], force=True)
    S.build_all_fsds(lake_copy, [quarter], force=True)

    rows = _rows(
        lake_copy,
        f"SELECT segments, value FROM statements WHERE accession = '{acc}' AND statement = 'IS' "
        f"AND concept = '{tag}' AND is_primary_period",
    )
    assert [(r["segments"], r["value"]) for r in rows] == [(None, 140000000000.0)]


def _stg(rows: list[dict]) -> pa.Table:
    cols = [
        "accession",
        "cik",
        "statement",
        "concept",
        "value",
        "value_presented",
        "period_end_rounded",
        "is_primary_period",
        "is_parenthetical",
        "segments",
    ]
    return pa.Table.from_pylist([{c: r.get(c) for c in cols} for r in rows])


def test_checks_use_the_raw_value_and_the_period_end_figure(tmp_path):
    """The checks read the value as filed, not the sign shown on the page, and for an instant reported
    at both ends of a period (cash on the cash-flow statement) they use the period-END figure.

    The presented sign was tried (2026-09-14) and reverted (2026-09-15): a cost shown as (cost) is
    still a positive cost to subtract, and one fact shown negated on one statement and plain on
    another is still one number. Every case below fails on the presented sign and passes on the raw."""
    duck = Duck(Storage(str(tmp_path)))
    try:

        def row(stmt, concept, value, presented, end):
            return {
                "accession": "a1",
                "cik": 1,
                "statement": stmt,
                "concept": concept,
                "value": value,
                "value_presented": presented,
                "period_end_rounded": end,
                "is_primary_period": True,
                "is_parenthetical": False,
                "segments": "",
            }

        y, prior = date(2025, 12, 31), date(2024, 12, 31)
        rows = [
            # gross profit: the cost is shown as (200) on the page, negated; as filed it is +200
            row("IS", "Revenues", 300.0, 300.0, y),
            row("IS", "CostOfRevenue", 200.0, -200.0, y),
            row("IS", "GrossProfit", 100.0, 100.0, y),
            # net income: one fact, shown plain on the income statement and negated on the cash flow
            row("IS", "NetIncomeLoss", 50.0, 50.0, y),
            row("CF", "NetIncomeLoss", 50.0, -50.0, y),
            # cash: the balance sheet shows the ending figure (79); the cash-flow statement shows the
            # beginning (71, prior year) and the ending (79). The check must use the ending.
            row("BS", "CashAndCashEquivalentsAtCarryingValue", 79.0, 79.0, y),
            row("CF", "CashAndCashEquivalentsAtCarryingValue", 71.0, 71.0, prior),
            row("CF", "CashAndCashEquivalentsAtCarryingValue", 79.0, 79.0, y),
        ]
        duck.register("stg", _stg(rows))
        checks = {c["check_name"]: c for c in S._checks_from_staged(duck, "fsds").to_pylist()}
        assert checks["gross_profit"]["passed"] is True  # 300 - 200 = 100 on the value as filed
        assert checks["net_income_is_equals_cf"]["passed"] is True  # 50 = 50: one fact, one number
        assert checks["ending_cash_cf_equals_bs"]["passed"] is True  # period-end cash: 79 = 79
    finally:
        duck.close()


def test_check_still_fails_a_real_imbalance(tmp_path):
    """The fix must not mask a genuine break: Assets that really do not balance still fail."""
    duck = Duck(Storage(str(tmp_path)))
    try:
        rows = [
            {
                "accession": "b1",
                "cik": 2,
                "statement": "BS",
                "concept": "Assets",
                "value": 90.0,
                "value_presented": 90.0,
                "period_end_rounded": date(2025, 12, 31),
                "is_primary_period": True,
                "is_parenthetical": False,
                "segments": "",
            },
            {
                "accession": "b1",
                "cik": 2,
                "statement": "BS",
                "concept": "LiabilitiesAndStockholdersEquity",
                "value": 100.0,
                "value_presented": 100.0,
                "period_end_rounded": date(2025, 12, 31),
                "is_primary_period": True,
                "is_parenthetical": False,
                "segments": "",
            },
        ]
        duck.register("stg", _stg(rows))
        checks = {c["check_name"]: c for c in S._checks_from_staged(duck, "fsds").to_pylist()}
        assert checks["assets_eq_liabilities_and_equity"]["passed"] is False
    finally:
        duck.close()


# -- one currency per statement --------------------------------------------------------------------

APPLE_ACC = "0000320193-26-000007"


def _translated(line: str, ccy: str, factor: float) -> str:
    """The same FSDS num row in another currency: unit swapped, value scaled, everything else equal."""
    f = line.split("\t")
    f[5] = f[5].replace("USD", ccy)
    f[8] = str(float(f[8]) * factor) if f[8] else f[8]
    return "\t".join(f)


def _build_quarter_with(
    lake_copy: Storage, quarter: str, extra_num: list[str], extra_pre: tuple[str, ...] = ()
) -> None:
    import io
    import zipfile

    tables = {t: text.encode("utf-8") for t, text in fx.fsds_quarters()[quarter].items()}
    tables["num"] = ("\n".join(tables["num"].decode().splitlines() + list(extra_num)) + "\n").encode()
    if extra_pre:
        tables["pre"] = ("\n".join(tables["pre"].decode().splitlines() + list(extra_pre)) + "\n").encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in tables.items():
            zf.writestr(f"{name}.txt", data)
    lake_copy.write_bytes(layout.raw_fsds_zip(quarter), buf.getvalue())
    load_all_fsds(lake_copy, [quarter], force=True)
    S.build_all_fsds(lake_copy, [quarter], force=True)


def _apple_usd_rows(quarter: str) -> list[str]:
    return [
        ln
        for ln in fx.fsds_quarters()[quarter]["num"].splitlines()
        if ln.startswith(APPLE_ACC + "\t") and "\tUSD" in ln
    ]


def test_a_convenience_translation_does_not_become_a_second_value(lake_copy: Storage):
    """A filer prints its statements in one currency with a dollar translation beside them: the data
    sets carry the same tag, date and line twice, in two units. The statement keeps the currency most
    of its lines use; the translation never competes for the line."""
    rev = [ln for ln in _apple_usd_rows("2026q1") if "\tRevenueFromContractWithCustomerExcludingAssessedTax\t" in ln]
    assert rev
    _build_quarter_with(lake_copy, "2026q1", [_translated(ln, "CNY", 7.0) for ln in rev])
    rows = _rows(
        lake_copy,
        f"SELECT value, unit FROM statements WHERE accession = '{APPLE_ACC}' AND statement = 'IS' "
        "AND concept = 'RevenueFromContractWithCustomerExcludingAssessedTax' AND is_primary_period",
    )
    assert [(r["value"], r["unit"]) for r in rows] == [(140000000000.0, "USD")]


def test_the_home_currency_wins_even_when_it_is_not_the_dollar(lake_copy: Storage):
    """Every line translated, plus one line reported only at home: the home currency is what most
    lines are reported in, so the whole statement is kept in it and the dollar rows go."""
    usd = _apple_usd_rows("2026q1")
    home_only = f"{APPLE_ACC}\tHomeCurrencyOnlyItem\tus-gaap/2025\t20251231\t1\tCNY\t\t\t700000\t"
    pre = f"{APPLE_ACC}\t2\t98\tIS\t0\tH\tHomeCurrencyOnlyItem\tus-gaap/2025\tHome currency only\t0"
    _build_quarter_with(lake_copy, "2026q1", [_translated(ln, "CNY", 7.0) for ln in usd] + [home_only], (pre,))
    rows = _rows(
        lake_copy,
        f"SELECT concept, value, unit FROM statements WHERE accession = '{APPLE_ACC}' AND value IS NOT NULL "
        "AND regexp_matches(unit, '^[A-Z]{3}(/shares)?$')",
    )
    assert rows and all(r["unit"].startswith("CNY") for r in rows)
    by = {
        r["concept"]: r["value"]
        for r in rows
        if r["concept"] in ("RevenueFromContractWithCustomerExcludingAssessedTax", "HomeCurrencyOnlyItem")
    }
    assert by["RevenueFromContractWithCustomerExcludingAssessedTax"] == 140000000000.0 * 7
    assert by["HomeCurrencyOnlyItem"] == 700000.0


def test_a_line_reported_only_in_the_translation_shows_nothing_not_the_wrong_currency(lake_copy: Storage):
    only_translated = f"{APPLE_ACC}\tTranslationOnlyItem\tus-gaap/2025\t20251231\t1\tCNY\t\t\t700000\t"
    pre = f"{APPLE_ACC}\t2\t98\tIS\t0\tH\tTranslationOnlyItem\tus-gaap/2025\tTranslation only\t0"
    _build_quarter_with(lake_copy, "2026q1", [only_translated], (pre,))
    rows = _rows(
        lake_copy,
        f"SELECT value, unit FROM statements WHERE accession = '{APPLE_ACC}' AND concept = 'TranslationOnlyItem'",
    )
    assert [(r["value"], r["unit"]) for r in rows] == [(None, None)]  # the line stays, empty and honest


def test_reporting_currency_rule():
    rc = S.reporting_currency
    assert rc([("Rev", "USD"), ("Cost", "USD"), ("Rev", "CNY")]) == "USD"  # more concepts
    assert rc([("Rev", "CNY"), ("Cost", "CNY"), ("Rev", "USD")]) == "CNY"  # the home currency, not the dollar
    assert rc([("Rev", "CNY"), ("Rev", "USD")]) == "USD"  # a dead heat goes to the dollar
    assert rc([("Rev", "GBP"), ("Rev", "EUR")]) == "EUR"  # then alphabetical, so it is stable
    assert rc([("Eps", "CNY/shares"), ("Cost", "CNY"), ("Rev", "USD")]) == "CNY"  # per-share follows its prefix
    assert rc([("Shares", "shares"), ("Ratio", "pure")]) is None  # nothing monetary
    assert S.in_currency("shares", "USD") and S.in_currency("USD/shares", "USD") and not S.in_currency("CNY", "USD")


def test_a_convenience_translation_changes_nothing_a_user_reads(lake_copy: Storage):
    """The page itself, not the statements table: build the company page before and after a filer
    adds a dollar-translated copy of every line, and require them to be identical — same lines, same
    values, one currency throughout. The table being right is not the same as the page being right,
    and until now only the table was tested."""
    import re

    from filings_hub.db.database import Database
    from filings_hub.export.grid import build_grid

    money = re.compile(r"^[A-Z]{3}(/shares)?$")

    def page() -> dict:
        database = Database("", lake_copy)
        try:
            return build_grid(database, fx.APPLE, ["Q1 2026"]).to_dict()
        finally:
            database.close()

    _build_quarter_with(lake_copy, "2026q1", [])
    before = page()
    _build_quarter_with(lake_copy, "2026q1", [_translated(ln, "CNY", 7.0) for ln in _apple_usd_rows("2026q1")])
    after = page()
    assert after == before, "the translation changed what the page shows"

    lines = [ln for s in after["statements"] for ln in s["lines"]]
    assert {ln["unit"] for ln in lines if ln["unit"] and money.match(ln["unit"])} <= {"USD", "USD/shares"}
    revenue = next(
        ln
        for s in after["statements"]
        if s["code"] == "IS"
        for ln in s["lines"]
        if ln["concept"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    )
    assert revenue["values"]["Q1 2026"] == 140_000_000_000.0  # the home-currency figure, not 7x it
    assert sum(1 for ln in lines if ln["values"].get("Q1 2026") is not None) > 5  # lines were not emptied
