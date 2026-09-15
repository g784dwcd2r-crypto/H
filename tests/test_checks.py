from filings_hub.ingest import checks as C


def names(results):
    return {r.check_name: r.passed for r in results}


def one(results, check_name):
    return next(r for r in results if r.check_name == check_name)


def test_balance_sheet_identity():
    assert names(C.check_balance_sheet({"Assets": 100, "LiabilitiesAndStockholdersEquity": 100})) == {
        "assets_eq_liabilities_and_equity": True
    }
    assert names(C.check_balance_sheet({"Assets": 100, "LiabilitiesAndStockholdersEquity": 90})) == {
        "assets_eq_liabilities_and_equity": False
    }
    # no L&SE tag -> liabilities + equity (+ minority interest, + temporary equity)
    r = C.check_balance_sheet(
        {
            "Assets": 100,
            "Liabilities": 60,
            "StockholdersEquity": 30,
            "MinorityInterest": 5,
            "TemporaryEquityCarryingAmountAttributableToParent": 5,
        }
    )
    assert names(r) == {"assets_eq_liabilities_plus_equity": True}
    assert "MinorityInterest" in r[0].detail
    assert C.check_balance_sheet({"Liabilities": 1}) == []


def test_ifrs_balance_sheet():
    assert names(C.check_balance_sheet({"Assets": 2100, "EquityAndLiabilities": 2100})) == {
        "assets_eq_liabilities_and_equity": True
    }
    assert names(C.check_balance_sheet({"Assets": 2100, "Liabilities": 1970, "Equity": 130})) == {
        "assets_eq_liabilities_plus_equity": True
    }


def test_income_statement_identities():
    v = {
        "Revenues": 100,
        "CostOfRevenue": 60,
        "GrossProfit": 40,
        "OperatingExpenses": 25,
        "OperatingIncomeLoss": 15,
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": 14,
        "IncomeTaxExpenseBenefit": 3,
        "NetIncomeLoss": 11,
    }
    assert names(C.check_income_statement(v)) == {
        "gross_profit": True,
        "operating_income": True,
        "income_after_tax": True,
    }
    v["GrossProfit"] = 39.9  # rounding within 0.5 %
    assert names(C.check_income_statement(v))["gross_profit"] is True
    v["GrossProfit"] = 35
    assert names(C.check_income_statement(v))["gross_profit"] is False
    # bank: no gross profit / opex -> only the tax identity
    bank = {
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": 59,
        "IncomeTaxExpenseBenefit": 12,
        "NetIncomeLoss": 47,
    }
    assert names(C.check_income_statement(bank)) == {"income_after_tax": True}
    # ifrs
    ifrs = {
        "Revenue": 100,
        "CostOfSales": 40,
        "GrossProfit": 60,
        "ProfitLossBeforeTax": 50,
        "IncomeTaxExpenseContinuingOperations": 10,
        "ProfitLoss": 40,
    }
    assert names(C.check_income_statement(ifrs)) == {"gross_profit": True, "income_after_tax": True}


def test_cash_flow_identity():
    v = {
        "NetCashProvidedByUsedInOperatingActivities": 120,
        "NetCashProvidedByUsedInInvestingActivities": 5,
        "NetCashProvidedByUsedInFinancingActivities": -124,
        "EffectOfExchangeRateOnCashAndCashEquivalents": 1,
        "CashAndCashEquivalentsPeriodIncreaseDecrease": 2,
    }
    assert names(C.check_cash_flow(v)) == {"net_change_in_cash": True}
    v2 = {
        "NetCashProvidedByUsedInOperatingActivities": 120,
        "NetCashProvidedByUsedInInvestingActivities": 5,
        "NetCashProvidedByUsedInFinancingActivities": -124,
        "CashAndCashEquivalentsPeriodIncreaseDecreaseExcludingExchangeRateEffect": 1,
    }
    assert names(C.check_cash_flow(v2)) == {"net_change_in_cash": True}
    assert C.check_cash_flow({"NetCashProvidedByUsedInOperatingActivities": 1}) == []
    ifrs = {
        "CashFlowsFromUsedInOperatingActivities": 10,
        "CashFlowsFromUsedInInvestingActivities": -3,
        "CashFlowsFromUsedInFinancingActivities": -2,
        "IncreaseDecreaseInCashAndCashEquivalents": 5,
    }
    assert names(C.check_cash_flow(ifrs)) == {"net_change_in_cash": True}


def test_run_checks_and_passed():
    assert C.run_checks("EQ", {"Assets": 1}) == []
    assert C.checks_passed([]) is None
    res = C.run_checks("BS", {"Assets": 100, "LiabilitiesAndStockholdersEquity": 100})
    assert C.checks_passed(res) is True
    assert res[0].difference == 0


def test_tolerance_absolute_floor():
    # tiny numbers: absolute tolerance of 1 unit
    assert C._close(3, 3.9) and not C._close(3, 4.5)


