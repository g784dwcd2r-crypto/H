"""Key numbers per results filing, read straight off the as-reported statements.

Two consumers:
  * the period table on the company page (revenue, net income, diluted EPS per period), computed per
    company at request time from its statements partition;
  * `company_metrics/`: one row per company with its latest annual numbers, for peer lists and ranking.

A metric is the first concept in its priority list that appears on the filing's primary-period
statement; the value is the as-reported one (not the presentation-negated one). No derived numbers.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

import pyarrow as pa
import pyarrow.compute as pc

from filings_hub.ingest.checks import OPERATING_CF, REVENUE_CONCEPTS
from filings_hub.lake import layout
from filings_hub.lake.duck import Duck
from filings_hub.lake.storage import Storage

log = logging.getLogger(__name__)

METRICS: dict[str, tuple[str, tuple[str, ...]]] = {
    # metric: (statement, concepts in priority order)
    "revenue": (
        "IS",
        (
            *REVENUE_CONCEPTS,
            "InterestAndDividendIncomeOperating",  # banks without a total revenue line
            "TotalRevenuesAndOtherIncome",
        ),
    ),
    "net_income": (
        "IS",
        (
            "NetIncomeLoss",
            "ProfitLoss",
            "ProfitLossAttributableToOwnersOfParent",
            "NetIncomeLossAvailableToCommonStockholdersBasic",
            "IncomeLossFromContinuingOperations",
        ),
    ),
    "eps_diluted": (
        "IS",
        ("EarningsPerShareDiluted", "DilutedEarningsLossPerShare", "EarningsPerShareBasicAndDiluted"),
    ),
    "total_assets": ("BS", ("Assets",)),
    "operating_cash_flow": ("CF", OPERATING_CF),
    # wider set for the swappable headline cards; still first-concept-that-appears, never derived
    "gross_profit": ("IS", ("GrossProfit",)),
    "operating_income": ("IS", ("OperatingIncomeLoss",)),
    "pretax_income": (
        "IS",
        (
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        ),
    ),
    "income_tax": ("IS", ("IncomeTaxExpenseBenefit",)),
    "eps_basic": ("IS", ("EarningsPerShareBasic", "EarningsPerShareBasicAndDiluted")),
    "shares_diluted": ("IS", ("WeightedAverageNumberOfDilutedSharesOutstanding",)),
    "net_interest_income": ("IS", ("InterestIncomeExpenseNet", "InterestIncomeExpenseAfterProvisionForLoanLoss")),
    "provision_for_credit_losses": (
        "IS",
        ("ProvisionForLoanLeaseAndOtherLosses", "ProvisionForLoanLossesExpensed", "ProvisionForCreditLosses"),
    ),
    "noninterest_income": ("IS", ("NoninterestIncome",)),
    "cash": (
        "BS",
        ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
    ),
    "total_liabilities": ("BS", ("Liabilities",)),
    "total_equity": (
        "BS",
        ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
    ),
    "long_term_debt": ("BS", ("LongTermDebtNoncurrent", "LongTermDebt")),
    "deposits": ("BS", ("Deposits",)),
    "loans": ("BS", ("LoansAndLeasesReceivableNetReportedAmount", "NotesReceivableNet")),
    "capex": ("CF", ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets")),
    "investing_cash_flow": ("CF", ("NetCashProvidedByUsedInInvestingActivities",)),
    "financing_cash_flow": ("CF", ("NetCashProvidedByUsedInFinancingActivities",)),
    "dividends_paid": ("CF", ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock")),
    "buybacks": ("CF", ("PaymentsForRepurchaseOfCommonStock",)),
    "depreciation": ("CF", ("DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "Depreciation")),
}
METRIC_NAMES = tuple(METRICS)
METRIC_LABELS: dict[str, str] = {
    "revenue": "Revenue",
    "net_income": "Net income",
    "eps_diluted": "Diluted EPS",
    "total_assets": "Total assets",
    "operating_cash_flow": "Operating cash flow",
    "gross_profit": "Gross profit",
    "operating_income": "Operating income",
    "pretax_income": "Pre-tax income",
    "income_tax": "Income tax",
    "eps_basic": "Basic EPS",
    "shares_diluted": "Diluted shares",
    "net_interest_income": "Net interest income",
    "provision_for_credit_losses": "Provision for credit losses",
    "noninterest_income": "Non-interest income",
    "cash": "Cash",
    "total_liabilities": "Total liabilities",
    "total_equity": "Equity",
    "long_term_debt": "Long-term debt",
    "deposits": "Deposits",
    "loans": "Loans",
    "capex": "Capital expenditure",
    "investing_cash_flow": "Investing cash flow",
    "financing_cash_flow": "Financing cash flow",
    "dividends_paid": "Dividends paid",
    "buybacks": "Buybacks",
    "depreciation": "Depreciation and amortisation",
}
# what the headline cards show by default for an industry (SIC prefix -> metrics); banks and insurers
# have no "revenue" line worth the name
HEADLINE_PRESETS: dict[str, list[str]] = {
    "60": ["net_interest_income", "provision_for_credit_losses", "net_income", "total_assets"],  # banks
    "61": ["net_interest_income", "provision_for_credit_losses", "net_income", "total_assets"],  # credit
    "63": ["revenue", "net_income", "total_assets", "total_equity"],  # insurance
    "67": ["revenue", "net_income", "total_assets", "total_equity"],  # holding companies, REITs
}


def headline_preset(sic: str | None) -> list[str]:
    """The default headline cards for an industry code; the generic four otherwise."""
    for prefix, cards in HEADLINE_PRESETS.items():
        if sic and str(sic).startswith(prefix):
            return list(cards)
    return ["revenue", "net_income", "eps_diluted", "operating_cash_flow"]


COMPANY_METRICS_SCHEMA = pa.schema(
    [
        ("cik", pa.int64()),
        ("period_label", pa.string()),
        ("fiscal_year", pa.int32()),
        ("period_end", pa.date32()),
        ("results_accession", pa.string()),
        ("revenue", pa.float64()),
        ("net_income", pa.float64()),
        ("eps_diluted", pa.float64()),
        ("total_assets", pa.float64()),
        ("operating_cash_flow", pa.float64()),
    ]
)


def _values_clause() -> str:
    rows = []
    for metric, (stmt, concepts) in METRICS.items():
        for i, concept in enumerate(concepts):
            rows.append(f"('{metric}', '{stmt}', '{concept}', {i})")
    return ", ".join(rows)


# Portable (DuckDB and Postgres): the priority pick is a row_number in a subquery, not QUALIFY.
METRIC_LINES_SQL = f"""
SELECT accession, metric, value FROM (
    SELECT s.accession, m.metric, s.value,
           row_number() OVER (PARTITION BY s.accession, m.metric ORDER BY m.priority, s.line_order) AS rn
    FROM statements s
    JOIN (VALUES {_values_clause()}) AS m(metric, statement, concept, priority)
      ON m.concept = s.concept AND m.statement = s.statement
    WHERE s.cik = ? AND s.is_primary_period AND NOT s.is_abstract AND s.value IS NOT NULL
      AND NOT s.is_parenthetical
) t WHERE rn = 1
"""


def period_metrics(query, cik: int) -> dict[str, dict[str, float | None]]:
    """{results_accession: {metric: value}} for one company. `query(sql, params)` is Database.query."""
    out: dict[str, dict[str, float | None]] = {}
    for r in query(METRIC_LINES_SQL, [cik]):
        out.setdefault(r["accession"], dict.fromkeys(METRIC_NAMES))[r["metric"]] = r["value"]
    return out


COMPANY_METRICS_SQL = f"""
WITH latest AS (
    SELECT cik, period_label, fiscal_year, period_end, results_accession
    FROM (
        SELECT p.*, row_number() OVER (PARTITION BY cik ORDER BY period_end DESC) AS rn
        FROM periods p WHERE period_type = 'annual' {{cik_filter}}
    ) WHERE rn = 1
),
picked AS (
    SELECT accession, metric, value FROM (
        SELECT s.accession, m.metric, s.value,
               row_number() OVER (PARTITION BY s.accession, m.metric ORDER BY m.priority, s.line_order) AS rn
        FROM statements s
        JOIN (VALUES {_values_clause()}) AS m(metric, statement, concept, priority)
          ON m.concept = s.concept AND m.statement = s.statement
        WHERE s.accession IN (SELECT results_accession FROM latest)
          AND s.is_primary_period AND NOT s.is_abstract AND s.value IS NOT NULL AND NOT s.is_parenthetical
    ) WHERE rn = 1
)
SELECT l.cik, l.period_label, l.fiscal_year, l.period_end, l.results_accession,
       max(CASE WHEN metric = 'revenue' THEN value END) AS revenue,
       max(CASE WHEN metric = 'net_income' THEN value END) AS net_income,
       max(CASE WHEN metric = 'eps_diluted' THEN value END) AS eps_diluted,
       max(CASE WHEN metric = 'total_assets' THEN value END) AS total_assets,
       max(CASE WHEN metric = 'operating_cash_flow' THEN value END) AS operating_cash_flow
