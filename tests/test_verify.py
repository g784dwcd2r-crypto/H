"""The acceptance harness itself: every criterion must pass, fail and abstain correctly.

The criteria need real SEC data to mean anything, so these tests drive each check against records
shaped like the ones a real lake produces, and assert the harness reaches the right verdict.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from filings_hub import verify as V
from filings_hub.db.database import Database
from filings_hub.testing import edgar_fixtures as fx


class FakeDB:
    """Answers the harness's queries from canned rows, keyed by a distinctive fragment of each query."""

    backend = "duckdb"
    periods_table = "periods_serving"

    def __init__(self, **canned):
        self.canned = canned

    def query(self, sql, params=()):
        for fragment, rows in self.canned.items():
            if fragment in sql:
                return rows(params) if callable(rows) else rows
        return []


def _run(kind, status, started, seconds=60.0, index_dates=(), **kw):
    return {
        "run_id": f"{kind}-{started}",
        "kind": kind,
        "status": status,
        "started_at": datetime.fromisoformat(f"{started}T06:00:00"),
        "duration_seconds": seconds,
        "index_dates": list(index_dates),
        "new_filings": kw.get("new_filings", 10),
        "facts_rows": kw.get("facts_rows", 100),
        "db_loaded": True,
        "failures": [],
    }


# --- 1. backfill duration -------------------------------------------------------------------
def test_backfill_duration():
    fast = FakeDB(**{"kind = 'backfill'": [_run("backfill", "ok", "2026-09-01", seconds=3.5 * 3600)]})
    c = V.check_backfill_duration(fast)
    assert c.passed is True and "3.50 h" in c.detail

    slow = FakeDB(**{"kind = 'backfill'": [_run("backfill", "ok", "2026-09-01", seconds=5 * 3600)]})
    assert V.check_backfill_duration(slow).passed is False

    assert V.check_backfill_duration(FakeDB()).passed is None  # never run
    failed = FakeDB(**{"kind = 'backfill'": [_run("backfill", "failed", "2026-09-01")]})
    assert V.check_backfill_duration(failed).passed is False


# --- 2. five consecutive unattended weekdays -------------------------------------------------
def _weekday_runs(days: list[str], status="ok"):
    return [_run("refresh", status, d, index_dates=[d]) for d in days]


def test_refresh_streak():
    # Mon 2026-09-07 .. Fri 2026-09-11
    week = ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"]
    ok = FakeDB(**{"kind = 'refresh'": _weekday_runs(week)})
    c = V.check_refresh_streak(ok)
    assert c.passed is True and "5/5" in c.detail

    # a gap in the middle
    gap = FakeDB(**{"kind = 'refresh'": _weekday_runs([d for d in week if d != "2026-09-09"])})
    c = V.check_refresh_streak(gap)
    assert c.passed is False and "2026-09-09" in " ".join(c.evidence)

    # a failed run anywhere in the window is manual intervention waiting to happen
    runs = _weekday_runs(week)
    runs[2]["status"] = "failed"
    assert V.check_refresh_streak(FakeDB(**{"kind = 'refresh'": runs})).passed is False

    assert V.check_refresh_streak(FakeDB()).passed is None
    # runs that never processed an index date do not count
    none_processed = FakeDB(**{"kind = 'refresh'": [_run("refresh", "ok", "2026-09-11")]})
    assert V.check_refresh_streak(none_processed).passed is False


def test_weekdays_back_skips_the_weekend():
    assert V._weekdays_back(date(2026, 9, 14), 5) == [
        date(2026, 9, 8),
        date(2026, 9, 9),
        date(2026, 9, 10),
        date(2026, 9, 11),
        date(2026, 9, 14),
    ]