def test_is_subtotal_and_parents():
    assert C.is_subtotal("Assets", "whatever", False)
    assert C.is_subtotal("FooBar", "Total foo", False)
    assert C.is_subtotal("FooBar", "Net income attributable to parent", False)
    assert not C.is_subtotal("FooBar", "Totally not a total", False)
    assert not C.is_subtotal("Assets", "Total", True)  # abstract headers never are
    lines = [
        {"concept": "Cash", "is_subtotal": False},
        {"concept": "AssetsCurrent", "is_subtotal": True},
        {"concept": "PPE", "is_subtotal": False},
        {"concept": "Assets", "is_subtotal": True},
    ]
    C.assign_parents(lines)
    assert [ln["parent_concept"] for ln in lines] == ["AssetsCurrent", "Assets", "Assets", None]


def test_income_after_tax_bridges_discontinued_operations():
    """Pretax minus tax is income from CONTINUING operations. A company selling a business reports
    discontinued operations after tax, below the tax line, so comparing straight to the bottom line
    fails a filing that is perfectly correct (Citigroup and Morgan Stanley do this most years)."""
    v = {
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": 100,
        "IncomeTaxExpenseBenefit": 30,
        "ProfitLoss": 65,  # 70 from continuing, minus a 5 loss on the business being sold
    }
    assert names(C.check_income_statement(v))["income_after_tax"] is False  # nothing to bridge with
    v["IncomeLossFromDiscontinuedOperationsNetOfTax"] = -5
    r = one(C.check_income_statement(v), "income_after_tax")
    assert r.passed and "IncomeLossFromDiscontinuedOperationsNetOfTax" in r.detail


def test_income_after_tax_bridges_equity_method_when_the_subtotal_excludes_it():
    """The concept's own name says whether the share of associates' profit is inside the subtotal."""
    v = {
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments": 4789,
        "IncomeTaxExpenseBenefit": 1000,
        "IncomeLossFromEquityMethodInvestments": 221,
        "ProfitLoss": 4010,
    }
    r = one(C.check_income_statement(v), "income_after_tax")
    assert r.passed and "+ IncomeLossFromEquityMethodInvestments" in r.detail
    # a subtotal that already includes it must not be bridged
    v2 = {
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": 4789,
        "IncomeTaxExpenseBenefit": 1000,
        "IncomeLossFromEquityMethodInvestments": 221,
        "ProfitLoss": 3789,
    }
    assert names(C.check_income_statement(v2))["income_after_tax"] is True


def test_income_after_tax_prefers_the_reported_continuing_operations_line():
    v = {
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": 100,
        "IncomeTaxExpenseBenefit": 30,
        "IncomeLossFromContinuingOperations": 70,
        "IncomeLossFromDiscontinuedOperationsNetOfTax": -5,
        "NetIncomeLoss": 65,
    }
    r = one(C.check_income_statement(v), "income_after_tax")
    assert r.passed and r.detail.endswith("= IncomeLossFromContinuingOperations")


def test_eps_recomputes_from_the_company_s_own_share_count():
    v = {
        "NetIncomeLossAvailableToCommonStockholdersBasic": 9_373_600_000,
        "WeightedAverageNumberOfSharesOutstandingBasic": 1_000_000_000,
        "WeightedAverageNumberOfDilutedSharesOutstanding": 1_010_000_000,
        "EarningsPerShareBasic": 9.37,
        "EarningsPerShareDiluted": 9.28,
    }
    assert names(C.check_income_statement(v)) == {"eps_basic": True, "eps_diluted": True}
    v["EarningsPerShareBasic"] = 9.80  # beyond a cent of rounding
    assert names(C.check_income_statement(v))["eps_basic"] is False


def test_eps_is_skipped_when_preferred_dividends_hide_the_numerator():
    """Preferred dividends come out of net income before the common shareholders are credited, so
    without the available-to-common line the numerator is unknown. No check beats a wrong check."""
    v = {
        "NetIncomeLoss": 1_000,
        "PreferredStockDividendsAndOtherAdjustments": 100,
        "WeightedAverageNumberOfSharesOutstandingBasic": 100,
        "EarningsPerShareBasic": 9.0,
    }
    assert "eps_basic" not in names(C.check_income_statement(v))
    v["NetIncomeLossAvailableToCommonStockholdersBasic"] = 900
    assert names(C.check_income_statement(v))["eps_basic"] is True
    # zero shares never divides
    assert C._check_eps({"NetIncomeLoss": 1, "WeightedAverageNumberOfSharesOutstandingBasic": 0}) == []


def test_net_income_and_cash_must_agree_across_statements():
    by = {
        "IS": {"NetIncomeLoss": 93_736},
        "CF": {"NetIncomeLoss": 93_736, "CashAndCashEquivalentsAtCarryingValue": 29_943},
        "BS": {"CashAndCashEquivalentsAtCarryingValue": 29_943},
    }
    r = C.check_across_statements(by)
    assert names(r) == {"net_income_is_equals_cf": True, "ending_cash_cf_equals_bs": True}
    assert all(x.statement == C.CROSS_STATEMENT for x in r)
    by["CF"]["NetIncomeLoss"] = 90_000
    assert names(C.check_across_statements(by))["net_income_is_equals_cf"] is False


