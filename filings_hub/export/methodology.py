"""Conservative eligibility for derived flows; reporting a value needs no eligibility test.

This is an explicit release allowlist, separate from ingestion's presentation hints. A monetary
unit or a duration alone does not establish additivity (average balances are monetary durations).
Add concepts here only with a reviewed definition and a numerical regression case.
"""

import re
from typing import Any

ADDITIVE_CONCEPTS = frozenset(
    [
        "Revenues",
        "RevenuesNetOfInterestExpense",
        "Revenue",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "InterestAndDividendIncomeOperating",
        "InterestExpense",
        "InterestIncomeExpenseNet",
        "ProvisionForLoanLeaseAndOtherLosses",
        "InterestIncomeExpenseAfterProvisionForLoanLoss",
        "NoninterestIncome",
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
        "CostOfServices",
        "GrossProfit",
        "ResearchAndDevelopmentExpense",
        "SellingGeneralAndAdministrativeExpense",
        "SellingAndMarketingExpense",
        "GeneralAndAdministrativeExpense",
        "DepreciationDepletionAndAmortization",
        "AmortizationOfIntangibleAssets",
        "RestructuringCharges",
        "GoodwillImpairmentLoss",
        "NoninterestExpense",
        "OperatingExpenses",
        "CostsAndExpenses",
        "OperatingIncomeLoss",
        "InvestmentIncomeInterest",
        "InterestExpenseNonoperating",
        "OtherNonoperatingIncomeExpense",
        "NonoperatingIncomeExpense",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "IncomeTaxExpenseBenefit",
        "IncomeLossFromContinuingOperations",
        "IncomeLossFromDiscontinuedOperationsNetOfTax",
        "ProfitLoss",
        "NetIncomeLossAttributableToNoncontrollingInterest",
        "NetIncomeLoss",
        "PreferredStockDividendsAndOtherAdjustments",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "DepreciationAndAmortization",
        "ShareBasedCompensation",
        "DeferredIncomeTaxExpenseBenefit",
        "OtherNoncashIncomeExpense",
        "IncreaseDecreaseInAccountsReceivable",
        "IncreaseDecreaseInInventories",
        "IncreaseDecreaseInOtherOperatingAssets",
        "IncreaseDecreaseInAccountsPayable",
        "IncreaseDecreaseInContractWithCustomerLiability",
        "IncreaseDecreaseInOtherOperatingLiabilities",
        "NetCashProvidedByUsedInOperatingActivities",
        "PaymentsToAcquireAvailableForSaleSecuritiesDebt",
        "ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities",
        "ProceedsFromSaleOfAvailableForSaleSecuritiesDebt",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireBusinessesNetOfCashAcquired",
        "PaymentsForProceedsFromOtherInvestingActivities",
        "NetCashProvidedByUsedInInvestingActivities",
        "PaymentsRelatedToTaxWithholdingForShareBasedCompensation",
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
        "PaymentsForRepurchaseOfCommonStock",
        "ProceedsFromIssuanceOfLongTermDebt",
        "RepaymentsOfLongTermDebt",
        "ProceedsFromRepaymentsOfCommercialPaper",
        "ProceedsFromPaymentsForOtherFinancingActivities",
        "NetCashProvidedByUsedInFinancingActivities",
        "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "CashAndCashEquivalentsPeriodIncreaseDecrease",
        "IncomeTaxesPaidNet",
        "InterestPaidNet",
        "OtherComprehensiveIncomeLossForeignCurrencyTransactionAndTranslationAdjustmentNetOfTax",
        "OtherComprehensiveIncomeLossCashFlowHedgeGainLossAfterReclassificationAndTax",
        "OtherComprehensiveIncomeLossAvailableForSaleSecuritiesAdjustmentNetOfTax",
        "OtherComprehensiveIncomeLossNetOfTax",
        "OtherComprehensiveIncomeLossNetOfTaxPortionAttributableToParent",
        "ComprehensiveIncomeNetOfTax",
        "ComprehensiveIncomeNetOfTaxIncludingPortionAttributableToNoncontrollingInterest",
    ]
)


def additive_reason(row: dict[str, Any], statement: str) -> str | None:
    """None means eligible; otherwise return the user-visible reason to leave the result blank."""
    if statement not in {"IS", "CF", "CI"}:
        return "Derivation is not supported for this statement."
    concept = row.get("concept") or ""
    if "PerShare" in concept or "WeightedAverage" in concept:
        return "Per-share amounts and weighted averages require a separate method; only reported values are shown."
    if row.get("is_custom") or not re.match(r"^(us-gaap|ifrs-full)(?:/|$)", row.get("taxonomy") or ""):
        return "This taxonomy or company-defined concept has no validated derivation method."
    if concept not in ADDITIVE_CONCEPTS:
        return "This concept has no validated additive derivation method; only reported values are shown."
    if not re.fullmatch(r"[A-Z]{3}", row.get("unit") or ""):
        return (
            "Derivation requires compatible currency flow values; ratios, shares and per-share units are unsupported."
        )
    if not row.get("qtrs"):
        return "Point-in-time balances cannot be added or subtracted as period flows."
    return None
