"""Step 4: coverage and applicability, company by company, over the whole lake.

We can say what we hold. This says what we should hold, and where the two differ. One pass over the
lake produces, per tier of company:

* how many companies we have, and how many have statements built;
* how many are getting **no arithmetic check at all** — the silent failure, because a company whose
  filings never trip a check is unverified and nothing says so;
* every company that was expected to have statements (it filed a financial report) but has none,
  each with a reason (foreign filer, gone dark, SPAC) or flagged as an unexplained gap to investigate.

Tiers, because a gap means different things in each: a company on a big exchange with no statements is
a bug; a shell company in the long tail that never filed accounts is normal. This is internal — it
tells us where to look and gates what we publish; it is never shown to a user.

Read-only. Run it against a local lake; on a remote lake it scans whole tables and should be run
against a local copy (see steps.md, Part 9).
"""

from __future__ import annotations

from typing import Any

from filings_hub.lake import layout
from filings_hub.lake.duck import Duck
from filings_hub.lake.storage import Storage

# Tiers, most-scrutinised first. A gap high in this list is a bug; a gap at the bottom is usually fine.
TIERS = ("nyse_nasdaq", "other_listed", "filing_unlisted", "everything_else")
TIER_LABELS = {
    "nyse_nasdaq": "Listed on NYSE or Nasdaq",
    "other_listed": "Other listed (OTC, CBOE, ...)",
    "filing_unlisted": "Not listed but files financial statements",
    "everything_else": "Everything else (funds, trusts, shells, defunct)",
}

# How many gap companies to name per tier; the count is always exact, only the examples are capped.
GAP_SAMPLE = 100

_TIER_SQL = """
    CASE
        WHEN c.is_listed AND (c.exchange ILIKE '%nasdaq%' OR c.exchange ILIKE 'nyse%') THEN 'nyse_nasdaq'
        WHEN c.is_listed THEN 'other_listed'
        WHEN c.last_financial_report_date IS NOT NULL THEN 'filing_unlisted'
        ELSE 'everything_else'
    END
"""

# Why a company that filed a financial report has no statements built. Ordered: first match wins.
_REASON_SQL = """
    CASE
        WHEN lfr_form IN ('20-F', '40-F') THEN 'foreign filer (20-F / 40-F)'
        WHEN NOT is_active THEN 'gone dark (no recent filing)'
        WHEN sic = '6770' OR name ILIKE '%acquisition corp%' THEN 'blank-check / SPAC'
        ELSE 'unexplained - investigate'
    END
"""


# A table absent from the lake gets a typed, empty stand-in so the audit reports zero rather than
# failing. The columns are exactly the ones the audit reads.
_EMPTY_VIEWS = {
    "filings": "SELECT NULL::BIGINT AS cik, NULL::VARCHAR AS accession WHERE false",
    "statements": "SELECT NULL::BIGINT AS cik, NULL::VARCHAR AS accession WHERE false",
    "statement_checks": (
        "SELECT NULL::BIGINT AS cik, NULL::VARCHAR AS accession, NULL::BOOLEAN AS passed, "
        "NULL::VARCHAR AS check_name, NULL::VARCHAR AS statement WHERE false"
    ),
}


def _bind_views(duck: Duck) -> bool:
    """Bind the four tables the audit reads. Returns False when there are no companies at all."""
    if not duck.view("companies", layout.COMPANIES, hive=False):
        return False
    if not duck.view("filings", f"{layout.FILINGS}/*/*.parquet"):
        duck.sql(f"CREATE OR REPLACE VIEW filings AS {_EMPTY_VIEWS['filings']}")
    for name in ("statements", "statement_checks"):
        rel = layout.STATEMENTS if name == "statements" else layout.STATEMENT_CHECKS
        if not duck.view(name, f"{rel}/*/*.parquet"):
            duck.sql(f"CREATE OR REPLACE VIEW {name} AS {_EMPTY_VIEWS[name]}")
    return True


def _co_cte() -> str:
    """Per-company metrics with a tier, as a CTE named `co`. Aggregates are joined, not scanned twice."""
    return f"""
        WITH f AS (SELECT cik, count(*) AS held FROM filings GROUP BY 1),
             s AS (SELECT cik, count(DISTINCT accession) AS sfilings FROM statements GROUP BY 1),
             k AS (
                 SELECT cik, count(*) AS ran,
                        count(*) FILTER (WHERE passed) AS passed,
                        count(*) FILTER (WHERE NOT passed) AS failed
                 FROM statement_checks GROUP BY 1
             ),
             co AS (
                 SELECT c.cik, c.name, c.exchange, c.sic, c.is_active,
                        c.last_financial_report_form AS lfr_form,
                        c.last_financial_report_date AS lfr_date,
                        {_TIER_SQL} AS tier,
                        coalesce(f.held, 0) AS filings_held,
                        coalesce(s.sfilings, 0) AS statement_filings,
                        coalesce(k.ran, 0) AS checks_ran,
                        coalesce(k.passed, 0) AS checks_passed,
                        coalesce(k.failed, 0) AS checks_failed
                 FROM companies c
                 LEFT JOIN f ON f.cik = c.cik
                 LEFT JOIN s ON s.cik = c.cik
                 LEFT JOIN k ON k.cik = c.cik
             )
    """


