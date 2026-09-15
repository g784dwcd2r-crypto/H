"""As-reported statements.

Primary path (source='fsds'): join FSDS `pre` (structure) x `num` (values) x `tag` (labels/attributes) per
filing, keep the company's own line order and labels, flag the filing's primary period column, detect
subtotals, run arithmetic checks and write `statements/cik={cik}/fsds_{quarter}_*.parquet`.

Fallback path (source='facts_fallback'): for filings the FSDS has not covered yet (it lags up to ~3
months), build the same rows from `facts`, using the company's latest FSDS-covered filing of the same
kind as a template for line order/labels, and taxonomy hints for anything new.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from typing import Any

import pyarrow as pa

from filings_hub.ingest import checks as chk
from filings_hub.ingest.periods import form_family, is_amendment
from filings_hub.ingest.sync_universe import FINANCIAL_REPORT_FORMS
from filings_hub.ingest.taxonomy_hints import classify_concept, default_order
from filings_hub.lake import layout
from filings_hub.lake.duck import Duck
from filings_hub.lake.storage import Storage

log = logging.getLogger(__name__)

STATEMENT_NAMES = {
    "IS": "Income Statement",
    "BS": "Balance Sheet",
    "CF": "Cash Flow",
    "EQ": "Equity",
    "CI": "Comprehensive Income",
    "CP": "Cover Page",
    "UN": "Unclassified",
    "SI": "Schedule of Investments",
}
CORE_STATEMENTS = ("IS", "BS", "CF", "EQ", "CI")

STATEMENTS_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("cik", pa.int64()),
        ("statement", pa.string()),
        ("report", pa.int32()),
        ("line", pa.int32()),
        ("line_order", pa.int32()),
        ("is_parenthetical", pa.bool_()),
        ("concept", pa.string()),
        ("taxonomy", pa.string()),
        # axis=member pairs from the data sets, e.g. "ProductOrService=DepositAccount;". Empty for a
        # line total. A line's identity is the concept PLUS this: the same tag broken out by product
        # or share class is several lines, not one.
        ("segments", pa.string()),
        ("label", pa.string()),
        ("standard_label", pa.string()),
        ("negating", pa.bool_()),
        ("is_abstract", pa.bool_()),
        ("is_custom", pa.bool_()),
        ("iord", pa.string()),
        ("crdr", pa.string()),
        ("datatype", pa.string()),
        ("period_start", pa.date32()),
        ("period_end", pa.date32()),
        ("period_end_rounded", pa.date32()),
        ("qtrs", pa.int32()),
        ("unit", pa.string()),
        ("value", pa.float64()),
        ("value_presented", pa.float64()),
        ("is_primary_period", pa.bool_()),
        ("is_subtotal", pa.bool_()),
        ("parent_concept", pa.string()),
        ("source", pa.string()),
        ("fsds_quarter", pa.string()),
        ("form", pa.string()),
        ("filed_date", pa.date32()),
        ("checks_passed", pa.bool_()),
    ]
)

CHECKS_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("cik", pa.int64()),
        ("statement", pa.string()),
        ("check_name", pa.string()),
        ("passed", pa.bool_()),
        ("lhs", pa.float64()),
        ("rhs", pa.float64()),
        ("difference", pa.float64()),
        ("detail", pa.string()),
        ("source", pa.string()),
    ]
)

MACROS = """
CREATE OR REPLACE MACRO month_end_round(d) AS
  CASE WHEN d IS NULL THEN NULL
       WHEN day(d) <= 15 THEN (d - to_days(day(d)))::DATE
       ELSE last_day(d) END;
CREATE OR REPLACE MACRO expected_qtrs(fp, form) AS
  CASE WHEN form LIKE '10-KT%' OR form LIKE '10-QT%' THEN NULL
       WHEN fp = 'FY' THEN [4] WHEN fp = 'Q1' THEN [1] WHEN fp = 'Q2' THEN [1, 2] WHEN fp = 'Q3' THEN [1, 3]
       ELSE NULL END;
"""


def _sql_list(values) -> str:
    return ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)


def _subtotal_sql(concept: str, label: str, is_abstract: str) -> str:
    return (
        f"(NOT {is_abstract} AND ({concept} IN ({_sql_list(sorted(chk.SUBTOTAL_CONCEPTS))}) "
        f"OR regexp_matches({label}, '{chk.SUBTOTAL_LABEL_REGEX}', 'i')))"
    )


# ---------------------------------------------------------------------------------------------
# FSDS path
# ---------------------------------------------------------------------------------------------
FX_INDEX_SQL = """
SELECT accession, concept, unit, month_end_round(period_end) AS pe_r, period_start, period_end,
       CASE WHEN period_start IS NULL THEN 0
            ELSE greatest(1, round(duration_days / 91.0)::INTEGER) END AS qtrs_est
