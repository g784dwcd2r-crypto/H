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
# The domestic component of pretax income has a foreign counterpart; the two sum to the total. Taken
# alone, the domestic tag failed three times as often as any other pretax line.
FOREIGN_PRETAX_CONCEPTS = ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeign",)
TAX_CONCEPTS = ("IncomeTaxExpenseBenefit", "IncomeTaxExpenseContinuingOperations")
# Income from continuing operations as its own line: what pretax income minus tax equals. The
# consolidated figure first, because pretax income is consolidated (the minority's share is in it).
# The plain `IncomeLossFromContinuingOperations` is the PARENT's portion, after the minority's share
# comes out; listed first it failed 26 % of the time, short by exactly that share. It comes last, and
# the minority's share is added back when the filer tagged it.
CONTINUING_ONLY_CONCEPTS = (
    "IncomeLossFromContinuingOperationsIncludingPortionAttributableToNoncontrollingInterest",
    "ProfitLossFromContinuingOperations",  # ifrs-full, consolidated
    "IncomeLossFromContinuingOperations",  # attributable to the parent
)
# Bottom-line income: continuing plus discontinued operations. ProfitLoss first: it is the
# consolidated total, including the minority's share, which is what pretax income minus tax equals.
# Tax is owed by the whole entity and the state does not care who owns which subsidiary, so every
# term in that identity is the group's.
TOTAL_INCOME_CONCEPTS = ("ProfitLoss", "NetIncomeLoss")
# Earnings credited to the parent's own shareholders, which is what EPS is per share OF. This is not
# the tax identity's order reversed; the two face different counterparties. Tax faces the state,
# which taxes the entity whole. A share faces its holder, whose claim is on the parent alone, so the
# minority's share of a subsidiary is not theirs. Taking ProfitLoss first failed 42 % of EPS checks
# on companies with subsidiaries, by exactly the minority's share.
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
        *FOREIGN_PRETAX_CONCEPTS,
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
# When the company did not tag its own EPS numerator, net income stands in for it. The company's
# numerator then differs by what its EPS note does: the two-class allocation to unvested shares with
# dividend rights (1-4 % of earnings, routinely) and preferred dividends and accretion on a loss.
# Those live in the note, not on the income statement, so the check cannot see them; measured on a
# sample, 79 % of such near-misses had no trace on the statement. An inferred numerator can vouch to
# about 5 %, which still catches a wrong share count, a scale, a sign or a period; it cannot vouch to
# the cent, and the check says so in its name.
EPS_APPROX_RELATIVE_TOLERANCE = 0.05


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
    """Pretax income minus tax must equal an after-tax line the filing offers.

    Which line, and with what bridge, cannot be read off the tag names, because filers use the same
    tags both ways. `IncomeLossFromContinuingOperations` is defined as the parent's portion and is
    short by the minority's share on some filings, but is the consolidated figure on others (equal to
    `ProfitLoss` to the dollar); a bridge that always added the minority's share failed 69 % of the
    time. The pretax tag whose name says equity-method income is excluded is used, six filings in
    eight, for a subtotal that includes it; an add-back that trusted the name double-counted. A filer
    reporting discontinued operations may still tag a pretax figure that carries them, so the bottom
    line stands as a candidate beside the bottom line less discontinued operations. And a filer may
    tag the total under `ProfitLoss`, under `NetIncomeLoss`, or put its earnings available to common
    in one and the consolidated total in the other, so both are offered.

    So the check does what an analyst does: it asks whether pretax minus tax equals any legitimate
    after-tax line, in a fixed preference order, and records which held. A wrong tax figure or a wrong
    bottom line still fails every candidate; only the tag ambiguity is absorbed. A failure is reported
    against the preferred pair.
    """
    pretax, tax = _first(v, PRETAX_CONCEPTS), _first(v, TAX_CONCEPTS)
    if not (pretax and tax):
        return []
    bases: list[tuple[float, str]] = [(pretax[1], pretax[0])]
    if pretax[0].endswith("Domestic") and (foreign := _first(v, FOREIGN_PRETAX_CONCEPTS)):
        # the domestic component is not the total; the plain reading stays, for a filer who tagged
        # the whole of pretax income under the domestic name
        bases.insert(0, (pretax[1] + foreign[1], f"{pretax[0]} + {foreign[0]}"))
    eq = _first(v, EQUITY_METHOD_CONCEPTS) if "IncomeLossFromEquityMethodInvestments" in pretax[0] else None
    lhs_options: list[tuple[float, str]] = []
    for amount, name in bases:
        lhs_options.append((amount - tax[1], f"{name} - {tax[0]}"))
        if eq:
            lhs_options.append((amount - tax[1] + eq[1], f"{name} - {tax[0]} + {eq[0]}"))

    rhs_options: list[tuple[float, str]] = []
    for concept in CONTINUING_ONLY_CONCEPTS:
        if v.get(concept) is not None:
            rhs_options.append((v[concept], concept))
    if v.get("IncomeLossFromContinuingOperations") is not None and (nci := _first(v, NONCONTROLLING_INCOME_CONCEPTS)):
        rhs_options.append(
            (v["IncomeLossFromContinuingOperations"] + nci[1], f"IncomeLossFromContinuingOperations + {nci[0]}")
        )
    disc = _first(v, DISCONTINUED_CONCEPTS)
    for concept in TOTAL_INCOME_CONCEPTS:
        if v.get(concept) is None:
            continue
        if disc:  # discontinued operations sit below the tax line and come off the bottom line first
            rhs_options.append((v[concept] - disc[1], f"{concept} - {disc[0]}"))
        rhs_options.append((v[concept], concept))
    if not rhs_options:
        return []

    for rhs, rhs_name in rhs_options:
        for lhs, lhs_name in lhs_options:
            if _close(lhs, rhs):
                return [_result("IS", "income_after_tax", lhs, rhs, f"{lhs_name} = {rhs_name}")]
    lhs, lhs_name = lhs_options[0]
    rhs, rhs_name = rhs_options[0]
    return [_result("IS", "income_after_tax", lhs, rhs, f"{lhs_name} = {rhs_name}")]