def coverage_audit(storage: Storage) -> dict[str, Any]:
    duck = Duck(storage)
    try:
        if not _bind_views(duck):
            return {"companies": 0, "message": "no companies in the lake"}

        by_tier = duck.fetch_dicts(
            _co_cte()
            + """
            SELECT tier,
                   count(*) AS companies,
                   count(*) FILTER (WHERE statement_filings > 0) AS with_statements,
                   count(*) FILTER (WHERE checks_ran > 0) AS with_any_check,
                   count(*) FILTER (WHERE statement_filings > 0 AND checks_ran = 0) AS zero_applicable_check,
                   count(*) FILTER (WHERE lfr_date IS NOT NULL AND statement_filings = 0) AS expected_but_missing
            FROM co GROUP BY tier
            """
        )
        tiers = {r["tier"]: r for r in by_tier}

        # every expected-but-missing company, reason attached; examples capped, counts exact
        gaps = duck.fetch_dicts(
            _co_cte()
            + f"""
            SELECT tier, cik, name, {_REASON_SQL} AS reason
            FROM co WHERE lfr_date IS NOT NULL AND statement_filings = 0
            ORDER BY tier, cik
            """
        )
        gaps_by_tier: dict[str, dict[str, Any]] = {}
        for t in TIERS:
            rows = [g for g in gaps if g["tier"] == t]
            reasons: dict[str, int] = {}
            for g in rows:
                reasons[g["reason"]] = reasons.get(g["reason"], 0) + 1
            gaps_by_tier[t] = {
                "total": len(rows),
                "reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
                "unexplained": [
                    {"cik": g["cik"], "name": g["name"]}
                    for g in rows
                    if g["reason"] == "unexplained - investigate"
                ][:GAP_SAMPLE],
            }

        # which checks actually apply, and the gross-profit rate against Hicham's 70-80 % estimate
        per_check = {
            r["check_name"]: r["filings"]
            for r in duck.fetch_dicts(
                "SELECT check_name, count(DISTINCT accession) AS filings "
                "FROM statement_checks GROUP BY 1 ORDER BY 2 DESC"
            )
        }
        is_filings = duck.fetch_dicts(
            "SELECT count(DISTINCT accession) AS n FROM statement_checks WHERE statement = 'IS'"
        )[0]["n"]
        gp = per_check.get("gross_profit", 0)
        gross_profit_rate = (gp / is_filings) if is_filings else 0.0

        return {
            "companies": sum(t["companies"] for t in tiers.values()),
            "tiers": tiers,
            "gaps": gaps_by_tier,
            "checks_applied": per_check,
            "gross_profit_rate": gross_profit_rate,
            "zero_applicable_check_total": sum(t["zero_applicable_check"] for t in tiers.values()),
        }
    finally:
        duck.close()


def format_report(report: dict[str, Any]) -> str:
    if report.get("companies", 0) == 0:
        return report.get("message", "no companies")
    out = [f"Coverage audit: {report['companies']:,} companies", ""]
    for t in TIERS:
        tr = report["tiers"].get(t)
        if not tr:
            continue
        out.append(f"[{t}]  {TIER_LABELS[t]}")
        out.append(
            f"  companies {tr['companies']:,}   with statements {tr['with_statements']:,}   "
            f"with a check {tr['with_any_check']:,}"
        )
        out.append(f"  getting NO check at all (has statements, zero checks): {tr['zero_applicable_check']:,}")
        gap = report["gaps"][t]
        if gap["total"]:
            reasons = ", ".join(f"{k}: {v:,}" for k, v in gap["reasons"].items())
            out.append(f"  filed a financial report but no statements built: {gap['total']:,}  ({reasons})")
        out.append("")
    out.append(f"Total companies getting no arithmetic check: {report['zero_applicable_check_total']:,}")
    out.append(f"Gross-profit check applies to {report['gross_profit_rate'] * 100:.1f} % of income statements "
               f"(Hicham's estimate: 70-80 %)")
    unexplained = sum(len(report["gaps"][t]["unexplained"]) for t in ("nyse_nasdaq", "other_listed"))
    if unexplained:
        out.append(f"Unexplained gaps in the top two tiers (investigate): {unexplained}"
                   f"{' (sampled)' if unexplained >= GAP_SAMPLE else ''}")
    return "\n".join(out)