FROM facts
{where}
QUALIFY row_number() OVER (PARTITION BY accession, concept, unit, pe_r, qtrs_est ORDER BY filed DESC) = 1
"""


def build_fx_index(duck: Duck) -> bool:
    """Materialise the facts -> exact-period lookup once, for every quarter of a build.

    The FSDS carries only month-end-rounded dates; exact 52/53-week period starts and ends come from
    `facts`. Doing that lookup per quarter meant one full scan of the facts lake (~100M rows) for each
    of ~68 quarters. Built once into `fx_index`, each quarter is then a keyed lookup.
    """
    duck.sql(MACROS)
    if not duck.view("facts", f"{layout.FACTS}/*/*.parquet"):
        return False
    duck.sql("CREATE OR REPLACE TABLE fx_index AS " + FX_INDEX_SQL.format(where=""))
    return True


def _stage_fsds_quarter(duck: Duck, quarter: str, enrich: bool, fx_index: bool = False) -> int:
    """Stage one FSDS quarter into temp table `stg` with every derived column except checks_passed.

    `fx_index`: the lookup was already built for the whole run by `build_fx_index`."""
    duck.sql(MACROS)
    if fx_index:
        duck.sql(
            "CREATE OR REPLACE TEMP TABLE fx AS SELECT * FROM fx_index "
            "WHERE accession IN (SELECT adsh FROM fsds_sub WHERE quarter = ?)",
            [quarter],
        )
    elif enrich and duck.view("facts", f"{layout.FACTS}/*/*.parquet"):
        duck.sql(
            "CREATE OR REPLACE TEMP TABLE fx AS "
            + FX_INDEX_SQL.format(where="WHERE accession IN (SELECT adsh FROM fsds_sub WHERE quarter = ?)"),
            [quarter],
        )
    else:
        duck.sql(
            "CREATE OR REPLACE TEMP TABLE fx (accession VARCHAR, concept VARCHAR, unit VARCHAR, pe_r DATE, "
            "period_start DATE, period_end DATE, qtrs_est INTEGER)"
        )

    duck.sql(
        f"""
        CREATE OR REPLACE TEMP TABLE stg AS
        WITH s AS (
            SELECT adsh, cik, form, period, fy, fp, filed, expected_qtrs(fp, form) AS exp_q
            FROM fsds_sub WHERE quarter = ?
        ),
        p AS (SELECT * FROM fsds_pre WHERE quarter = ?),
        t AS (
            SELECT * FROM fsds_tag WHERE quarter = ?
            QUALIFY row_number() OVER (PARTITION BY tag, version ORDER BY abstract DESC NULLS LAST, tlabel) = 1
        ),
        -- A statement line takes the total: no co-registrant, no axis breakdown. But some filings
        -- report a tag ONLY broken out -- Triumph Financial's fee income is three product lines with
        -- no total -- and taking totals only made those lines vanish from the statement. So: totals
        -- where the filing has them, the breakdown where it has nothing else. (Quarters loaded before
        -- the `dimensional` column existed hold totals only, hence the coalesce.)
        n AS (
            SELECT * EXCLUDE (has_total) FROM (
                SELECT *, max(CASE WHEN NOT coalesce(dimensional, false) THEN 1 ELSE 0 END)
                            OVER (PARTITION BY adsh, tag, version) AS has_total
                FROM fsds_num WHERE quarter = ? AND coreg IS NULL
            )
            WHERE CASE WHEN has_total = 1 THEN NOT coalesce(dimensional, false) ELSE TRUE END
        ),
        base AS (
            SELECT p.adsh AS accession, s.cik, p.stmt AS statement, p.report, p.line,
                   coalesce(p.inpth, 0) = 1 AS is_parenthetical,
                   p.tag AS concept, p.version AS taxonomy, p.plabel AS label, t.tlabel AS standard_label,
                   coalesce(p.negating, 0) = 1 AS negating, coalesce(t.abstract, 0) = 1 AS is_abstract,
                   coalesce(t.custom, 0) = 1 AS is_custom, t.iord, t.crdr, t.datatype,
                   n.ddate AS period_end_rounded, n.qtrs, coalesce(n.segments, '') AS segments,
                   -- FSDS commonly stores perShare facts with currency-only UOM. Restore the
                   -- denominator before the Company Facts join, otherwise 52/53-week EPS dates
                   -- cannot match USD/shares contexts and silently fall back to calendar dates.
                   CASE WHEN regexp_matches(lower(t.datatype), '(^|:)pershare(itemtype)?$')
                             AND regexp_full_match(n.uom, '[A-Z]{{3}}')
                        THEN n.uom || '/shares' ELSE n.uom END AS unit, n.value,
                   s.period AS filing_period, s.form, s.filed AS filed_date, s.exp_q
            FROM p JOIN s USING (adsh)
            LEFT JOIN t ON t.tag = p.tag AND t.version = p.version
            LEFT JOIN n ON n.adsh = p.adsh AND n.tag = p.tag AND n.version = p.version
        ),
        -- A foreign filer often prints its statements in its home currency with a "convenience
        -- translation" into dollars beside them, and the data sets carry both: the same tag, date and
        -- line twice, in two units (net income in HK$ and in US$, 7.8x apart). Left in, the page shows
        -- whichever row came first and a check compares a renminbi revenue with a dollar cost. A
        -- statement is kept in ONE currency: the one most of its lines are reported in (by distinct
        -- tags, then rows; USD, then alphabetical, break a tie). Non-monetary units (shares, pure) are
        -- untouched and a per-share unit follows its currency prefix. `reporting_currency` is the same
        -- rule for the provisional path.
        currency AS (
            SELECT accession, ccy FROM (
                SELECT accession, regexp_extract(unit, '^([A-Z]{{3}})', 1) AS ccy,
                       count(DISTINCT concept) AS n_tags, count(*) AS n_rows
                FROM base
                WHERE value IS NOT NULL AND regexp_matches(unit, '^[A-Z]{{3}}(/shares)?$')
                GROUP BY 1, 2
            )
            QUALIFY row_number() OVER (
                PARTITION BY accession ORDER BY n_tags DESC, n_rows DESC, (ccy = 'USD') DESC, ccy
            ) = 1
        ),
        kept AS (
            -- Which value belongs on a line is decided by the concept, not by the statement it sits on:
            -- `tag.iord` says whether it is an instant ('I', reported with qtrs = 0) or a duration
            -- ('D', qtrs > 0). Selecting by statement instead dropped every instant presented on the
            -- cash flow statement -- the cash reconciliation lines are instants -- and let an equity
            -- line take both its closing balance and the year's movement as "the" value.
            -- A custom tag with no `tag` row (iord IS NULL) falls back to what the statement expects.
            SELECT b.* FROM base b
            LEFT JOIN currency c USING (accession)
            WHERE (period_end_rounded IS NULL
               OR (iord = 'I' AND qtrs = 0)
               OR (iord = 'D' AND qtrs > 0 AND (exp_q IS NULL OR list_contains(exp_q, qtrs)))
               OR (iord IS NULL AND (
                       (statement = 'BS' AND qtrs = 0)
                    OR (statement <> 'BS' AND qtrs = 0)
                    OR (statement <> 'BS' AND qtrs > 0 AND (exp_q IS NULL OR list_contains(exp_q, qtrs)))
               )))
              -- one currency per statement (see `currency`); a row without a value passes through
              AND (b.value IS NULL OR c.ccy IS NULL
                   OR NOT regexp_matches(b.unit, '^[A-Z]{{3}}(/shares)?$')
                   OR regexp_extract(b.unit, '^([A-Z]{{3}})', 1) = c.ccy)
        ),
        missing AS (
            -- lines whose only values were filtered out keep an empty row so the structure stays intact
            SELECT accession, cik, statement, report, line, is_parenthetical, concept, taxonomy, label,
                   standard_label, negating, is_abstract, is_custom, iord, crdr, datatype,
                   NULL::DATE AS period_end_rounded, NULL::INTEGER AS qtrs, '' AS segments, NULL::VARCHAR AS unit,
                   NULL::DOUBLE AS value, filing_period, form, filed_date, exp_q
            FROM base b
            WHERE NOT EXISTS (
                SELECT 1 FROM kept k WHERE k.accession = b.accession AND k.statement = b.statement
                  AND k.report = b.report AND k.line = b.line
            )
            QUALIFY row_number() OVER (PARTITION BY accession, statement, report, line ORDER BY period_end_rounded) = 1
        ),
        rows_ AS (SELECT * FROM kept UNION ALL SELECT * FROM missing),
        enriched AS (
            SELECT r.*, fx.period_start AS fact_start, fx.period_end AS fact_end
            FROM rows_ r
            LEFT JOIN fx ON fx.accession = r.accession AND fx.concept = r.concept AND fx.unit = r.unit
                        AND fx.pe_r = r.period_end_rounded AND fx.qtrs_est = coalesce(r.qtrs, 0)
        ),
        derived AS (
            SELECT *,
                dense_rank() OVER (
                    PARTITION BY accession, statement, is_parenthetical ORDER BY report, line, segments) AS line_order,
                -- the filing's own column is the shortest duration it reports at the balance-sheet
                -- date (the quarter on a Q2 income statement, not the year to date); instants are
                -- excluded from the minimum so they cannot drag it to zero
                min(CASE WHEN period_end_rounded = filing_period AND qtrs > 0 THEN qtrs END)
                    OVER (PARTITION BY accession, statement, is_parenthetical) AS primary_qtrs,
                {_subtotal_sql("concept", "coalesce(label, '')", "is_abstract")} AS is_subtotal
            FROM enriched
        ),
        paired AS (
            -- `pre` gives no dates, so a concept presented twice as an instant -- the "beginning
            -- balances" and "ending balances" lines of a cash flow or equity statement -- joins to
            -- every instant value the filing reports, and both lines would then show the closing
            -- balance. Pair them by position instead: the first such line takes the opening instant
            -- (the filing's own period start), the rest take the period end.
            SELECT *,
                count(DISTINCT CASE WHEN qtrs = 0 THEN line_order END) OVER concept_lines AS instant_lines,
                dense_rank() OVER (
                    PARTITION BY accession, statement, is_parenthetical, concept, segments, qtrs ORDER BY line_order
                ) AS instant_line_rank,
                last_day(filing_period - to_months(coalesce(primary_qtrs, 4) * 3)) AS opening_period
            FROM derived
            WINDOW concept_lines AS (PARTITION BY accession, statement, is_parenthetical, concept, segments)
        ),
        with_primary AS (
            SELECT *,
                CASE WHEN period_end_rounded IS NULL THEN TRUE
                     WHEN qtrs = 0 AND instant_lines > 1 AND instant_line_rank = 1
                         THEN period_end_rounded = opening_period
                     WHEN qtrs = 0 THEN period_end_rounded = filing_period
                     ELSE period_end_rounded = filing_period AND qtrs = primary_qtrs END AS is_primary_period
            FROM paired
        ),
        line_keys AS (
            SELECT DISTINCT accession, statement, is_parenthetical, line_order, concept, is_subtotal FROM with_primary
        ),
        parents AS (
            SELECT accession, statement, is_parenthetical, line_order,
                   min(CASE WHEN is_subtotal THEN line_order END) OVER (
                       PARTITION BY accession, statement, is_parenthetical ORDER BY line_order
                       ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING) AS parent_order
            FROM line_keys
        ),
        parent_concepts AS (
            SELECT p.accession, p.statement, p.is_parenthetical, p.line_order, k.concept AS parent_concept
            FROM parents p
            LEFT JOIN line_keys k ON k.accession = p.accession AND k.statement = p.statement
                 AND k.is_parenthetical = p.is_parenthetical AND k.line_order = p.parent_order
        )
        SELECT w.accession, w.cik, w.statement, w.report::INTEGER AS report, w.line::INTEGER AS line,
               w.line_order::INTEGER AS line_order, w.is_parenthetical, w.concept, w.taxonomy,
               nullif(w.segments, '') AS segments, w.label,
               w.standard_label, w.negating, w.is_abstract, w.is_custom, w.iord, w.crdr, w.datatype,
               coalesce(w.fact_start,
                        CASE WHEN w.qtrs > 0
                             THEN (date_trunc('month', w.period_end_rounded) - to_months(w.qtrs * 3 - 1))::DATE END
               ) AS period_start,
               coalesce(w.fact_end, w.period_end_rounded) AS period_end,
               w.period_end_rounded, w.qtrs::INTEGER AS qtrs, w.unit, w.value,
               CASE WHEN w.negating THEN -w.value ELSE w.value END AS value_presented,
               w.is_primary_period, w.is_subtotal, pc.parent_concept,
               'fsds' AS source, ? AS fsds_quarter, w.form, w.filed_date
        FROM with_primary w
        LEFT JOIN parent_concepts pc ON pc.accession = w.accession AND pc.statement = w.statement
             AND pc.is_parenthetical = w.is_parenthetical AND pc.line_order = w.line_order
        """,
        [quarter, quarter, quarter, quarter, quarter],
    )
    return duck.fetch_value("SELECT count(*) FROM stg")


def _checks_from_staged(duck: Duck, source: str) -> pa.Table:
    """Run Python arithmetic checks on the primary-period values in `stg`."""
    pivot = duck.fetch_arrow(
        f"""
        -- the value as filed: the checks are written for it (costs positive, cash-flow activities
        -- signed; see checks.py). The presented sign was tried and broke ~60k checks: a cost shown
        -- as (cost) is still a positive cost to subtract, and one fact shown negated on one statement
        -- and plain on another is still one number. arg_max picks the latest-dated value, so an
        -- instant reported at both ends of a period (cash on the cash-flow statement) is the END one.
        SELECT accession, cik, statement, concept,
               arg_max(value, period_end_rounded) AS value
        FROM stg
        WHERE is_primary_period AND NOT is_parenthetical AND value IS NOT NULL
          AND coalesce(segments, '') = ''
          AND statement IN ('BS', 'IS', 'CF') AND concept IN ({_sql_list(sorted(chk.CHECK_CONCEPTS))})
        GROUP BY 1, 2, 3, 4
        """
    )
    groups: dict[tuple[str, int], dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for r in pivot.to_pylist():
        groups[(r["accession"], r["cik"])][r["statement"]][r["concept"]] = r["value"]
    rows = []
    for (acc, cik), by_statement in groups.items():
        for res in chk.run_filing_checks(by_statement):
            rows.append(
                {
                    "accession": acc,
                    "cik": cik,
                    "statement": res.statement,
                    "check_name": res.check_name,
                    "passed": res.passed,
                    "lhs": res.lhs,
                    "rhs": res.rhs,
                    "difference": res.difference,
                    "detail": res.detail,
                    "source": source,
                }
            )
    return pa.Table.from_pylist(rows, schema=CHECKS_SCHEMA)


def _delete_glob(storage: Storage, pattern: str) -> int:
    n = 0
    for p in storage.glob(pattern):
        storage.delete(p)
        n += 1
    return n


def existing_fallbacks(storage: Storage) -> list[str]:
    """Lake paths of every provisional (fallback) statements/checks file."""
    return storage.glob(f"{layout.STATEMENTS}/*/fallback_*.parquet") + storage.glob(
        f"{layout.STATEMENT_CHECKS}/*/fallback_*.parquet"
    )


def build_fsds_quarter(
    storage: Storage,
    quarter: str,
    duck: Duck | None = None,
    enrich: bool = True,
    fallbacks: list[str] | None = None,
    fx_index: bool = False,
) -> dict[str, int]:
    """Build statements for every filing in one FSDS quarter (idempotent per quarter).

    `fallbacks`: pre-listed provisional files (see `existing_fallbacks`); listed here when None."""
    own = duck is None
    duck = duck or Duck(storage)
    try:
        for t in ("sub", "num", "pre", "tag"):
            if not duck.view(f"fsds_{t}", f"{layout.FSDS}/{t}/*/*.parquet"):
                raise RuntimeError(f"FSDS table {t} not loaded")
        n_rows = _stage_fsds_quarter(duck, quarter, enrich, fx_index)
        checks = _checks_from_staged(duck, "fsds")
        duck.register("chk", checks)
        duck.sql(
            """
            CREATE OR REPLACE TEMP TABLE chk_summary AS
            SELECT accession, statement, bool_and(passed) AS checks_passed FROM chk GROUP BY 1, 2
            """
        )
        # remove the previous build of this quarter and the fallbacks it supersedes
        _delete_glob(storage, f"{layout.STATEMENTS}/*/fsds_{quarter}_*.parquet")
        _delete_glob(storage, f"{layout.STATEMENT_CHECKS}/*/fsds_{quarter}_*.parquet")
        covered = set(duck.fetch_column("SELECT DISTINCT accession FROM stg"))
        removed = 0
        for p in existing_fallbacks(storage) if fallbacks is None else fallbacks:
            acc = p.rsplit("/", 1)[-1][len("fallback_") : -len(".parquet")]
            if acc in covered and storage.exists(p):
                storage.delete(p)
                removed += 1

        storage.mkdirs(layout.STATEMENTS)
        storage.mkdirs(layout.STATEMENT_CHECKS)
        duck.sql(
            f"""
            COPY (
                SELECT s.*, c.checks_passed
                FROM stg s LEFT JOIN chk_summary c USING (accession, statement)
                ORDER BY cik, accession, statement, is_parenthetical, line_order, period_end, qtrs
            ) TO '{duck.path(layout.STATEMENTS)}'
            (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (cik), APPEND, FILENAME_PATTERN 'fsds_{quarter}_{{uuid}}')
            """
        )
        if checks.num_rows:
            duck.sql(
                f"""
                COPY (SELECT * FROM chk ORDER BY cik, accession, statement, check_name)
                TO '{duck.path(layout.STATEMENT_CHECKS)}'
                (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (cik), APPEND,
                 FILENAME_PATTERN 'fsds_{quarter}_{{uuid}}')
                """
            )
        duck.unregister("chk")
        n_filings = len(covered)
        log.info(
            "statements %s: %d rows, %d filings, %d checks, %d fallbacks superseded",
            quarter,
            n_rows,
            n_filings,
            checks.num_rows,
            removed,
        )
        return {
            "rows": n_rows,
            "filings": n_filings,
            "checks": checks.num_rows,
            "fallbacks_removed": removed,
        }
    finally:
        if own:
            duck.close()


def built_quarters(storage: Storage) -> set[str]:
    out = set()
    for p in storage.glob(f"{layout.STATEMENTS}/*/fsds_*.parquet"):
        name = p.rsplit("/", 1)[-1]
        out.add(name.split("_")[1])
    return out


def build_all_fsds(
    storage: Storage, quarters: list[str] | None = None, force: bool = False, enrich: bool = True
) -> list[str]:
    from filings_hub.ingest.fsds import loaded_quarters

    have = loaded_quarters(storage)
    done = built_quarters(storage)
    todo = [q for q in (quarters or have) if q in have and (force or q not in done)]
    if not todo:
        return todo
    duck = Duck(storage)
    fallbacks = existing_fallbacks(storage)
    try:
        for t in ("sub", "num", "pre", "tag"):
            duck.view(f"fsds_{t}", f"{layout.FSDS}/{t}/*/*.parquet")
        # one pass over the facts lake for the whole run rather than one per quarter
        indexed = enrich and len(todo) > 1 and build_fx_index(duck)
        for q in todo:
            build_fsds_quarter(storage, q, duck, enrich, fallbacks, fx_index=indexed)
    finally:
        duck.close()
    return todo


# ---------------------------------------------------------------------------------------------
# Fallback path (facts -> provisional statements)
# ---------------------------------------------------------------------------------------------
def month_end_round(d: date | None) -> date | None:
    if d is None:
        return None
    if d.day <= 15:
        first = d.replace(day=1)
        from datetime import timedelta

        return first - timedelta(days=1)
    import calendar

    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def expected_qtrs(fiscal_quarter: int | None, form: str) -> set[int] | None:
    if form.upper().startswith(("10-KT", "10-QT")) or fiscal_quarter is None:
        return None
    return {4: {4}, 1: {1}, 2: {1, 2}, 3: {1, 3}}.get(fiscal_quarter)


def _qtrs_est(duration_days: int | None) -> int:
    if duration_days is None:
        return 0
    return max(1, round(duration_days / 91.0))


def _keep_period(statement: str, qtrs: int, exp: set[int] | None) -> bool:
    """Whether a fact of this duration belongs on this statement.

    An instant (qtrs == 0) is kept on every statement: the cash flow and equity statements present
    opening and closing balances, which are points in time. Only the balance sheet is instants-only.
    """
    if qtrs == 0:
        return True
    if statement == "BS":
        return False
    return exp is None or qtrs in exp


_MONETARY_UNIT = re.compile(r"^([A-Z]{3})(/shares)?$")


def reporting_currency(units: Iterable[tuple[str, str | None]]) -> str | None:
    """The one currency a filing's statements are kept in, from (concept, unit) pairs: the currency
    reported on the most distinct concepts, then on the most rows; USD, then alphabetical, break a
    tie. None when nothing is monetary. The same rule as the `currency` CTE in `_stage_fsds_quarter`,
    for the provisional path: a foreign filer's dollar convenience translation must not become a
    second value on a line, in either path."""
    tags: dict[str, set[str]] = defaultdict(set)
    rows: dict[str, int] = defaultdict(int)
    for concept, unit in units:
        m = _MONETARY_UNIT.match(unit or "")
        if m:
            tags[m.group(1)].add(concept)
            rows[m.group(1)] += 1
    if not rows:
        return None
    return min(rows, key=lambda c: (-len(tags[c]), -rows[c], c != "USD", c))


def in_currency(unit: str | None, ccy: str) -> bool:
    """True for a non-monetary unit, or a monetary one in `ccy` (a per-share unit by its prefix)."""
    m = _MONETARY_UNIT.match(unit or "")
    return m is None or m.group(1) == ccy


def build_fallback_rows(
    cik: int,
    accession: str,
    form: str,
    filed_date: date,
    report_date: date,
    fiscal_quarter: int | None,
    facts: list[dict[str, Any]],
    template: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pure function: (statement rows, check rows) for one filing from its facts.

    `template`: distinct lines (statement, is_parenthetical, line_order, concept, label, negating,
    is_abstract, standard_label, taxonomy) of the company's latest FSDS-covered filing of the same kind.
    """
    filing_period = month_end_round(report_date)
    exp = expected_qtrs(fiscal_quarter, form)
    by_concept: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in facts:
        if f["taxonomy"] == "dei":
            continue
        by_concept[f["concept"]].append(f)
    # one currency per filing, as the FSDS path does (see `reporting_currency`)
    ccy = reporting_currency(
        (c, f.get("unit")) for c, fs in by_concept.items() for f in fs if f.get("value") is not None
    )
    if ccy:
        for concept, fs in list(by_concept.items()):
            by_concept[concept] = [f for f in fs if in_currency(f.get("unit"), ccy)]

    def fact_rows(concept: str, statement: str) -> list[dict[str, Any]]:
        out = []
        for f in by_concept.get(concept, []):
            q = _qtrs_est(f.get("duration_days"))
            if not _keep_period(statement, q, exp):
                continue
            out.append(
                {
                    "period_start": f["period_start"],
                    "period_end": f["period_end"],
                    "period_end_rounded": month_end_round(f["period_end"]),
                    "qtrs": q,
                    "unit": f["unit"],
                    "value": f["value"],
                    "fact_label": f.get("label"),
                    "taxonomy": f["taxonomy"],
                }
            )
        return out

    lines: dict[tuple[str, bool], list[dict[str, Any]]] = defaultdict(list)
    used: set[str] = set()
    # a template line without a statement or a position cannot be placed: the FSDS `pre` table
    # occasionally leaves both blank, and sorting None against a string crashed a whole backfill
    template = [t for t in template or [] if t.get("statement") and t.get("line_order") is not None]
    if template:
        ordered = sorted(template, key=lambda t: (t["statement"], bool(t["is_parenthetical"]), t["line_order"]))
        # How many lines of a statement carry each concept. A cash flow or equity statement presents the
        # same concept twice, as opening and closing balances, and each line takes its own instant --
        # filling both from the whole fact set would print the closing balance on the opening line.
        repeats: dict[tuple[str, bool, str], int] = defaultdict(int)
        for t in ordered:
            if not t["is_abstract"]:
                repeats[(t["statement"], bool(t["is_parenthetical"]), t["concept"])] += 1
        seen: dict[tuple[str, bool, str], int] = defaultdict(int)
        for t in ordered:
            key = (t["statement"], bool(t["is_parenthetical"]))
            if t["is_abstract"]:
                lines[key].append({**t, "values": []})
                continue
            vals = fact_rows(t["concept"], t["statement"])
            concept_key = (*key, t["concept"])
            pinned = False
            if repeats[concept_key] > 1:
                instants = sorted((v for v in vals if v["qtrs"] == 0), key=lambda v: v["period_end"])
                if len(instants) >= repeats[concept_key]:
                    # oldest instant to the first line, newest to the last
                    offset = len(instants) - repeats[concept_key]
                    vals = [instants[offset + seen[concept_key]]]
                    pinned = True
            seen[concept_key] += 1
            if not vals:
                continue
            used.add(t["concept"])
            lines[key].append({**t, "values": vals, "pinned": pinned})
    # concepts reported in this filing but not in the template
    extras: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for concept, fs in by_concept.items():
        if concept in used:
            continue
        is_instant = all(f["period_start"] is None for f in fs)
        statement = classify_concept(concept, is_instant)
        vals = fact_rows(concept, statement)
        if not vals:
            continue
        extras[statement].append(
            {
                "statement": statement,
                "is_parenthetical": False,
                "concept": concept,
                "label": fs[0].get("label") or concept,
                "standard_label": fs[0].get("label"),
                "negating": False,
                "is_abstract": False,
                "taxonomy": fs[0]["taxonomy"],
                "values": vals,
            }
        )
    for statement, items in extras.items():
        items.sort(key=lambda i: default_order(statement, i["concept"]))
        lines[(statement, False)].extend(items)

    stmt_rows: list[dict[str, Any]] = []
    check_rows: list[dict[str, Any]] = []
    by_statement: dict[str, dict[str, float]] = {}
    for (statement, parenthetical), items in lines.items():
        # drop trailing/leading abstract headers with nothing under them
        cleaned: list[dict[str, Any]] = []
        for i, it in enumerate(items):
            if it["is_abstract"]:
                nxt = items[i + 1] if i + 1 < len(items) else None
                if nxt is None or nxt["is_abstract"]:
                    continue
            cleaned.append(it)
        for order, it in enumerate(cleaned, 1):
            it["line_order"] = order
            it["is_subtotal"] = chk.is_subtotal(it["concept"], it.get("label"), it["is_abstract"])
        chk.assign_parents(cleaned)
        # the filing's own column is the shortest *duration* it reports at the balance-sheet date;
        # instants are excluded so they cannot drag the minimum to zero and unset every duration row
        primary_qtrs = min(
            (
                v["qtrs"]
                for it in cleaned
                for v in it["values"]
                if v["period_end_rounded"] == filing_period and v["qtrs"] > 0
            ),
            default=None,
        )
        primary_values: dict[str, float] = {}
        for it in cleaned:
            base = {
                "accession": accession,
                "cik": cik,
                "statement": statement,
                "report": None,
                "line": it["line_order"],
                "line_order": it["line_order"],
                "is_parenthetical": parenthetical,
                "concept": it["concept"],
                "taxonomy": it.get("taxonomy"),
                "segments": None,  # companyfacts publishes undimensioned facts only
                "label": it.get("label") or it["concept"],
                "standard_label": it.get("standard_label"),
                "negating": bool(it.get("negating")),
                "is_abstract": bool(it["is_abstract"]),
                "is_custom": False,
                "iord": None,
                "crdr": None,
                "datatype": None,
                "is_subtotal": it["is_subtotal"],
                "parent_concept": it.get("parent_concept"),
                "source": "facts_fallback",
                "fsds_quarter": None,
                "form": form,
                "filed_date": filed_date,
                "checks_passed": None,
            }
            if not it["values"]:
                stmt_rows.append(
                    {
                        **base,
                        "period_start": None,
                        "period_end": None,
                        "period_end_rounded": None,
                        "qtrs": None,
                        "unit": None,
                        "value": None,
                        "value_presented": None,
                        "is_primary_period": True,
                    }
                )
                continue
            for v in sorted(it["values"], key=lambda v: (v["period_end"], v["qtrs"])):
                if v["qtrs"] == 0:
                    # a line narrowed to one instant above (an opening-balance line) shows that
                    # instant; any other line shows the instant at its own period end, so a balance
                    # sheet's comparative column stays a comparative
                    primary = it.get("pinned", False) or v["period_end_rounded"] == filing_period
                else:
                    primary = v["period_end_rounded"] == filing_period and v["qtrs"] == primary_qtrs
                if primary and not parenthetical and it["concept"] in chk.CHECK_CONCEPTS:
                    # values are sorted ascending by period end, so the last primary one wins: the
                    # period-END figure for an instant reported at both ends (e.g. cash). The value
                    # as filed, which is what the checks are written for (see _checks_from_staged).
                    primary_values[it["concept"]] = v["value"]
                stmt_rows.append(
                    {
                        **base,
                        "period_start": v["period_start"],
                        "period_end": v["period_end"],
                        "period_end_rounded": v["period_end_rounded"],
                        "qtrs": v["qtrs"],
                        "unit": v["unit"],
                        "value": v["value"],
                        "value_presented": -v["value"] if base["negating"] else v["value"],
                        "is_primary_period": primary,
                    }
                )
        if not parenthetical:
            by_statement[statement] = primary_values
            results = chk.run_checks(statement, primary_values)
            passed = chk.checks_passed(results)
            for r in stmt_rows:
                if r["statement"] == statement and r["is_parenthetical"] == parenthetical:
                    r["checks_passed"] = passed
            for res in results:
                check_rows.append(
                    {
                        "accession": accession,
                        "cik": cik,
                        "statement": statement,
                        "check_name": res.check_name,
                        "passed": res.passed,
                        "lhs": res.lhs,
                        "rhs": res.rhs,
                        "difference": res.difference,
                        "detail": res.detail,
                        "source": "facts_fallback",
                    }
                )
    for res in chk.check_across_statements(by_statement):
        check_rows.append(
            {
                "accession": accession,
                "cik": cik,
                "statement": res.statement,
                "check_name": res.check_name,
                "passed": res.passed,
                "lhs": res.lhs,
                "rhs": res.rhs,
                "difference": res.difference,
                "detail": res.detail,
                "source": "facts_fallback",
            }
        )
    stmt_rows.sort(
        key=lambda r: (
            r["statement"],
            r["is_parenthetical"],
            r["line_order"],
            r["period_end"] or date.min,
            r["qtrs"] or 0,
        )
    )
    return stmt_rows, check_rows


TEMPLATE_FORMS = {
    "annual": ("10-K", "10-KT", "10-K405", "10-KSB", "20-F", "40-F"),
    "quarter": ("10-Q", "10-QT", "10-QSB"),
}


def _template_for(duck: Duck, cik: int, family: str) -> list[dict[str, Any]] | None:
    """The company's most recent FSDS-covered filing of the same kind, used for line order and labels.

    Matched on the form itself. Selecting the quarterly template as "any filing that is not annual" let
    an S-1, S-4 or 424B through -- the FSDS covers those too -- so a provisional 10-Q could inherit a
    prospectus's line order and labels instead of the company's last 10-Q.
    """
    if not duck.view("statements", f"{layout.statements_cik_dir(cik)}/*.parquet"):
        return None
    forms = TEMPLATE_FORMS.get(family)
    if not forms:
        return None
    placeholders = ", ".join("?" for _ in forms)
    rows = duck.fetch_dicts(
        f"""
        WITH latest AS (
            SELECT accession FROM statements
            WHERE source = 'fsds' AND replace(upper(form), '/A', '') IN ({placeholders})
            ORDER BY filed_date DESC LIMIT 1
        )
        SELECT DISTINCT statement, is_parenthetical, line_order, concept, label, negating, is_abstract,
               standard_label, taxonomy
        FROM statements WHERE accession = (SELECT accession FROM latest)
          AND statement IS NOT NULL AND line_order IS NOT NULL
        ORDER BY statement, is_parenthetical, line_order
        """,
        list(forms),
    )
    return rows or None


def _facts_for(duck: Duck, cik: int, accession: str) -> list[dict[str, Any]]:
    if not duck.view("cik_facts", f"{layout.facts_cik_dir(cik)}/*.parquet"):
        return []
    return duck.fetch_dicts(
        "SELECT taxonomy, concept, unit, period_start, period_end, value, duration_days, label "
        "FROM cik_facts WHERE accession = ?",
        [accession],
    )


def accessions_with_statements(storage: Storage, cik: int) -> set[str]:
    duck = Duck(storage)
    try:
        if not duck.view("statements", f"{layout.statements_cik_dir(cik)}/*.parquet"):
            return set()
        return set(duck.fetch_column("SELECT DISTINCT accession FROM statements"))
    finally:
        duck.close()


def write_fallback(
    storage: Storage,
    cik: int,
    accession: str,
    rows: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    if not rows:
        return
    storage.write_parquet(
        f"{layout.statements_cik_dir(cik)}/fallback_{accession}.parquet",
        pa.Table.from_pylist(rows, schema=STATEMENTS_SCHEMA),
    )
    storage.delete(f"{layout.statement_checks_cik_dir(cik)}/fallback_{accession}.parquet")
    if checks:
        storage.write_parquet(
            f"{layout.statement_checks_cik_dir(cik)}/fallback_{accession}.parquet",
            pa.Table.from_pylist(checks, schema=CHECKS_SCHEMA),
        )


def fill_fallbacks_for_cik(
    storage: Storage, cik: int, duck: Duck | None = None, rebuild_accessions: set[str] | None = None
) -> int:
    """Build provisional statements for this CIK's XBRL results filings that have none yet.

    Refresh retries can explicitly rebuild their touched fallback accessions: an interrupted previous
    attempt may have written statement rows without the corresponding checks. Never remove FSDS
    outputs, and leave all unrelated fallback history intact.
    """
    own = duck is None
    duck = duck or Duck(storage)
    try:
        if not duck.view("filings", f"{layout.FILINGS}/*/*.parquet"):
            return 0
        forms = _sql_list(FINANCIAL_REPORT_FORMS)
        filings = duck.fetch_dicts(
            f"SELECT accession, form, filed_date, report_date FROM filings WHERE cik = ? AND is_xbrl "
            f"AND (form IN ({forms}) OR replace(form, '/A', '') IN ({forms})) AND report_date IS NOT NULL",
            [cik],
        )
        if not filings:
            return 0
        have = accessions_with_statements(storage, cik)
        if rebuild_accessions and duck.view("existing_cik_statements", f"{layout.statements_cik_dir(cik)}/*.parquet"):
            fsds_accessions = set(
                duck.fetch_column("SELECT DISTINCT accession FROM existing_cik_statements WHERE source = 'fsds'")
            )
            # Rebuild only provisional results, but leave their old files available if facts are
            # temporarily absent or the builder fails. FSDS-covered accessions always take priority.
            have -= rebuild_accessions - fsds_accessions
        periods: dict[str, int] = {}
        if duck.view("periods", layout.PERIODS, hive=False):
            for r in duck.fetch_dicts("SELECT results_accession, fiscal_quarter FROM periods WHERE cik = ?", [cik]):
                periods[r["results_accession"]] = r["fiscal_quarter"]
        built = 0
        templates: dict[str, list[dict[str, Any]] | None] = {}
        for f in filings:
            if f["accession"] in have or is_amendment(f["form"]):
                continue
            family = form_family(f["form"]) or "annual"
            if family not in templates:
                templates[family] = _template_for(duck, cik, family)
            facts = _facts_for(duck, cik, f["accession"])
            if not facts:
                continue
            rows, checks = build_fallback_rows(
                cik,
                f["accession"],
                f["form"],
                f["filed_date"],
                f["report_date"],
                periods.get(f["accession"]),
                facts,
                templates[family],
            )
            write_fallback(storage, cik, f["accession"], rows, checks)
            built += 1
        return built
    finally:
        if own:
            duck.close()


def fill_all_fallbacks(storage: Storage, ciks: list[int] | None = None) -> int:
    duck = Duck(storage)
    try:
        if ciks is None:
            if not duck.view("filings", f"{layout.FILINGS}/*/*.parquet"):
                return 0
            forms = _sql_list(FINANCIAL_REPORT_FORMS)
            ciks = duck.fetch_column(f"SELECT DISTINCT cik FROM filings WHERE is_xbrl AND form IN ({forms})")
        total = 0
        for i, cik in enumerate(ciks, 1):
            total += fill_fallbacks_for_cik(storage, cik, duck)
            if i % 500 == 0:
                log.info("fallbacks: %d/%d companies, %d built", i, len(ciks), total)
        return total
    finally:
        duck.close()


_QUARTER = re.compile(r"^\d{4}q[1-4]$")
_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")


def recheck(storage: Storage, duck: Duck | None = None) -> dict[str, int]:
    """Recompute every arithmetic check from the statements already in the lake, in place.

    The checks are computed when statements are built, from the staged rows; the statements table
    holds exactly those rows. So a change to a check (checks.py) or to how its inputs are picked can
    be measured by recomputing from the lake, in minutes, instead of rebuilding every quarter. This
    is the same code as the build: `_checks_from_staged` over the same primary-period rows, per FSDS
    quarter and per provisional filing, and the files are written under the builders' own names
    (`fsds_<quarter>_<uuid>`, `fallback_<accession>`) so a later quarter rebuild still supersedes
    them. `check-report` afterwards shows what a full rebuild would.

    Not refreshed: `checks_passed` on the statement rows, and with it the periods table, the coverage
    numbers and `verify`'s pass rate. Those are denormalised at build time and rewriting the
    statements table is the expensive part; they catch up on the next `statements` build.
    """
    own = duck is None
    duck = duck or Duck(storage)
    out = {"fsds_quarters": 0, "fsds_checks": 0, "fallback_filings": 0, "fallback_checks": 0}
    try:
        if not duck.view("st", f"{layout.STATEMENTS}/*/*.parquet"):
            return out
        # one pass over the statements: only the rows a check can read (the pivot's own filters)
        duck.sql(
            f"""
            CREATE OR REPLACE TEMP TABLE chk_rows AS
            SELECT accession, cik, statement, concept, value, period_end_rounded, is_primary_period,
                   is_parenthetical, coalesce(segments, '') AS segments, source, fsds_quarter
            FROM st
            WHERE is_primary_period AND NOT is_parenthetical AND value IS NOT NULL
              AND coalesce(segments, '') = '' AND statement IN ('BS', 'IS', 'CF')
              AND concept IN ({_sql_list(sorted(chk.CHECK_CONCEPTS))})
            """
        )
        storage.mkdirs(layout.STATEMENT_CHECKS)

        # FSDS: every quarter's checks are replaced, including a quarter that now yields none
        _delete_glob(storage, f"{layout.STATEMENT_CHECKS}/*/fsds_*.parquet")
        for q in duck.fetch_column("SELECT DISTINCT fsds_quarter FROM chk_rows WHERE source = 'fsds' ORDER BY 1"):
            if not q or not _QUARTER.match(q):
                raise RuntimeError(f"unexpected fsds_quarter {q!r} on statements rows")
            duck.sql(
                f"CREATE OR REPLACE VIEW stg AS SELECT * FROM chk_rows WHERE source = 'fsds' AND fsds_quarter = '{q}'"
            )
            checks = _checks_from_staged(duck, "fsds")
            if checks.num_rows:
                duck.register("chk", checks)
                duck.sql(
                    f"""
                    COPY (SELECT * FROM chk ORDER BY cik, accession, statement, check_name)
                    TO '{duck.path(layout.STATEMENT_CHECKS)}'
                    (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (cik), APPEND,
                     FILENAME_PATTERN 'fsds_{q}_{{uuid}}')
                    """
                )
                duck.unregister("chk")
            out["fsds_quarters"] += 1
            out["fsds_checks"] += checks.num_rows

        # provisional filings: one file each, replaced even when the filing now yields no check
        duck.sql("CREATE OR REPLACE VIEW stg AS SELECT * FROM chk_rows WHERE source = 'facts_fallback'")
        by_filing: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
        for r in _checks_from_staged(duck, "facts_fallback").to_pylist():
            by_filing[(r["cik"], r["accession"])].append(r)
        for cik, acc in duck.fetch_all("SELECT DISTINCT cik, accession FROM st WHERE source = 'facts_fallback'"):
            if not _ACCESSION.match(acc):
                raise RuntimeError(f"unexpected accession {acc!r} on statements rows")
            path = f"{layout.statement_checks_cik_dir(cik)}/fallback_{acc}.parquet"
            storage.delete(path)
            rows = by_filing.get((int(cik), acc), [])
            if rows:
                storage.write_parquet(path, pa.Table.from_pylist(rows, schema=CHECKS_SCHEMA))
            out["fallback_filings"] += 1
            out["fallback_checks"] += len(rows)
        return out
    finally:
        if own:
            duck.close()