# --- 3. the golden set ------------------------------------------------------------------------
def _period(label, fq, end, **kw):
    return {
        "period_label": label,
        "fiscal_year": kw.get("fy", 2025),
        "fiscal_quarter": fq,
        "period_end": date.fromisoformat(end),
        "results_accession": kw.get("acc", f"acc-{label}"),
        "results_form": "10-K" if fq == 4 else "10-Q",
        "results_filed_date": date.fromisoformat(end) + timedelta(days=30),
        "earnings_release_accession": kw.get("er", f"er-{label}"),
        "earnings_release_filed_date": date.fromisoformat(end) + timedelta(days=25) if kw.get("er", True) else None,
        "statements_source": kw.get("source", "fsds"),
        "checks_passed": kw.get("checks", True),
    }


def _company_db(periods, lines=(("IS", 20), ("BS", 15), ("CF", 12)), ticker="TEST"):
    return FakeDB(
        **{
            "FROM tickers WHERE ticker": lambda p: [{"cik": 1}] if p[0] == ticker else [],
            "ORDER BY period_end DESC LIMIT 20": periods,
            "ORDER BY period_end DESC LIMIT 8": periods[:8],
            "FROM statements WHERE accession": [{"statement": s, "n": n} for s, n in lines],
        }
    )


def test_golden_company_passes_on_a_healthy_company():
    periods = [_period("FY2025", 4, "2025-09-27"), _period("Q3 2025", 3, "2025-06-28")]
    ok, detail = V.check_golden_company(_company_db(periods), "TEST")
    assert ok is True and "2 periods" in detail and "2 with an earnings release" in detail


@pytest.mark.parametrize(
    ("periods", "lines", "expected"),
    [
        ([], (("IS", 1),), "no periods"),
        ([_period("2025 Q1", 1, "2025-03-31")], (("IS", 1),), "malformed period labels"),
        ([_period("Q1 2025", 1, "2025-03-31")], (("IS", 1),), "no annual period"),
        ([_period("FY2025", 4, "2025-12-31", source=None)], (("IS", 1),), "no period has statements"),
        ([_period("FY2025", 4, "2025-12-31", checks=False)], (("IS", 1), ("BS", 1)), "arithmetic checks failed"),
        ([_period("FY2025", 4, "2025-12-31")], (("BS", 1),), "no income statement"),
        ([_period("FY2025", 4, "2025-12-31")], (("IS", 1),), "no balance sheet"),
    ],
)
def test_golden_company_rejects_broken_data(periods, lines, expected):
    ok, detail = V.check_golden_company(_company_db(periods, lines), "TEST")
    assert ok is False and expected in detail


def test_golden_company_detects_duplicate_labels():
    dupes = [_period("FY2025", 4, "2025-12-31"), _period("FY2025", 4, "2025-12-30")]
    ok, detail = V.check_golden_company(_company_db(dupes), "TEST")
    assert ok is False and "duplicate period labels" in detail


def test_golden_set_abstains_when_the_universe_is_missing():
    golden = [{"ticker": t, "covers": ""} for t in ("AAA", "BBB", "CCC", "DDD")]
    c = V.check_golden_set(FakeDB(), golden)
    assert c.passed is None and "not in this universe" in c.detail


def test_golden_set_fails_when_present_but_broken():
    golden = [{"ticker": "TEST", "covers": ""}]
    db = _company_db([_period("FY2025", 4, "2025-12-31", checks=False)])
    c = V.check_golden_set(db, golden)
    assert c.passed is False and "0/1" in c.detail


# --- 4. earnings-release coverage -------------------------------------------------------------
def test_earnings_release_coverage():
    golden = [{"ticker": "TEST", "covers": ""}]
    full = _company_db([_period("FY2025", 4, "2025-12-31"), _period("Q3 2025", 3, "2025-09-30")])
    assert V.check_earnings_release_coverage(full, golden).passed is True

    none = _company_db([_period("FY2025", 4, "2025-12-31", er=None), _period("Q3 2025", 3, "2025-09-30", er=None)])
    c = V.check_earnings_release_coverage(none, golden)
    assert c.passed is False and "0/2" in c.detail


