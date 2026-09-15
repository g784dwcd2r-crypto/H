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
    """When the pretax tag's name says the share of associates' profit is outside the subtotal, the
    add-back is tried; it is taken only when it is what closes the identity (see the next test for
    the filers who use the same tag for a subtotal that already includes it)."""
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
    eps = one(C.check_income_statement(v), "eps_basic_approx")
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
    eps = one(C.check_income_statement(v), "eps_basic_approx")
    assert eps.passed and eps.lhs == 10.0
    assert eps.detail.startswith("ProfitLoss - NetIncomeLossAttributableToNoncontrollingInterest /")
    # with no minority line, the total is the parent's and is used as before
    del v["NetIncomeLossAttributableToNoncontrollingInterest"]
    v["EarningsPerShareBasic"] = 12.0
    assert one(C.check_income_statement(v), "eps_basic_approx").passed


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


def test_eps_is_exact_with_the_companys_numerator_and_approximate_without_it():
    """Two-class allocations and preferred dividends live in the EPS note, not on the statement. With
    the company's own numerator the check is exact (1 %); with net income standing in it is
    approximate (5 %), named so, and says so."""
    # a 3 % gap: the company allocated 3 % of earnings to unvested shares with dividend rights
    inferred = {
        "NetIncomeLoss": 1_000,
        "WeightedAverageNumberOfSharesOutstandingBasic": 100,
        "EarningsPerShareBasic": 9.7,
    }
    r = one(C.check_income_statement(inferred), "eps_basic_approx")
    assert r.passed and r.detail.endswith("(numerator inferred)")
    assert "eps_basic" not in names(C.check_income_statement(inferred))
    # the same gap with the company's own numerator tagged is a real break
    tagged = {**inferred, "NetIncomeLossAvailableToCommonStockholdersBasic": 1_000}
    r = one(C.check_income_statement(tagged), "eps_basic")
    assert not r.passed and "inferred" not in r.detail
    assert "eps_basic_approx" not in names(C.check_income_statement(tagged))
    # past 5 %, the approximate check still fails: a wrong share count is not an allocation
    assert not one(C.check_income_statement({**inferred, "EarningsPerShareBasic": 9.0}), "eps_basic_approx").passed


def test_the_tax_identity_compares_to_consolidated_continuing_income_not_the_parents_portion():
    """Pretax income minus tax is consolidated: the minority's share is still in it. The plain
    IncomeLossFromContinuingOperations is the parent's portion after that share comes out."""
    v = {
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": 100.0,
        "IncomeTaxExpenseBenefit": 20.0,
        "IncomeLossFromContinuingOperationsIncludingPortionAttributableToNoncontrollingInterest": 80.0,
        "IncomeLossFromContinuingOperations": 70.0,  # the parent's, after a 10 minority share
        "NetIncomeLossAttributableToNoncontrollingInterest": 10.0,
    }
    r = one(C.check_income_statement(v), "income_after_tax")
    assert r.passed and r.rhs == 80.0 and r.detail.endswith("IncludingPortionAttributableToNoncontrollingInterest")
    # only the parent's line tagged: the minority's share is put back
    del v["IncomeLossFromContinuingOperationsIncludingPortionAttributableToNoncontrollingInterest"]
    r = one(C.check_income_statement(v), "income_after_tax")
    assert r.passed and r.rhs == 80.0
    assert r.detail.endswith("= IncomeLossFromContinuingOperations + NetIncomeLossAttributableToNoncontrollingInterest")
    # the parent's line and no minority tagged: compared as it is, and the gap shows honestly
    del v["NetIncomeLossAttributableToNoncontrollingInterest"]
    r = one(C.check_income_statement(v), "income_after_tax")
    assert not r.passed and r.rhs == 70.0


def test_the_tax_identity_does_not_trust_tag_names_and_records_which_reading_held():
    """Filers use the same tags both ways, so the check tries every legitimate after-tax line, with
    and without the equity-method add-back, and records which held. Numbers from the real filings
    that showed it."""
    # CHS: the pretax tag whose name says equity-method income is excluded, used for a subtotal that
    # includes it; adding the 175.8m back double-counted. Closes without the add-back.
    chs = {
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments": 419_878_000,
        "IncomeTaxExpenseBenefit": -4_091_000,
        "IncomeLossFromEquityMethodInvestments": 175_777_000,
        "ProfitLoss": 423_969_000,
        "NetIncomeLoss": 424_192_000,
    }
    r = one(C.check_income_statement(chs), "income_after_tax")
    assert r.passed and "+ IncomeLossFromEquityMethodInvestments" not in r.detail
    assert r.detail.endswith("= ProfitLoss")
    # QVC: IncomeLossFromContinuingOperations already consolidated (equal to ProfitLoss); the minority
    # bridge broke it. Closes on the line as it is.
    qvc = {
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments": 98_000_000,
        "IncomeTaxExpenseBenefit": 57_000_000,
        "IncomeLossFromEquityMethodInvestments": 39_000_000,
        "IncomeLossFromContinuingOperations": 41_000_000,
        "NetIncomeLossAttributableToNoncontrollingInterest": 4_000_000,
        "ProfitLoss": 41_000_000,
    }
    r = one(C.check_income_statement(qvc), "income_after_tax")
    assert r.passed and r.detail.endswith("= IncomeLossFromContinuingOperations")
    # nothing closes: reported against the preferred pair, the plain reading and the first line
    broken = {**qvc, "IncomeTaxExpenseBenefit": 50_000_000}
    r = one(C.check_income_statement(broken), "income_after_tax")
    assert not r.passed and r.lhs == 48_000_000 and r.rhs == 41_000_000
    assert r.detail.endswith("= IncomeLossFromContinuingOperations") and "+ IncomeLossFromEquityMethod" not in r.detail