def _eps_close(lhs: float, rhs: float, relative: float = EPS_RELATIVE_TOLERANCE) -> bool:
    return abs(lhs - rhs) <= max(EPS_ABSOLUTE_TOLERANCE, relative * abs(rhs))


def _check_eps(v: dict[str, float]) -> list[CheckResult]:
    """Earnings per share must be the earnings credited to common shareholders over the share count
    the company itself reported. Only runs when the numerator is unambiguous: either the company
    tagged earnings available to common, or it reports no preferred dividends to deduct.

    Each column takes the company's own numerator for THAT column first: diluted earnings can carry
    add-backs (interest on convertible debt) that basic does not, so a diluted EPS checked against
    the basic numerator was off by exactly those."""
    out: list[CheckResult] = []
    for kind, eps_concept, shares_concept in EPS_PAIRS:
        eps, shares = v.get(eps_concept), v.get(shares_concept)
        if eps is None or not shares:
            continue
        own = EPS_NUMERATOR_CONCEPTS if kind == "basic" else tuple(reversed(EPS_NUMERATOR_CONCEPTS))
        numerator = _first(v, own)
        inferred = numerator is None  # the company's own numerator is not tagged: net income stands in
        if numerator is None:
            if _first(v, PREFERRED_DIVIDEND_CONCEPTS):
                continue  # preferred dividends come out first and we cannot see how much
            numerator = _first(v, EPS_FALLBACK_NUMERATOR_CONCEPTS)
            if (
                numerator is not None
                and numerator[0] == "ProfitLoss"
                and (nci := _first(v, NONCONTROLLING_INCOME_CONCEPTS))
            ):
                # the consolidated total is all the filer gave; take the minority's share back out
                numerator = (f"ProfitLoss - {nci[0]}", numerator[1] - nci[1])
        if numerator is None:
            continue
        computed = numerator[1] / shares
        out.append(
            CheckResult(
                "IS",
                f"eps_{kind}_approx" if inferred else f"eps_{kind}",
                _eps_close(computed, eps, EPS_APPROX_RELATIVE_TOLERANCE if inferred else EPS_RELATIVE_TOLERANCE),
                computed,
                eps,
                f"{numerator[0]} / {shares_concept} = {eps_concept}" + (" (numerator inferred)" if inferred else ""),
            )
        )
    return out


def check_cash_flow(v: dict[str, float]) -> list[CheckResult]:
    """The three activities must sum to the net change in cash the filing states.

    Whether the exchange-rate effect is inside that stated total cannot be read off the tag. The IFRS
    `IncreaseDecreaseInCashAndCashEquivalents`, whose name promises it is, failed 19 % of the time
    against 0.6 % for its before-the-effect sibling, and every sampled filing that tags the effect
    separately states the total *before* it, showing the effect on its own line underneath: Spark
    Networks, Valspar, Vale and TDCX all close to the dollar without it and miss by exactly the effect
    with it. So both readings are tried, the one the tag's name promises first.
    """
    out: list[CheckResult] = []
    ops, inv, fin = _first(v, OPERATING_CF), _first(v, INVESTING_CF), _first(v, FINANCING_CF)
    if not (ops and inv and fin):
        return out
    activities = ops[1] + inv[1] + fin[1]
    incl = _first(v, NET_CHANGE_IN_CASH_INCL_FX)
    target = incl or _first(v, NET_CHANGE_IN_CASH_EXCL_FX)
    if target is None:
        return out
    without_fx = (activities, "ops + investing + financing")
    options = [without_fx]
    if fx := _first(v, FX_CONCEPTS):
        with_fx = (activities + fx[1], "ops + investing + financing + fx")
        options = [with_fx, without_fx] if incl else [without_fx, with_fx]
    for lhs, lhs_name in options:
        if _close(lhs, target[1]):
            return [_result("CF", "net_change_in_cash", lhs, target[1], f"{lhs_name} = {target[0]}")]
    lhs, lhs_name = options[0]
    return [_result("CF", "net_change_in_cash", lhs, target[1], f"{lhs_name} = {target[0]}")]


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
