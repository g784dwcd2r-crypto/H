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
# Income from continuing operations as its own line. Preferred right-hand side for the tax identity.
CONTINUING_ONLY_CONCEPTS = (
    "IncomeLossFromContinuingOperations",
    "IncomeLossFromContinuingOperationsIncludingPortionAttributableToNoncontrollingInterest",
    "ProfitLossFromContinuingOperations",  # ifrs-full
)
# Bottom-line income: continuing plus discontinued operations. ProfitLoss first: it is the
# consolidated total, including the minority's share, which is what pretax income minus tax equals.
TOTAL_INCOME_CONCEPTS = ("ProfitLoss", "NetIncomeLoss")
# Earnings credited to the parent's own shareholders, which is what EPS is per share OF. The order is
# the reverse of the tax identity's: NetIncomeLoss (the parent's portion) before ProfitLoss (the
# consolidated total, including the minority's share). Taking ProfitLoss first failed 42 % of EPS
# checks on companies with subsidiaries, by exactly the minority's share.
EPS_FALLBACK_NUMERATOR_CONCEPTS = (
    "NetIncomeLoss",
    "ProfitLossAttributableToOwnersOfParent",  # ifrs-full
    "ProfitLoss",
)
# The minority's share of the consolidated profit, to bridge ProfitLoss down to the parent's portion
# when a filer reports the total only.
NONCONTROLLING_INCOME_CONCEPTS = (
    "NetIncomeLossAttributableToNoncontrollingInterest",
    "ProfitLossAttributableToNoncontrollingInterests",  # ifrs-full
)
CONTINUING_CONCEPTS = CONTINUING_ONLY_CONCEPTS + TOTAL_INCOME_CONCEPTS
# Results of businesses being sold or closed, reported after tax and below the tax line.
DISCONTINUED_CONCEPTS = (
    "IncomeLossFromDiscontinuedOperationsNetOfTax",
    "IncomeLossFromDiscontinuedOperationsNetOfTaxAttributableToReportingEntity",
    "IncomeLossFromDiscontinuedOperationsNetOfTaxIncludingPortionAttributableToNoncontrollingInterest",
    "ProfitLossFromDiscontinuedOperations",  # ifrs-full
)
# Share of an associate's profit. Some pretax concepts exclude it by definition (their name says so),
# in which case it has to be added back before comparing with income after tax.
EQUITY_METHOD_CONCEPTS = (
    "IncomeLossFromEquityMethodInvestments",
    "ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod",  # ifrs-full
)
# Preferred dividends sit between net income and the earnings the common shareholders are credited
# with, so EPS cannot be recomputed from total net income when any of these is present.
PREFERRED_DIVIDEND_CONCEPTS = (
    "PreferredStockDividendsAndOtherAdjustments",
    "PreferredStockDividendsIncomeStatementImpact",
    "DividendsPreferred",
    "PreferredStockDividendsShares",
)
EPS_NUMERATOR_CONCEPTS = (
    "NetIncomeLossAvailableToCommonStockholdersBasic",
    "NetIncomeLossAvailableToCommonStockholdersDiluted",
)
# (EPS concept, share-count concept) for the basic and diluted columns.
EPS_PAIRS = (
    ("basic", "EarningsPerShareBasic", "WeightedAverageNumberOfSharesOutstandingBasic"),
    ("diluted", "EarningsPerShareDiluted", "WeightedAverageNumberOfDilutedSharesOutstanding"),
)
# Concepts that must carry the same value wherever they appear in one filing. Compared like with
# like: the same concept on two statements, never two concepts that merely sound alike.
CROSS_STATEMENT_NET_INCOME = ("ProfitLoss", "NetIncomeLoss")
CROSS_STATEMENT_CASH = (
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    "CashAndCashEquivalentsAtCarryingValue",
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
        *EPS_FALLBACK_NUMERATOR_CONCEPTS,
        *NONCONTROLLING_INCOME_CONCEPTS,
        *DISCONTINUED_CONCEPTS,
        *EQUITY_METHOD_CONCEPTS,
        *PREFERRED_DIVIDEND_CONCEPTS,
        *EPS_NUMERATOR_CONCEPTS,
        *CROSS_STATEMENT_CASH,
        *[c for _, c, _ in EPS_PAIRS],
        *[c for _, _, c in EPS_PAIRS],
        *EQUITY_TOTAL_CONCEPTS,
        *NET_CHANGE_IN_CASH_INCL_FX,
        *NET_CHANGE_IN_CASH_EXCL_FX,
        *FX_CONCEPTS,
    }
)

RELATIVE_TOLERANCE = 0.005  # statements "may not sum due to rounding"; 0.5 % catches real breaks
ABSOLUTE_TOLERANCE = 1.0
CROSS_STATEMENT = "XS"  # `statement` value for a check that spans statements rather than sitting on one
EPS_ABSOLUTE_TOLERANCE = 0.01  # EPS is printed to the cent, so a cent of rounding is not a break
EPS_RELATIVE_TOLERANCE = 0.01


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
    out.extend(_check_income_after_tax(v))
    out.extend(_check_eps(v))
    return out


