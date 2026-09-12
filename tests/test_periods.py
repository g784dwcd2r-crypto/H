from datetime import date

from filings_hub.ingest import periods as P


def f(acc, form, filed, report, items=""):
    return {
        "accession": acc,
        "form": form,
        "filed_date": date.fromisoformat(filed),
        "report_date": date.fromisoformat(report) if report else None,
        "items": items.split(",") if items else [],
        "primary_doc_url": f"https://x/{acc}",
    }


def test_parse_fye():
    assert P.parse_fye("0927") == (9, 27)
    assert P.parse_fye("1231") == (12, 31)
    assert P.parse_fye("0229") == (2, 29)
    assert P.parse_fye(None) is None
    assert P.parse_fye("13") is None
    assert P.parse_fye("1332") is None


def test_safe_date_clamps_leap_day():
    assert P.safe_date(2025, 2, 29) == date(2025, 2, 28)
    assert P.safe_date(2024, 2, 29) == date(2024, 2, 29)


def test_apple_quarters_from_nominal_fye():
    fye = (9, 30)
    assert P.fiscal_period_for(date(2025, 12, 27), "quarter", fye).key == (2026, 1)
    assert P.fiscal_period_for(date(2026, 3, 28), "quarter", fye).key == (2026, 2)
    assert P.fiscal_period_for(date(2026, 6, 27), "quarter", fye).key == (2026, 3)
    assert P.fiscal_period_for(date(2025, 9, 27), "annual", fye).key == (2025, 4)
    # 53-week year ending a few days after the nominal FYE is still the same fiscal year
    assert P.fiscal_period_for(date(2025, 10, 3), "annual", fye).key == (2025, 4)


def test_quarter_uses_real_annual_anchor_over_nominal_fye():
    # FYE changed from March to December: nominal says 0331 but the actual next 10-K ends 2024-12-31
    anchors = [date(2023, 3, 31), date(2024, 12, 31)]
    fp = P.fiscal_period_for(date(2024, 9, 30), "quarter", (3, 31), anchors)
    assert fp.key == (2024, 3) and fp.method == "anchor"
    # without the anchor the nominal FYE would have put it in FY2025
    assert P.fiscal_period_for(date(2024, 9, 30), "quarter", (3, 31)).key == (2025, 2)


def test_53_week_retailer():
    fye = (1, 31)
    anchors = [date(2024, 2, 3), date(2025, 2, 1)]
    assert P.fiscal_period_for(date(2024, 5, 4), "quarter", fye, anchors).key == (2025, 1)
    assert P.fiscal_period_for(date(2024, 8, 3), "quarter", fye, anchors).key == (2025, 2)
    assert P.fiscal_period_for(date(2024, 11, 2), "quarter", fye, anchors).key == (2025, 3)
    assert P.fiscal_period_for(date(2024, 2, 3), "annual", fye, anchors).key == (2024, 4)
    # same answers with only the nominal FYE
    assert P.fiscal_period_for(date(2024, 5, 4), "quarter", fye).key == (2025, 1)


def test_fallback_when_no_fye_and_no_anchor():
    fp = P.fiscal_period_for(date(2024, 5, 31), "quarter", None)
    assert fp.method == "fallback" and fp.key == (2024, 2)
    fp = P.fiscal_period_for(date(2024, 11, 30), "quarter", None)
    assert fp.key == (2024, 3)  # a 4th "quarter" never exists for a 10-Q


def test_irregular_distance_falls_through():
    # 10-Q ending 1 month before FYE (transition-like) -> nominal cannot place it -> calendar fallback
    fp = P.fiscal_period_for(date(2024, 11, 30), "quarter", (12, 31))
    assert fp.method == "fallback"


def test_labels():
    assert P.period_label(P.FiscalPeriod(2025, 4, "x")) == "FY2025"
    assert P.period_label(P.FiscalPeriod(2026, 1, "x")) == "Q1 2026"
    assert P.period_label(P.FiscalPeriod(2026, 2, "x"), transition=True) == "Q2 2026T"