def test_earnings_release_flags_an_implausible_lag():
    golden = [{"ticker": "TEST", "covers": ""}]
    late = _period("FY2025", 4, "2025-12-31")
    late["earnings_release_filed_date"] = date(2026, 12, 1)  # ~11 months after the period end
    c = V.check_earnings_release_coverage(_company_db([late]), golden)
    assert any("days after period end" in e for e in c.evidence)


# --- 5. checks_passed rate --------------------------------------------------------------------
def _quality_db(companies, periods, applicable, passed, provisional=0):
    return FakeDB(
        **{
            "sum(CASE WHEN p.checks_passed": [
                {
                    "periods": periods,
                    "applicable": applicable,
                    "passed": passed,
                    "companies": companies,
                    "provisional": provisional,
                }
            ]
        }
    )


def test_quality_threshold():
    universe = list(range(1, 501))
    good = _quality_db(companies=480, periods=5000, applicable=4800, passed=4700)
    c = V.check_statement_quality(good, ciks=universe)
    assert c.passed is True and "97.9%" in c.detail

    bad = _quality_db(companies=480, periods=5000, applicable=4800, passed=4000)
    assert V.check_statement_quality(bad, ciks=universe).passed is False

    # a rate over a fraction of the universe verifies nothing either way
    partial = _quality_db(companies=3, periods=10, applicable=7, passed=7)
    c = V.check_statement_quality(partial, ciks=universe)
    assert c.passed is None and "3/500" in c.detail

    empty = _quality_db(companies=0, periods=0, applicable=0, passed=0)
    assert V.check_statement_quality(empty, ciks=universe).passed is None


# --- vendored reference data --------------------------------------------------------------------
def test_vendored_sp500_list():
    ciks = V.load_sp500()
    assert 450 < len(ciks) < 520
    assert all(isinstance(c, int) and c > 0 for c in ciks)
    # the index lists more symbols than filers: a dual-class listing is two tickers on one CIK
    assert len(set(ciks)) == len(ciks)
    assert 320193 in ciks and 19617 in ciks  # Apple and JPMorgan


def test_golden_set_is_the_shape_the_plan_asks_for():
    golden = V.load_golden_set()
    assert len(golden) == 20
    assert all(row["ticker"] and row["covers"] for row in golden)
    assert len({row["ticker"] for row in golden}) == 20
    covers = " ".join(row["covers"] for row in golden).lower()
    for characteristic in ("reit", "insurer", "biotech", "40-f", "bank", "52/53-week"):
        assert characteristic in covers, characteristic


# --- end to end against a built lake ------------------------------------------------------------
def test_report_and_exit_status_on_a_lake_without_real_data(built_lake):
    db = Database("", built_lake)
    try:
        criteria = V.run_acceptance(db, golden=V.load_golden_set())
        report = V.format_report(criteria)
    finally:
        db.close()
    assert "Phase 1 definition of done" in report
    # the fixture universe is seven synthetic companies, so nothing real can be claimed as verified
    assert not any(c.passed is False for c in criteria), report
    assert sum(c.passed is None for c in criteria) >= 3, report
    assert "not in this universe" in report


def test_golden_set_exports_workbooks(built_lake, tmp_path):
    db = Database("", built_lake)
    try:
        written = V.export_golden_set(db, [{"ticker": "AAPL", "covers": ""}], tmp_path, periods=3)
    finally:
        db.close()
    assert [p.name for p in written] == ["AAPL-statements.xlsx"]
    assert written[0].stat().st_size > 5000
    assert fx.APPLE  # the export resolved through the real tickers table