def _check_income_after_tax(v: dict[str, float]) -> list[CheckResult]:
    """Pretax income minus tax is income from CONTINUING operations, not the bottom line.

    Getting this wrong is how a correct filing fails a check: a company selling a business reports
    discontinued operations after tax, below the tax line, and a company using a pretax concept whose
    name says "...AndIncomeLossFromEquityMethodInvestments" has excluded its share of associates'
    profit from that subtotal. Both have to be bridged before the two sides can be compared.
    """
    pretax, tax = _first(v, PRETAX_CONCEPTS), _first(v, TAX_CONCEPTS)
    if not (pretax and tax):
        return []
    lhs, parts = pretax[1] - tax[1], [pretax[0], f"- {tax[0]}"]
    if "IncomeLossFromEquityMethodInvestments" in pretax[0] and (eq := _first(v, EQUITY_METHOD_CONCEPTS)):
        lhs += eq[1]  # the subtotal's own name says it is excluded
        parts.append(f"+ {eq[0]}")
    if cont := _first(v, CONTINUING_ONLY_CONCEPTS):
        return [_result("IS", "income_after_tax", lhs, cont[1], " ".join(parts) + f" = {cont[0]}")]
    total = _first(v, TOTAL_INCOME_CONCEPTS)
    if not total:
        return []
    if disc := _first(v, DISCONTINUED_CONCEPTS):
        lhs += disc[1]  # reported after tax, so it belongs on the same side as the bottom line
        parts.append(f"+ {disc[0]}")
    return [_result("IS", "income_after_tax", lhs, total[1], " ".join(parts) + f" = {total[0]}")]


def _eps_close(lhs: float, rhs: float) -> bool:
    return abs(lhs - rhs) <= max(EPS_ABSOLUTE_TOLERANCE, EPS_RELATIVE_TOLERANCE * abs(rhs))


def _check_eps(v: dict[str, float]) -> list[CheckResult]:
    """Earnings per share must be the earnings credited to common shareholders over the share count
    the company itself reported. Only runs when the numerator is unambiguous: either the company
    tagged earnings available to common, or it reports no preferred dividends to deduct."""
    numerator = _first(v, EPS_NUMERATOR_CONCEPTS)
    if numerator is None:
        if _first(v, PREFERRED_DIVIDEND_CONCEPTS):
            return []  # preferred dividends come out first and we cannot see how much
        numerator = _first(v, EPS_FALLBACK_NUMERATOR_CONCEPTS)
        if (
            numerator is not None
            and numerator[0] == "ProfitLoss"
            and (nci := _first(v, NONCONTROLLING_INCOME_CONCEPTS))
        ):
            # the consolidated total is all the filer gave; take the minority's share back out
            numerator = (f"ProfitLoss - {nci[0]}", numerator[1] - nci[1])
    if numerator is None:
        return []
    out: list[CheckResult] = []
    for kind, eps_concept, shares_concept in EPS_PAIRS:
        eps, shares = v.get(eps_concept), v.get(shares_concept)
        if eps is None or not shares:
            continue
        computed = numerator[1] / shares
        out.append(
            CheckResult(
                "IS",
                f"eps_{kind}",
                _eps_close(computed, eps),
                computed,
                eps,
                f"{numerator[0]} / {shares_concept} = {eps_concept}",
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


def check_across_statements(by_statement: dict[str, dict[str, float]]) -> list[CheckResult]:
    """One number filed twice must agree. Compared like with like: the SAME concept on two
    statements, never two concepts that merely sound alike, so a definitional difference (cash with
    restricted cash against cash without it) can never be reported as a break.

    Net income is the bottom of the income statement and the first line of the cash flow statement.
    Ending cash is the foot of the cash flow statement and a line on the balance sheet.
    """
    out: list[CheckResult] = []
    is_, cf, bs = (by_statement.get(k) or {} for k in ("IS", "CF", "BS"))
    for concept in CROSS_STATEMENT_NET_INCOME:
        if is_.get(concept) is not None and cf.get(concept) is not None:
            out.append(
                _result(CROSS_STATEMENT, "net_income_is_equals_cf", is_[concept], cf[concept], f"IS = CF ({concept})")
            )
            break
    for concept in CROSS_STATEMENT_CASH:
        if cf.get(concept) is not None and bs.get(concept) is not None:
            out.append(
                _result(CROSS_STATEMENT, "ending_cash_cf_equals_bs", cf[concept], bs[concept], f"CF = BS ({concept})")
            )
            break
    return out


CHECKERS = {"BS": check_balance_sheet, "IS": check_income_statement, "CF": check_cash_flow}


def run_checks(statement: str, values: dict[str, float]) -> list[CheckResult]:
    fn = CHECKERS.get(statement)
    return fn(values) if fn else []


def run_filing_checks(by_statement: dict[str, dict[str, float]]) -> list[CheckResult]:
    """Every check for one filing: the per-statement ones, then the cross-statement ones."""
    out: list[CheckResult] = []
    for statement, values in sorted(by_statement.items()):
        out.extend(run_checks(statement, values))
    out.extend(check_across_statements(by_statement))
    return out


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
    Mirrors the SQL window in sync_statements (tests keep them in sync).

    This is a POSITIONAL GUESS, not the company's declared arithmetic: the SEC summary data sets drop
    the filing's calculation tree, so we assume each line rolls into the next subtotal below it. It is
    right often but wrong often enough that it must NOT back a pass/fail check (a positional
    `subtotal_equals_children` flagged 98.3 % of filings and was worthless). It exists only to hint at
    grouping for display, and every place that exposes it labels it as inferred. The real parent comes
    from the filing's calculation tree once we read it (steps.md step 8); only then is a subtotal check
    meaningful."""
    next_sub: str | None = None
    for line in reversed(lines):
        line["parent_concept"] = next_sub
        if line.get("is_subtotal"):
            next_sub = line["concept"]
