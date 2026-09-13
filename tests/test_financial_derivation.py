"""Independent arithmetic cases for the financial release gate (not investment estimates)."""

from datetime import date

import pytest

from filings_hub.export.grid import PeriodColumn, _Derive, _Rows


def _period(year, quarter):
    end = date(year, quarter * 3, (31, 30, 30, 31)[quarter - 1])
    return PeriodColumn(
        period_label=f"FY{year}" if quarter == 4 else f"Q{quarter} {year}",
        period_end=end,
        fiscal_year=year,
        fiscal_quarter=quarter,
        accession=f"{year}-q{quarter}",
        form="10-K" if quarter == 4 else "10-Q",
        filed_date=date(year + 1, 2, 1) if quarter == 4 else date(year, quarter * 3 + 1, 20),
        filing_index_url=f"https://example.test/{year}-q{quarter}-index.htm",
        primary_doc_url=f"https://example.test/{year}-q{quarter}.htm",
        earnings_release_accession=None,
        earnings_release_url=None,
        statements_source="fsds",
        checks_passed=True,
        period_type="annual" if quarter == 4 else "quarter",
    )


def _fact(p, value, concept="NetIncomeLoss", qtrs=None, **overrides):
    qtrs = qtrs if qtrs is not None else p.fiscal_quarter
    return {
        "accession": p.accession,
        "concept": concept,
        "label": concept,
        "value_presented": value,
        "value": value,
        "qtrs": qtrs,
        "unit": "USD",
        "taxonomy": "us-gaap/2025",
        "is_custom": False,
        "negating": False,
        "is_primary_period": True,
        "period_start": date(p.fiscal_year, (p.fiscal_quarter - qtrs) * 3 + 1, 1),
        "period_end": p.period_end,
        "period_end_rounded": p.period_end,
        **overrides,
    }


def _deriver(periods, facts, statement="IS"):
    rows = _Rows({p.accession: {statement: facts.get(p.accession, [])} for p in periods}, periods)
    return _Derive(rows, statement, periods)


@pytest.mark.parametrize(
    "concept,unit",
    [
        ("WeightedAverageNumberOfSharesOutstandingBasic", "shares"),
        ("WeightedAverageNumberOfDilutedSharesOutstanding", "shares"),
        ("EarningsPerShareDiluted", "USD/shares"),
        ("EffectiveIncomeTaxRateContinuingOperations", "pure"),
        ("AverageInterestEarningAssets", "USD"),
    ],
)
def test_nonadditive_annual_minus_ytd_is_unavailable(concept, unit):
    p3, p4 = _period(2025, 3), _period(2025, 4)
    derive = _deriver(
        [p3, p4],
        {
            p3.accession: [_fact(p3, 100, concept, unit=unit)],
            p4.accession: [_fact(p4, 100, concept, unit=unit)],
        },
    )
    cell = derive.quarter(2025, 4, f"{concept}|{concept.lower()}", concept)
    assert cell.value is None  # a 100-share average must never become 0 shares
    assert cell.status == "unavailable" and cell.reason


def test_reported_q4_shares_win_over_unavailable_derivation():
    p4 = _period(2025, 4)
    concept = "WeightedAverageNumberOfSharesOutstandingBasic"
    derive = _deriver(
        [p4],
        {
            p4.accession: [
                _fact(p4, 100, concept, unit="shares"),
                _fact(p4, 104, concept, qtrs=1, unit="shares", is_primary_period=False),
            ]
        },
    )
    cell = derive.quarter(2025, 4, f"{concept}|{concept.lower()}", concept)
    assert cell.value == 104 and cell.status == "reported"
    assert cell.sources[0]["period_start"] == "2025-10-01"


def test_nonadditive_ltm_requires_direct_reported_period():
    pprev, p4, pcurrent = _period(2024, 2), _period(2024, 4), _period(2025, 2)
    concept = "EarningsPerShareDiluted"
    derive = _deriver(
        [pprev, p4, pcurrent],
        {
            pprev.accession: [_fact(pprev, 2.1, concept, unit="USD/shares")],
            p4.accession: [_fact(p4, 4.7, concept, unit="USD/shares")],
            pcurrent.accession: [_fact(pcurrent, 2.5, concept, unit="USD/shares")],
        },
    )
    key = f"{concept}|{concept.lower()}"
    assert derive.ltm(2025, 2, key, concept).value is None
    assert derive.ltm(2024, 4, key, concept).value == 4.7


@pytest.mark.parametrize("concept", ["NetIncomeLoss", "RevenuesNetOfInterestExpense"])
def test_flow_difference_has_reproducible_sources(concept):
    p3, p4 = _period(2025, 3), _period(2025, 4)
    derive = _deriver(
        [p3, p4],
        {
            p3.accession: [_fact(p3, 310, concept)],
            p4.accession: [_fact(p4, 450, concept)],
        },
    )
    cell = derive.quarter(2025, 4, f"{concept}|{concept.lower()}", concept)
    assert cell.value == 140 and cell.status == "derived"
    assert sum(s["value"] * s["coefficient"] for s in cell.sources) == cell.value
    assert [s["accession"] for s in cell.sources] == [p4.accession, p3.accession]
    assert cell.sources[0]["document_url"] == p4.primary_doc_url