def test_the_net_change_in_cash_reads_the_exchange_rate_effect_both_ways():
    """Filers that tag the exchange-rate effect separately state the net change BEFORE it, whatever
    the tag's name promises. Numbers from the real filings that showed it."""
    # Valspar: ops + investing + financing = -23,495, exactly the tagged period increase/decrease;
    # adding the -13,682 effect misses by exactly that
    valspar = {
        "NetCashProvidedByUsedInOperatingActivities": 398_504_000,
        "NetCashProvidedByUsedInInvestingActivities": -313_960_000,
        "NetCashProvidedByUsedInFinancingActivities": -108_039_000,
        "EffectOfExchangeRateOnCashAndCashEquivalents": -13_682_000,
        "CashAndCashEquivalentsPeriodIncreaseDecrease": -23_495_000,
    }
    r = one(C.check_cash_flow(valspar), "net_change_in_cash")
    assert r.passed and r.lhs == -23_495_000 and "+ fx" not in r.detail
    # TDCX, the IFRS tag whose name says the effect is inside it: same story
    tdcx = {
        "CashFlowsFromUsedInOperatingActivities": 103_825_000,
        "CashFlowsFromUsedInInvestingActivities": -44_139_000,
        "CashFlowsFromUsedInFinancingActivities": 199_644_000,
        "EffectOfExchangeRateChangesOnCashAndCashEquivalents": -5_990_000,
        "IncreaseDecreaseInCashAndCashEquivalents": 259_330_000,
    }
    assert one(C.check_cash_flow(tdcx), "net_change_in_cash").passed
    # a filer who does include it still passes, on the reading its tag promises
    including = {
        "NetCashProvidedByUsedInOperatingActivities": 100.0,
        "NetCashProvidedByUsedInInvestingActivities": -40.0,
        "NetCashProvidedByUsedInFinancingActivities": 10.0,
        "EffectOfExchangeRateOnCashAndCashEquivalents": -5.0,
        "CashAndCashEquivalentsPeriodIncreaseDecrease": 65.0,
    }
    r = one(C.check_cash_flow(including), "net_change_in_cash")
    assert r.passed and r.lhs == 65.0 and "+ fx" in r.detail
    # a genuinely wrong total matches neither reading
    assert not one(
        C.check_cash_flow({**including, "CashAndCashEquivalentsPeriodIncreaseDecrease": 90.0}), "net_change_in_cash"
    ).passed


def test_the_tax_identity_offers_the_bottom_line_with_and_without_discontinued_operations():
    """China Jo-Jo: the pretax figure already carries the discontinued result, so the bottom line as
    it stands is what closes, not the bottom line less discontinued operations."""
    v = {
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": -6_441_419,
        "IncomeTaxExpenseBenefit": 16_258,
        "IncomeLossFromDiscontinuedOperationsNetOfTax": 644_308,
        "ProfitLoss": -6_457_677,
        "NetIncomeLoss": -5_813_369,
    }
    r = one(C.check_income_statement(v), "income_after_tax")
    assert r.passed and r.rhs == -6_457_677 and r.detail.endswith("= ProfitLoss")


def test_the_tax_identity_offers_both_bottom_line_tags():
    """Texas Capital tagged ProfitLoss after preferred dividends and NetIncomeLoss as the total; the
    identity closes on the second, so both are candidates."""
    v = {
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments": 65_375_000,
        "IncomeTaxExpenseBenefit": 22_833_000,
        "ProfitLoss": 40_104_000,
        "NetIncomeLoss": 42_542_000,
        "PreferredStockDividendsIncomeStatementImpact": 2_438_000,
    }
    r = one(C.check_income_statement(v), "income_after_tax")
    assert r.passed and r.rhs == 42_542_000 and r.detail.endswith("= NetIncomeLoss")


def test_the_tax_identity_completes_the_domestic_pretax_line_with_its_foreign_half():
    v = {
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic": 300.0,
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeign": 200.0,
        "IncomeTaxExpenseBenefit": 100.0,
        "NetIncomeLoss": 400.0,
    }
    r = one(C.check_income_statement(v), "income_after_tax")
    assert r.passed and r.lhs == 400.0 and "Foreign" in r.detail
    # a filer who tagged the whole of pretax income under the domestic name still closes
    alone = {**v, "IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeign": 0.0, "NetIncomeLoss": 200.0}
    assert one(C.check_income_statement(alone), "income_after_tax").passed