# --- the passing path, end to end through the real SQL ------------------------------------------
def _acceptance_lake(root, golden, sp500_ciks, *, checks_pass_rate=1.0, weekdays=5):
    """A lake shaped like one built from real SEC data: the golden set and the S&P 500 universe, each
    with periods, statements and a run log. Written straight to parquet so the test exercises the
    harness's real SQL rather than a stand-in."""
    import pyarrow as pa

    from filings_hub.ingest.periods import PERIODS_SCHEMA
    from filings_hub.ingest.refresh import RUN_LOG_SCHEMA
    from filings_hub.ingest.sync_statements import STATEMENTS_SCHEMA
    from filings_hub.ingest.sync_universe import COMPANIES_SCHEMA, TICKERS_SCHEMA
    from filings_hub.lake import layout
    from filings_hub.lake.storage import Storage

    st = Storage(str(root))
    golden_ciks = {row["ticker"]: 900_000 + i for i, row in enumerate(golden)}
    all_ciks = sorted(set(sp500_ciks) | set(golden_ciks.values()))

    companies, tickers = [], []
    for cik in all_ciks:
        ticker = next((t for t, c in golden_ciks.items() if c == cik), f"T{cik}")
        companies.append(
            {
                "cik": cik,
                "name": f"Company {cik}",
                "ticker": ticker,
                "exchange": "NYSE",
                "sic": "1000",
                "sic_description": "x",
                "entity_type": "operating",
                "category": None,
                "state_of_incorporation": "DE",
                "state_of_incorporation_description": None,
                "fiscal_year_end": "1231",
                "ein": None,
                "former_names": [],
                "business_state": None,
                "business_city": None,
                "website": None,
                "is_listed": True,
                "is_active": True,
                "last_filing_date": date(2026, 2, 20),
                "last_financial_report_date": date(2026, 2, 20),
                "last_financial_report_form": "10-K",
                "filing_count": 50,
            }
        )
        tickers.append({"cik": cik, "ticker": ticker, "exchange": "NYSE", "is_primary": True, "source": "x"})
    st.write_parquet(layout.COMPANIES, pa.Table.from_pylist(companies, schema=COMPANIES_SCHEMA))
    st.write_parquet(layout.TICKERS, pa.Table.from_pylist(tickers, schema=TICKERS_SCHEMA))

    periods, statements = [], []
    n = 0
    for cik in all_ciks:
        for fy in (2024, 2025):
            for fq, end in ((4, f"{fy}-12-31"), (3, f"{fy}-09-30")):
                n += 1
                acc = f"{cik:010d}-{fy % 100:02d}-{fq:06d}"
                periods.append(
                    {
                        "cik": cik,
                        "period_label": (f"FY{fy}" if fq == 4 else f"Q3 {fy}"),
                        "fiscal_year": fy,
                        "fiscal_quarter": fq,
                        "period_type": "annual" if fq == 4 else "quarter",
                        "period_end": date.fromisoformat(end),
                        "results_accession": acc,
                        "results_form": "10-K" if fq == 4 else "10-Q",
                        "results_filed_date": date.fromisoformat(end) + timedelta(days=40),
                        "results_primary_doc_url": f"https://www.sec.gov/{acc}.htm",
                        "earnings_release_accession": f"er-{acc}",
                        "earnings_release_filed_date": date.fromisoformat(end) + timedelta(days=30),
                        "earnings_release_primary_doc_url": None,
                        "amendment_accessions": [],
                        "label_method": "period_end",
                    }
                )
                # a share of filings fail their arithmetic checks, to exercise the threshold
                passes = (n % 100) >= round((1 - checks_pass_rate) * 100)
                for stmt, lines in (("IS", 12), ("BS", 10), ("CF", 9)):
                    for line in range(1, lines + 1):
                        statements.append(
                            {
                                "accession": acc,
                                "cik": cik,
                                "statement": stmt,
                                "report": 1,
                                "line": line,
                                "line_order": line,
                                "is_parenthetical": False,
                                "concept": f"C{line}",
                                "taxonomy": "us-gaap/2025",
                                "label": f"Line {line}",
                                "standard_label": None,
                                "negating": False,
                                "is_abstract": False,
                                "is_custom": False,
                                "iord": "D",
                                "crdr": None,
                                "datatype": "monetary",
                                "period_start": None,
                                "period_end": date.fromisoformat(end),
                                "period_end_rounded": date.fromisoformat(end),
                                "qtrs": 4,
                                "unit": "USD",
                                "value": 1.0,
                                "value_presented": 1.0,
                                "is_primary_period": True,
                                "is_subtotal": False,
                                "parent_concept": None,
                                "source": "fsds",
                                "fsds_quarter": "2026q1",
                                "form": "10-K",
                                "filed_date": date.fromisoformat(end) + timedelta(days=40),
                                "checks_passed": passes,
                            }
                        )
    st.write_parquet(layout.PERIODS, pa.Table.from_pylist(periods, schema=PERIODS_SCHEMA))
    st.write_parquet(
        f"{layout.STATEMENTS}/cik=1/part-0.parquet", pa.Table.from_pylist(statements, schema=STATEMENTS_SCHEMA)
    )

    runs = [
        {
            "run_id": "backfill-1",
            "kind": "backfill",
            "started_at": datetime(2026, 9, 1, 2, 0),
            "finished_at": datetime(2026, 9, 1, 5, 0),
            "duration_seconds": 3.0 * 3600,
            "status": "ok",
            "index_dates": [],
            "new_filings": 1_000_000,
            "ciks_refreshed": len(all_ciks),
            "facts_rows": 100_000_000,
            "statements_built": 5000,
            "fsds_quarters_loaded": [],
            "failures": [],
            "error": None,
            "db_loaded": True,
        }
    ]
    for i, day in enumerate(V._weekdays_back(date(2026, 9, 11), weekdays)):
        runs.append(
            {
                "run_id": f"refresh-{i}",
                "kind": "refresh",
                "started_at": datetime.combine(day, datetime.min.time()).replace(hour=6),
                "finished_at": None,
                "duration_seconds": 400.0,
                "status": "ok",
                "index_dates": [day.isoformat()],
                "new_filings": 3000,
                "ciks_refreshed": 900,
                "facts_rows": 50_000,
                "statements_built": 400,
                "fsds_quarters_loaded": [],
                "failures": [],
                "error": None,
                "db_loaded": True,
            }
        )
    st.write_parquet(f"{layout.RUN_LOG}/runs.parquet", pa.Table.from_pylist(runs, schema=RUN_LOG_SCHEMA))
    return st


