from filings_hub.ingest import checks as C


def names(results):
    return {r.check_name: r.passed for r in results}


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