def test_cross_statement_checks_compare_like_with_like():
    """Cash including restricted cash is a different concept from cash without it, and a filing may
    legitimately carry one on each statement. Two different concepts are never compared."""
    by = {
        "CF": {"CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": 30_000},
        "BS": {"CashAndCashEquivalentsAtCarryingValue": 28_000},
    }
    assert C.check_across_statements(by) == []
    assert C.check_across_statements({}) == []


def test_run_filing_checks_covers_every_statement_and_the_cross_checks():
    by = {
        "BS": {"Assets": 100, "LiabilitiesAndStockholdersEquity": 100, "CashAndCashEquivalentsAtCarryingValue": 10},
        "IS": {"Revenues": 100, "CostOfRevenue": 60, "GrossProfit": 40, "NetIncomeLoss": 11},
        "CF": {"NetIncomeLoss": 11, "CashAndCashEquivalentsAtCarryingValue": 10},
    }
    got = names(C.run_filing_checks(by))
    assert got == {
        "assets_eq_liabilities_and_equity": True,
        "gross_profit": True,
        "net_income_is_equals_cf": True,
        "ending_cash_cf_equals_bs": True,
    }


def test_eps_is_per_share_of_the_parents_earnings_not_the_consolidated_total():
    """ProfitLoss is the consolidated profit including the minority shareholders' share of subsidiaries;
    NetIncomeLoss is the parent's portion, and EPS is per share of that. Taking ProfitLoss first failed
    42 % of EPS checks on companies with subsidiaries, by exactly the minority's share."""
    v = {
        "ProfitLoss": 1_200,  # 1,000 to the parent, 200 to minority holders
        "NetIncomeLoss": 1_000,
        "NetIncomeLossAttributableToNoncontrollingInterest": 200,
        "WeightedAverageNumberOfSharesOutstandingBasic": 100,
        "EarningsPerShareBasic": 10.0,  # 1,000 / 100, as the company reports it
    }
    eps = one(C.check_income_statement(v), "eps_basic")
    assert eps.passed and eps.lhs == 10.0 and eps.detail.startswith("NetIncomeLoss /")
    # the consolidated total would have said 12.00 and failed
    assert 1_200 / 100 == 12.0 and not C._eps_close(12.0, 10.0)


def test_eps_bridges_the_consolidated_total_by_the_minoritys_share_when_that_is_all_there_is():
    v = {
        "ProfitLoss": 1_200,
        "NetIncomeLossAttributableToNoncontrollingInterest": 200,
        "WeightedAverageNumberOfSharesOutstandingBasic": 100,
        "EarningsPerShareBasic": 10.0,
    }
    eps = one(C.check_income_statement(v), "eps_basic")
    assert eps.passed and eps.lhs == 10.0
    assert eps.detail.startswith("ProfitLoss - NetIncomeLossAttributableToNoncontrollingInterest /")
    # with no minority line, the total is the parent's and is used as before
    del v["NetIncomeLossAttributableToNoncontrollingInterest"]
    v["EarningsPerShareBasic"] = 12.0
    assert one(C.check_income_statement(v), "eps_basic").passed


def test_the_tax_identity_still_prefers_the_consolidated_total():
    """Pretax income minus tax is the consolidated profit, minority share included: the opposite
    preference from EPS, on purpose."""
    v = {
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": 1_500,
        "IncomeTaxExpenseBenefit": 300,
        "ProfitLoss": 1_200,
        "NetIncomeLoss": 1_000,
    }
    tax = one(C.check_income_statement(v), "income_after_tax")
    assert tax.passed and tax.rhs == 1_200 and tax.detail.endswith("= ProfitLoss")


def test_diluted_eps_takes_the_diluted_numerator_when_the_company_tags_both():
    """Diluted earnings can carry add-backs (convertible interest) that basic does not. Checking the
    diluted EPS against the basic numerator was off by exactly those."""
    v = {
        "NetIncomeLossAvailableToCommonStockholdersBasic": 1_000,
        "NetIncomeLossAvailableToCommonStockholdersDiluted": 1_060,  # + 60 of convertible interest
        "WeightedAverageNumberOfSharesOutstandingBasic": 100,
        "WeightedAverageNumberOfDilutedSharesOutstanding": 106,
        "EarningsPerShareBasic": 10.0,
        "EarningsPerShareDiluted": 10.0,
    }
    r = {c.check_name: c for c in C.check_income_statement(v)}
    assert r["eps_basic"].passed and r["eps_basic"].detail.startswith(
        "NetIncomeLossAvailableToCommonStockholdersBasic /"
    )
    assert r["eps_diluted"].passed and r["eps_diluted"].detail.startswith(
        "NetIncomeLossAvailableToCommonStockholdersDiluted /"
    )
    # with only the basic numerator tagged, diluted falls back to it, as before
    del v["NetIncomeLossAvailableToCommonStockholdersDiluted"]
    r = {c.check_name: c for c in C.check_income_statement(v)}
    assert (
        r["eps_diluted"].detail.startswith("NetIncomeLossAvailableToCommonStockholdersBasic /")
        and not r["eps_diluted"].passed
    )
