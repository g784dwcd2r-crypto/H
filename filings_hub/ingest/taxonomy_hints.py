"""Fallback classification of XBRL concepts into statements, used only for filings the FSDS has not
covered yet (marked `source = 'facts_fallback'`). Ordered lists give a sensible default line order."""

from __future__ import annotations

IS_ORDER = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
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
    "EarningsPerShareBasic",
    "EarningsPerShareDiluted",
    "WeightedAverageNumberOfSharesOutstandingBasic",
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "CommonStockDividendsPerShareDeclared",
]
BS_ORDER = [
    "CashAndCashEquivalentsAtCarryingValue",
    "RestrictedCashCurrent",
    "ShortTermInvestments",
    "MarketableSecuritiesCurrent",
    "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    "AccountsReceivableNetCurrent",
    "InventoryNet",
    "PrepaidExpenseAndOtherAssetsCurrent",
    "OtherAssetsCurrent",
    "AssetsCurrent",
    "MarketableSecuritiesNoncurrent",
    "PropertyPlantAndEquipmentNet",
    "OperatingLeaseRightOfUseAsset",
    "Goodwill",
    "IntangibleAssetsNetExcludingGoodwill",
    "DeferredIncomeTaxAssetsNet",
    "OtherAssetsNoncurrent",
    "AssetsNoncurrent",
    "Assets",
    "AccountsPayableCurrent",
    "AccruedLiabilitiesCurrent",
    "ContractWithCustomerLiabilityCurrent",
    "DeferredRevenueCurrent",
    "CommercialPaper",
    "LongTermDebtCurrent",
    "OperatingLeaseLiabilityCurrent",
    "OtherLiabilitiesCurrent",
    "LiabilitiesCurrent",
    "LongTermDebtNoncurrent",
    "OperatingLeaseLiabilityNoncurrent",
    "DeferredIncomeTaxLiabilitiesNet",
    "OtherLiabilitiesNoncurrent",
    "LiabilitiesNoncurrent",
    "Liabilities",
    "CommitmentsAndContingencies",
    "TemporaryEquityCarryingAmountAttributableToParent",
    "PreferredStockValue",
    "CommonStockValue",
    "CommonStocksIncludingAdditionalPaidInCapital",
    "AdditionalPaidInCapital",
    "TreasuryStockValue",
    "RetainedEarningsAccumulatedDeficit",
    "AccumulatedOtherComprehensiveIncomeLossNetOfTax",
    "StockholdersEquity",
    "MinorityInterest",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    "LiabilitiesAndStockholdersEquity",
]
CF_ORDER = [
    "NetIncomeLoss",
    "ProfitLoss",
    "DepreciationDepletionAndAmortization",
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
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    "IncomeTaxesPaidNet",
    "InterestPaidNet",
]
CI_ORDER = [
    "NetIncomeLoss",
    "ProfitLoss",
    "OtherComprehensiveIncomeLossForeignCurrencyTransactionAndTranslationAdjustmentNetOfTax",
    "OtherComprehensiveIncomeLossCashFlowHedgeGainLossAfterReclassificationAndTax",
    "OtherComprehensiveIncomeLossAvailableForSaleSecuritiesAdjustmentNetOfTax",
    "OtherComprehensiveIncomeLossNetOfTax",
    "OtherComprehensiveIncomeLossNetOfTaxPortionAttributableToParent",
    "ComprehensiveIncomeNetOfTax",
    "ComprehensiveIncomeNetOfTaxIncludingPortionAttributableToNoncontrollingInterest",
]
EQ_ORDER = [
    "StockholdersEquity",
    "StockIssuedDuringPeriodValueNewIssues",
    "StockIssuedDuringPeriodValueShareBasedCompensation",
    "AdjustmentsToAdditionalPaidInCapitalSharebasedCompensationRequisiteServicePeriodRecognitionValue",
    "StockRepurchasedAndRetiredDuringPeriodValue",
    "TreasuryStockValueAcquiredCostMethod",
    "Dividends",
    "DividendsCommonStock",
    "DividendsCommonStockCash",
    "NetIncomeLoss",
    "OtherComprehensiveIncomeLossNetOfTax",
]

ORDER = {"IS": IS_ORDER, "BS": BS_ORDER, "CF": CF_ORDER, "CI": CI_ORDER, "EQ": EQ_ORDER}
_INDEX = {stmt: {c: i for i, c in enumerate(order)} for stmt, order in ORDER.items()}

CF_PREFIXES = (
    "NetCashProvidedByUsedIn",
    "PaymentsTo",
    "PaymentsFor",
    "PaymentsOf",
    "ProceedsFrom",
    "RepaymentsOf",
    "IncreaseDecreaseIn",
    "CashAndCashEquivalentsPeriodIncreaseDecrease",
    "CashCashEquivalentsRestrictedCash",
    "EffectOfExchangeRate",
    "ShareBasedCompensation",
    "DepreciationDepletionAndAmortization",
    "DepreciationAndAmortization",
    "DeferredIncomeTaxExpenseBenefit",
    "OtherNoncash",
    "IncomeTaxesPaid",
    "InterestPaid",
    "GainLossOnSaleOf",
    "GainLossOnDisposition",
)
CI_PREFIXES = ("OtherComprehensiveIncome", "ComprehensiveIncome")
EQ_PREFIXES = (
    "StockIssuedDuringPeriod",
    "StockRepurchasedDuringPeriod",
    "StockRepurchasedAndRetired",
    "TreasuryStockValueAcquired",
    "Dividends",
    "AdjustmentsToAdditionalPaidInCapital",
    "StockholdersEquityOther",
    "CumulativeEffectOfNewAccountingPrinciple",
)


def classify_concept(concept: str, is_instant: bool) -> str:
    """Statement code for a concept not seen in the company's own FSDS template."""
    for stmt, idx in _INDEX.items():
        if concept in idx and (stmt == "BS") == is_instant:
            return stmt
    if concept.startswith(CI_PREFIXES):
        return "CI"
    if concept.startswith(EQ_PREFIXES):
        return "EQ"
    if concept.startswith(CF_PREFIXES):
        return "CF"
    if is_instant:
        return "BS"
    if concept in _INDEX["IS"]:
        return "IS"
    return "IS"


def default_order(statement: str, concept: str) -> tuple[int, str]:
    return (_INDEX.get(statement, {}).get(concept, 10_000), concept)