def test_build_periods_apple_like():
    filings = [
        f("k24", "10-K", "2024-11-01", "2024-09-28"),
        f("e24a", "8-K", "2024-10-31", "2024-10-31", "2.02,9.01"),
        f("e24b", "8-K", "2024-11-15", "2024-11-15", "2.02,9.01"),  # second 2.02 -> not picked
        f("k24a", "10-K/A", "2025-01-15", "2024-09-28"),
        f("q1", "10-Q", "2025-01-31", "2024-12-28"),
        f("e1", "8-K", "2025-01-30", "2025-01-30", "2.02"),
        f("noise", "4", "2025-02-01", "2025-01-31"),
        f("other8k", "8-K", "2025-02-20", "2025-02-20", "5.02"),
        f("q2", "10-Q", "2025-05-02", "2025-03-29"),
        f("k25", "10-K", "2025-10-31", "2025-09-27"),
        f("nodate", "10-Q", "2025-12-01", None),  # no report date -> ignored
    ]
    rows = P.build_periods_for_company(320193, filings, "0927")
    by_label = {r["period_label"]: r for r in rows}
    assert list(by_label) == ["FY2025", "Q2 2025", "Q1 2025", "FY2024"]  # newest first
    fy24 = by_label["FY2024"]
    assert fy24["results_accession"] == "k24"
    assert fy24["earnings_release_accession"] == "e24a"
    assert fy24["amendment_accessions"] == ["k24a"]
    assert fy24["period_type"] == "annual" and fy24["fiscal_quarter"] == 4
    q1 = by_label["Q1 2025"]
    assert q1["earnings_release_accession"] == "e1"
    assert q1["label_method"] == "anchor"
    assert by_label["Q2 2025"]["earnings_release_accession"] is None
    assert by_label["FY2025"]["results_primary_doc_url"] == "https://x/k25"


def test_amendment_only_period_and_transition():
    filings = [
        f("ka", "10-Q/A", "2025-06-01", "2025-03-31"),
        f("kt", "10-KT", "2025-09-15", "2025-06-30"),
        f("k", "10-K", "2026-02-15", "2025-12-31"),
    ]
    rows = P.build_periods_for_company(1, filings, "1231")
    labels = {r["period_label"]: r for r in rows}
    assert labels["Q1 2025"]["results_accession"] == "ka" and labels["Q1 2025"]["label_method"] == "amendment_only"
    assert labels["FY2025T"]["period_type"] == "transition"
    assert labels["FY2025"]["results_accession"] == "k"


def test_latest_original_wins_when_refiled():
    filings = [
        f("k1", "10-K", "2025-02-01", "2024-12-31"),
        f("k2", "10-K", "2025-02-05", "2024-12-31"),
    ]
    rows = P.build_periods_for_company(1, filings, "1231")
    assert rows[0]["results_accession"] == "k2" and rows[0]["amendment_accessions"] == ["k1"]


def test_earnings_release_windows():
    filings = [
        f("k", "10-K", "2025-03-01", "2024-12-31"),
        f("late", "8-K", "2025-03-25", "2025-03-25", "2.02"),  # 84 days after FYE: inside the 90-day annual window
        f("q", "10-Q", "2025-05-10", "2025-03-31"),
        f("toolate", "8-K", "2025-06-15", "2025-06-15", "2.02"),  # 76 days after Q1 end: outside the 60-day window
    ]
    rows = {r["period_label"]: r for r in P.build_periods_for_company(1, filings, "1231")}
    assert rows["FY2024"]["earnings_release_accession"] == "late"
    assert rows["Q1 2025"]["earnings_release_accession"] is None