FROM latest l LEFT JOIN picked p ON p.accession = l.results_accession
GROUP BY ALL
ORDER BY l.cik
"""


def _company_metrics_rows(duck: Duck, ciks: Iterable[int] | None = None) -> pa.Table:
    views = duck.create_views()
    if not (views["periods"] and views["statements"]):
        return COMPANY_METRICS_SCHEMA.empty_table()
    if ciks is None:
        sql, params = COMPANY_METRICS_SQL.format(cik_filter=""), []
    else:
        sql = COMPANY_METRICS_SQL.format(cik_filter="AND cik IN (SELECT unnest(?::BIGINT[]))")
        params = [sorted(set(ciks))]
    return duck.fetch_arrow(sql, params).select(COMPANY_METRICS_SCHEMA.names).cast(COMPANY_METRICS_SCHEMA)


def build_company_metrics(storage: Storage) -> int:
    """Rebuild company_metrics/ from scratch (backfill)."""
    duck = Duck(storage)
    try:
        table = _company_metrics_rows(duck)
    finally:
        duck.close()
    storage.write_parquet(layout.COMPANY_METRICS, table)
    log.info("company_metrics: %d companies", table.num_rows)
    return table.num_rows


def upsert_company_metrics(storage: Storage, ciks: Iterable[int]) -> int:
    """Refresh path: recompute the touched companies only and merge into the existing table."""
    cik_set = set(ciks)
    if not cik_set:
        return 0
    if not storage.exists(layout.COMPANY_METRICS):
        return build_company_metrics(storage)
    duck = Duck(storage)
    try:
        fresh = _company_metrics_rows(duck, cik_set)
    finally:
        duck.close()
    existing = storage.read_parquet(layout.COMPANY_METRICS)
    mask = pc.invert(pc.is_in(existing.column("cik"), value_set=pa.array(sorted(cik_set), pa.int64())))
    keep = existing.filter(mask)
    merged = pa.concat_tables([keep.cast(COMPANY_METRICS_SCHEMA), fresh]).sort_by("cik")
    storage.write_parquet(layout.COMPANY_METRICS, merged)
    return fresh.num_rows


__all__ = [
    "COMPANY_METRICS_SCHEMA",
    "HEADLINE_PRESETS",
    "METRICS",
    "METRIC_LABELS",
    "METRIC_NAMES",
    "build_company_metrics",
    "headline_preset",
    "period_metrics",
    "upsert_company_metrics",
]