@pytest.mark.parametrize(
    "prior_overrides,reason",
    [
        ({"unit": "EUR"}, "currencies"),
        ({"negating": True}, "sign"),
        ({"taxonomy": "issuer/2025", "is_custom": True}, "taxonomies"),
        ({"period_start": date(2025, 2, 1)}, "fiscal-year start"),
    ],
)
def test_incompatible_inputs_do_not_produce_a_number(prior_overrides, reason):
    p3, p4 = _period(2025, 3), _period(2025, 4)
    derive = _deriver(
        [p3, p4],
        {
            p3.accession: [_fact(p3, 310, **prior_overrides)],
            p4.accession: [_fact(p4, 450)],
        },
    )
    cell = derive.quarter(2025, 4, "NetIncomeLoss|netincomeloss", "NetIncomeLoss")
    assert cell.value is None and reason in cell.reason


def test_custom_concept_with_standard_local_name_is_not_derived():
    p3, p4 = _period(2025, 3), _period(2025, 4)
    derive = _deriver(
        [p3, p4], {p.accession: [_fact(p, 100, taxonomy="issuer/2025", is_custom=True)] for p in [p3, p4]}
    )
    cell = derive.quarter(2025, 4, "NetIncomeLoss|netincomeloss", "NetIncomeLoss")
    assert cell.value is None and "company-defined" in cell.reason


def test_changed_comparative_does_not_mix_reporting_bases():
    pp, pfy, pc = _period(2024, 2), _period(2024, 4), _period(2025, 2)
    comparative = _fact(pp, 220, accession=pc.accession, is_primary_period=False)
    derive = _deriver(
        [pp, pfy, pc],
        {
            pp.accession: [_fact(pp, 200)],
            pfy.accession: [_fact(pfy, 500)],
            pc.accession: [_fact(pc, 250), comparative],
        },
    )
    cell = derive.ltm(2025, 2, "NetIncomeLoss|netincomeloss", "NetIncomeLoss")
    assert cell.value is None and "comparative changed" in cell.reason


def test_repeated_source_occurrences_are_never_merged_by_label_alias():
    p1, p2 = _period(2024, 4), _period(2025, 4)
    first = [_fact(p1, 1, label="Beginning balance"), _fact(p1, 2, label="Ending balance")]
    second = [_fact(p2, 3, label="Ending balance")]
    rows = _Rows({p1.accession: {"EQ": first}, p2.accession: {"EQ": second}}, [p1, p2])
    assert len(rows.primary(p1.accession, "EQ")) == 2
    assert rows.primary(p2.accession, "EQ")[0][0] == rows.primary(p1.accession, "EQ")[1][0]


def test_repeated_comparatives_remain_distinct_when_primary_labels_change():
    p1, p2 = _period(2024, 4), _period(2025, 4)
    rows = _Rows(
        {
            p1.accession: {"IS": [_fact(p1, 1, label="Older label")]},
            p2.accession: {
                "IS": [
                    _fact(p2, 3, label="Newer label"),
                    _fact(p1, 1, label="Older label", accession=p2.accession, is_primary_period=False),
                    _fact(p1, 2, label="Newer label", accession=p2.accession, is_primary_period=False),
                ]
            },
        },
        [p1, p2],
    )
    comparative = rows.groups(p2.accession, "IS")[(p1.period_end, 4)]
    assert len(comparative) == 2
    assert {r["value_presented"] for r in comparative.values()} == {1, 2}
    assert rows.primary(p1.accession, "IS")[0][0] != rows.primary(p2.accession, "IS")[0][0]


@pytest.mark.parametrize("changed", [{"unit": "EUR"}, {"taxonomy": "issuer/2025", "is_custom": True}])
def test_label_alias_does_not_merge_different_units_or_taxonomies(changed):
    p1, p2 = _period(2024, 4), _period(2025, 4)
    rows = _Rows(
        {
            p1.accession: {"IS": [_fact(p1, 1, label="Older label")]},
            p2.accession: {"IS": [_fact(p2, 2, label="Newer label", **changed)]},
        },
        [p1, p2],
    )
    assert rows.primary(p1.accession, "IS")[0][0] != rows.primary(p2.accession, "IS")[0][0]


def test_fsds_currency_only_pershare_joins_exact_fiscal_dates(built_lake):
    from filings_hub.ingest.sync_statements import _stage_fsds_quarter
    from filings_hub.lake.duck import Duck
    from filings_hub.testing import edgar_fixtures as fx

    duck = Duck(built_lake)
    try:
        duck.create_views()
        # Alter only this connection's input view; leave the shared lake files untouched.
        duck.sql("""CREATE TEMP TABLE currency_only_num AS
            SELECT * REPLACE (CASE WHEN tag = 'EarningsPerShareDiluted' THEN 'USD' ELSE uom END AS uom)
            FROM fsds_num""")
        duck.sql("CREATE OR REPLACE VIEW fsds_num AS SELECT * FROM currency_only_num")
        _stage_fsds_quarter(duck, "2025q4", enrich=True)
        eps = duck.fetch_dicts(
            """SELECT unit, value_presented, period_start, period_end FROM stg
            WHERE accession = ? AND concept = 'EarningsPerShareDiluted' AND is_primary_period""",
            [fx.APPLE_10K_FY2025],
        )
        assert eps == [
            {
                "unit": "USD/shares",
                "value_presented": 7.46,
                "period_start": date(2024, 9, 29),
                "period_end": date(2025, 9, 27),
            }
        ]
        assert (
            duck.fetch_value(
                "SELECT unit FROM stg WHERE accession = ? AND concept = 'NetIncomeLoss' AND statement = 'IS' AND is_primary_period",
                [fx.APPLE_10K_FY2025],
            )
            == "USD"
        )
    finally:
        duck.close()
