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
}
METRIC_NAMES = tuple(METRICS)

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
    "METRICS",
    "METRIC_NAMES",
    "build_company_metrics",
    "period_metrics",
    "upsert_company_metrics",
]
