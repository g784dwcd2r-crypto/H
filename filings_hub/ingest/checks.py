"""Arithmetic checks per statement and subtotal heuristics shared by the FSDS and fallback builders.

Values are the raw XBRL values (costs positive, cash-flow activities signed), taken from the filing's
primary period column. Every check runs only when all of its operands are present; `checks_passed` is
NULL when no check applied.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Concepts that are presented as subtotals in almost every filing. Combined with a label regex
# (^total ...) this is how `is_subtotal` is decided; FSDS carries no calculation hierarchy.
SUBTOTAL_CONCEPTS = frozenset(
    {
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "CostsAndExpenses",
        "OperatingExpenses",
        "GrossProfit",
        "OperatingIncomeLoss",
        "NonoperatingIncomeExpense",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "IncomeLossFromContinuingOperations",
        "ProfitLoss",
        "NetIncomeLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "ComprehensiveIncomeNetOfTax",
        "ComprehensiveIncomeNetOfTaxIncludingPortionAttributableToNoncontrollingInterest",
        "OtherComprehensiveIncomeLossNetOfTax",
        "OtherComprehensiveIncomeLossNetOfTaxPortionAttributableToParent",
        "AssetsCurrent",
        "AssetsNoncurrent",
        "Assets",
        "LiabilitiesCurrent",
        "LiabilitiesNoncurrent",
        "Liabilities",
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "LiabilitiesAndStockholdersEquity",
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInInvestingActivities",
        "NetCashProvidedByUsedInFinancingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
        "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",
        "CashAndCashEquivalentsPeriodIncreaseDecrease",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseExcludingExchangeRateEffect",
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "InterestAndDividendIncomeOperating",
        "InterestExpense",
        "InterestIncomeExpenseNet",
        "InterestIncomeExpenseAfterProvisionForLoanLoss",
        "NoninterestIncome",
        "NoninterestExpense",
    }
)

SUBTOTAL_LABEL_REGEX = (
    r"^\s*(total|net (income|loss|earnings|cash)|gross (profit|margin)|operating (income|loss|profit))\b"
)

REVENUE_CONCEPTS = (
    "Revenues",
    "Revenue",  # ifrs-full
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "RevenuesNetOfInterestExpense",
)
COST_OF_REVENUE_CONCEPTS = (
    "CostOfRevenue",
    "CostOfSales",  # ifrs-full
    "CostOfGoodsAndServicesSold",
    "CostOfGoodsSold",
    "CostOfServices",
    "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization",
)
PRETAX_CONCEPTS = (
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "ProfitLossBeforeTax",  # ifrs-full
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
)
TAX_CONCEPTS = ("IncomeTaxExpenseBenefit", "IncomeTaxExpenseContinuingOperations")
CONTINUING_CONCEPTS = (
    "IncomeLossFromContinuingOperations",
    "ProfitLossFromContinuingOperations",  # ifrs-full
    "ProfitLoss",
    "NetIncomeLoss",
)
EQUITY_TOTAL_CONCEPTS = (
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    "StockholdersEquity",
    "Equity",  # ifrs-full
)
LIABILITIES_AND_EQUITY_CONCEPTS = ("LiabilitiesAndStockholdersEquity", "EquityAndLiabilities")
OPERATING_CF = (
    "NetCashProvidedByUsedInOperatingActivities",
    "CashFlowsFromUsedInOperatingActivities",
)
INVESTING_CF = (
    "NetCashProvidedByUsedInInvestingActivities",
    "CashFlowsFromUsedInInvestingActivities",
)
FINANCING_CF = (
    "NetCashProvidedByUsedInFinancingActivities",
    "CashFlowsFromUsedInFinancingActivities",
)
NET_CHANGE_IN_CASH_INCL_FX = (
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
    "CashAndCashEquivalentsPeriodIncreaseDecrease",
    "IncreaseDecreaseInCashAndCashEquivalents",  # ifrs-full
)
NET_CHANGE_IN_CASH_EXCL_FX = (
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseExcludingExchangeRateEffect",
    "CashAndCashEquivalentsPeriodIncreaseDecreaseExcludingExchangeRateEffect",
    "IncreaseDecreaseInCashAndCashEquivalentsBeforeEffectOfExchangeRateChanges",  # ifrs-full
)
FX_CONCEPTS = (
    "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    "EffectOfExchangeRateOnCashAndCashEquivalents",
    "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",
    "EffectOfExchangeRateChangesOnCashAndCashEquivalents",  # ifrs-full
)

CHECK_CONCEPTS = frozenset(
    {
        "Assets",
        "Liabilities",
        "TemporaryEquityCarryingAmountAttributableToParent",
        "TemporaryEquityCarryingAmountIncludingPortionAttributableToNoncontrollingInterest",
        "MinorityInterest",
        "GrossProfit",
        "OperatingExpenses",
        "OperatingIncomeLoss",
        *LIABILITIES_AND_EQUITY_CONCEPTS,
        *OPERATING_CF,
        *INVESTING_CF,
        *FINANCING_CF,
        *REVENUE_CONCEPTS,
        *COST_OF_REVENUE_CONCEPTS,
        *PRETAX_CONCEPTS,
        *TAX_CONCEPTS,
        *CONTINUING_CONCEPTS,
        *EQUITY_TOTAL_CONCEPTS,
        *NET_CHANGE_IN_CASH_INCL_FX,
        *NET_CHANGE_IN_CASH_EXCL_FX,
        *FX_CONCEPTS,
    }
)

RELATIVE_TOLERANCE = 0.005  # statements "may not sum due to rounding"; 0.5 % catches real breaks
ABSOLUTE_TOLERANCE = 1.0


@dataclass(frozen=True)
class CheckResult:
    statement: str
    check_name: str
    passed: bool
    lhs: float
    rhs: float
    detail: str

    @property
    def difference(self) -> float:
        return self.lhs - self.rhs


def _first(values: dict[str, float], concepts: tuple[str, ...]) -> tuple[str, float] | None:
    for c in concepts:
        if c in values and values[c] is not None:
            return c, values[c]
    return None


def _close(lhs: float, rhs: float) -> bool:
    tol = max(ABSOLUTE_TOLERANCE, RELATIVE_TOLERANCE * max(abs(lhs), abs(rhs)))
    return abs(lhs - rhs) <= tol


def _result(statement: str, name: str, lhs: float, rhs: float, detail: str) -> CheckResult:
    return CheckResult(statement, name, _close(lhs, rhs), lhs, rhs, detail)


def check_balance_sheet(v: dict[str, float]) -> list[CheckResult]:
    out: list[CheckResult] = []
    assets = v.get("Assets")
    if assets is None:
        return out
    if le := _first(v, LIABILITIES_AND_EQUITY_CONCEPTS):
        out.append(_result("BS", "assets_eq_liabilities_and_equity", assets, le[1], f"Assets = {le[0]}"))
    elif v.get("Liabilities") is not None and (eq := _first(v, EQUITY_TOTAL_CONCEPTS)):
        rhs = v["Liabilities"] + eq[1]
        parts = ["Liabilities", eq[0]]
        if eq[0] == "StockholdersEquity" and v.get("MinorityInterest") is not None:
            rhs += v["MinorityInterest"]
            parts.append("MinorityInterest")
        for t in (
            "TemporaryEquityCarryingAmountIncludingPortionAttributableToNoncontrollingInterest",
            "TemporaryEquityCarryingAmountAttributableToParent",
        ):
            if v.get(t) is not None:
                rhs += v[t]
                parts.append(t)
                break
        out.append(
            _result(
                "BS",
                "assets_eq_liabilities_plus_equity",
                assets,
                rhs,
                "Assets = " + " + ".join(parts),
            )
        )
    return out


def check_income_statement(v: dict[str, float]) -> list[CheckResult]:
    out: list[CheckResult] = []
    rev, cost, gp = (
        _first(v, REVENUE_CONCEPTS),
        _first(v, COST_OF_REVENUE_CONCEPTS),
        v.get("GrossProfit"),
    )
    if rev and cost and gp is not None:
        out.append(_result("IS", "gross_profit", rev[1] - cost[1], gp, f"{rev[0]} - {cost[0]} = GrossProfit"))
    if gp is not None and v.get("OperatingExpenses") is not None and v.get("OperatingIncomeLoss") is not None:
        out.append(
            _result(
                "IS",
                "operating_income",
                gp - v["OperatingExpenses"],
                v["OperatingIncomeLoss"],
                "GrossProfit - OperatingExpenses = OperatingIncomeLoss",
            )
        )
    pretax, tax = _first(v, PRETAX_CONCEPTS), _first(v, TAX_CONCEPTS)
    if pretax and tax:
        cont = _first(v, CONTINUING_CONCEPTS)
        if cont:
            out.append(
                _result(
                    "IS",
                    "income_after_tax",
                    pretax[1] - tax[1],
                    cont[1],
                    f"{pretax[0]} - {tax[0]} = {cont[0]}",
                )
            )
    return out


def check_cash_flow(v: dict[str, float]) -> list[CheckResult]:
    out: list[CheckResult] = []
    ops, inv, fin = _first(v, OPERATING_CF), _first(v, INVESTING_CF), _first(v, FINANCING_CF)
    if not (ops and inv and fin):
        return out
    activities = ops[1] + inv[1] + fin[1]
    fx = _first(v, FX_CONCEPTS)
    if incl := _first(v, NET_CHANGE_IN_CASH_INCL_FX):
        lhs = activities + (fx[1] if fx else 0.0)
        out.append(
            _result(
                "CF",
                "net_change_in_cash",
                lhs,
                incl[1],
                f"ops + investing + financing{' + fx' if fx else ''} = {incl[0]}",
            )
        )
    elif excl := _first(v, NET_CHANGE_IN_CASH_EXCL_FX):
        out.append(
            _result(
                "CF",
                "net_change_in_cash",
                activities,
                excl[1],
                f"ops + investing + financing = {excl[0]}",
            )
        )
    return out


CHECKERS = {"BS": check_balance_sheet, "IS": check_income_statement, "CF": check_cash_flow}


def run_checks(statement: str, values: dict[str, float]) -> list[CheckResult]:
    fn = CHECKERS.get(statement)
    return fn(values) if fn else []


def checks_passed(results: list[CheckResult]) -> bool | None:
    if not results:
        return None
    return all(r.passed for r in results)


def is_subtotal(concept: str | None, label: str | None, is_abstract: bool) -> bool:
    import re

    if is_abstract:
        return False
    if concept in SUBTOTAL_CONCEPTS:
        return True
    return bool(label and re.match(SUBTOTAL_LABEL_REGEX, label, flags=re.IGNORECASE))


def assign_parents(lines: list[dict[str, Any]]) -> None:
    """Set `parent_concept` on ordered lines of one statement: the next subtotal after each line.
    Mirrors the SQL window in sync_statements (tests keep them in sync)."""
    next_sub: str | None = None
    for line in reversed(lines):
        line["parent_concept"] = next_sub
        if line.get("is_subtotal"):
            next_sub = line["concept"]