def test_next_expected_results():
    rows = [
        {
            "fiscal_year": 2025,
            "fiscal_quarter": 4,
            "period_end": date(2025, 9, 27),
            "results_filed_date": date(2025, 10, 31),
            "earnings_release_filed_date": date(2025, 10, 30),
        },
        {
            "fiscal_year": 2025,
            "fiscal_quarter": 1,
            "period_end": date(2024, 12, 28),
            "results_filed_date": date(2025, 1, 31),
            "earnings_release_filed_date": date(2025, 1, 30),
        },
    ]
    nxt = P.next_expected_results(rows)
    assert nxt["period_label"] == "Q1 2026"
    assert nxt["expected_results_filed_date"] == date(2026, 1, 30)
    assert nxt["expected_earnings_release_date"] == date(2026, 1, 29)
    assert P.next_expected_results([]) is None
    # no prior-year twin -> statutory-ish lag
    nxt = P.next_expected_results([rows[0]])
    assert nxt["expected_results_filed_date"] == nxt["period_end"] + __import__("datetime").timedelta(days=40)


def test_periods_table_schema():
    rows = P.build_periods_for_company(1, [f("k", "10-K", "2025-02-01", "2024-12-31")], "1231")
    t = P.periods_table(rows)
    assert t.num_rows == 1 and t.schema == P.PERIODS_SCHEMA


def test_52_53_week_year_ending_just_after_new_year():
    """Snap-on's fiscal 2021 ended 2022-01-01 and its fiscal 2022 ended 2022-12-31. Naming the fiscal
    year after the calendar year of the period end collapsed both into FY2022, so a whole year vanished
    from the spine and its filings were reclassified as amendments of the next one."""
    fye = (12, 31)
    assert P.fiscal_year_of(date(2022, 1, 1), fye) == 2021
    assert P.fiscal_year_of(date(2022, 12, 31), fye) == 2022
    assert P.fiscal_year_of(date(2023, 12, 30), fye) == 2023
    assert P.fiscal_period_for(date(2022, 1, 1), "annual", fye).key == (2021, 4)
    assert P.fiscal_period_for(date(2022, 12, 31), "annual", fye).key == (2022, 4)

    filings = [
        f("f2021-q1", "10-Q", "2021-04-29", "2021-04-02"),
        f("f2021-q2", "10-Q", "2021-07-29", "2021-07-03"),
        f("f2021-q3", "10-Q", "2021-10-28", "2021-10-02"),
        f("f2021-10k", "10-K", "2022-02-10", "2022-01-01"),
        f("f2022-q1", "10-Q", "2022-04-28", "2022-04-02"),
        f("f2022-q2", "10-Q", "2022-07-28", "2022-07-02"),
        f("f2022-q3", "10-Q", "2022-10-27", "2022-10-01"),
        f("f2022-10k", "10-K", "2023-02-09", "2022-12-31"),
    ]
    rows = P.build_periods_for_company(55785, filings, "1231")
    assert len(rows) == 8, [r["period_label"] for r in rows]
    by_label = {r["period_label"]: r["results_accession"] for r in rows}
    assert by_label == {
        "Q1 2021": "f2021-q1",
        "Q2 2021": "f2021-q2",
        "Q3 2021": "f2021-q3",
        "FY2021": "f2021-10k",
        "Q1 2022": "f2022-q1",
        "Q2 2022": "f2022-q2",
        "Q3 2022": "f2022-q3",
        "FY2022": "f2022-10k",
    }
    assert all(not r["amendment_accessions"] for r in rows)


def test_fiscal_year_falls_back_when_the_year_end_moved():
    """A company that changed its fiscal year end must not have old periods pulled toward the new one."""
    # nominal FYE is now December, but this annual report ended in June: name it for the year it ended
    assert P.fiscal_year_of(date(2019, 6, 30), (12, 31)) == 2019
    assert P.fiscal_year_of(date(2019, 6, 30), None) == 2019
    # a 53-week year ending a few days *before* the nominal date still belongs to that year
    assert P.fiscal_year_of(date(2025, 9, 27), (9, 30)) == 2025
    assert P.fiscal_year_of(date(2024, 2, 3), (1, 31)) == 2024