def test_every_criterion_passes_on_a_lake_at_real_shape(tmp_path):
    """Proves the harness is not vacuously abstaining: given a universe of the right shape, every
    criterion reaches PASS through the same SQL it would run against real SEC data."""
    golden = V.load_golden_set()
    st = _acceptance_lake(tmp_path / "lake", golden, V.load_sp500())
    db = Database("", st)
    try:
        criteria = V.run_acceptance(db, golden=golden)
        report = V.format_report(criteria, verbose=True)
    finally:
        db.close()
    assert [c.status for c in criteria] == ["PASS"] * 5, report
    by_name = {c.name.split(" ")[0]: c for c in criteria}
    assert "3.00 h" in by_name["Bulk"].detail
    assert "20/20" in by_name["20-company"].detail
    assert "over 500 companies" in by_name["checks_passed"].detail


def test_the_quality_criterion_fails_below_the_threshold(tmp_path):
    st = _acceptance_lake(tmp_path / "lake", V.load_golden_set(), V.load_sp500(), checks_pass_rate=0.90)
    db = Database("", st)
    try:
        c = V.check_statement_quality(db, ciks=V.load_sp500())
    finally:
        db.close()
    assert c.passed is False and "90" in c.detail


def test_the_refresh_criterion_fails_on_a_short_streak(tmp_path):
    st = _acceptance_lake(tmp_path / "lake", V.load_golden_set(), V.load_sp500(), weekdays=3)
    db = Database("", st)
    try:
        c = V.check_refresh_streak(db)
    finally:
        db.close()
    assert c.passed is False and "3/5" in c.detail
