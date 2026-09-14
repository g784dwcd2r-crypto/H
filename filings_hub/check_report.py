"""An error report over the arithmetic checks: which rule fails, how badly, and for whom.

`check-tolerance` answers "is the tolerance hiding breaks". This answers the next question: of the
checks that fail, which rule (balance sheet balances, gross profit, EPS, ...), how far past the line,
how many distinct companies, and the worst offenders by name. It is the report to skim when the
headline says ~9 % of checks fail and you want to know where.

Read-only. Run it against a local lake (a remote lake scans whole tables; see steps.md, Part 9).
"""

from __future__ import annotations

from typing import Any

from filings_hub.ingest.checks import EPS_RELATIVE_TOLERANCE, RELATIVE_TOLERANCE
from filings_hub.lake import layout
from filings_hub.lake.duck import Duck
from filings_hub.lake.storage import Storage

# A failing check, by how far past its tolerance line it sits. q = (relative gap) / (that check's
# tolerance), so q >= 1 means it failed; the bands say by how much.
FAIL_BANDS = ("just-over", "2-10x", ">10x")

# Plain-language names for the checks, so the report reads without knowing the concept codes.
CHECK_LABELS = {
    "assets_eq_liabilities_and_equity": "Balance sheet balances (Assets = Liabilities + Equity)",
    "assets_eq_liabilities_plus_equity": "Balance sheet balances (older layout)",
    "gross_profit": "Gross profit (Revenue - Cost = Gross profit)",
    "income_after_tax": "Income after tax (Pretax - Tax = Continuing income)",
    "eps_basic": "Earnings per share, basic",
    "eps_diluted": "Earnings per share, diluted",
    "net_income_is_equals_cf": "Net income agrees: income statement = cash flow",
    "ending_cash_cf_equals_bs": "Ending cash agrees: cash flow = balance sheet",
}


def _tol_expr() -> str:
    return (
        f"CASE WHEN check_name LIKE 'eps\\_%' ESCAPE '\\' "
        f"THEN {EPS_RELATIVE_TOLERANCE} ELSE {RELATIVE_TOLERANCE} END"
    )


def failure_report(storage: Storage, examples: int = 20) -> dict[str, Any]:
    duck = Duck(storage)
    try:
        if not duck.view("sc", f"{layout.STATEMENT_CHECKS}/*/*.parquet"):
            return {"total": 0, "message": "no statement_checks in the lake"}
        have_companies = duck.view("companies", layout.COMPANIES, hive=False)

        base = f"""
            WITH t AS (
                SELECT check_name, cik, accession, lhs, rhs, passed,
                       abs(coalesce(difference, lhs - rhs)) AS gap,
                       greatest(abs(lhs), abs(rhs)) AS mag,
                       {_tol_expr()} AS tol
                FROM sc WHERE lhs IS NOT NULL AND rhs IS NOT NULL
            ),
            q AS (
                SELECT *, CASE WHEN mag = 0 OR mag IS NULL THEN NULL ELSE (gap / mag) / tol END AS q
                FROM t
            )
        """

        per_check = duck.fetch_dicts(
            base
            + """
            SELECT check_name,
                   count(*) AS total,
                   count(*) FILTER (WHERE passed) AS passed,
                   count(*) FILTER (WHERE NOT passed) AS failed,
                   count(*) FILTER (WHERE NOT passed AND q < 2) AS just_over,
                   count(*) FILTER (WHERE NOT passed AND q >= 2 AND q < 10) AS mid,
                   count(*) FILTER (WHERE NOT passed AND (q >= 10 OR q IS NULL)) AS far
            FROM q GROUP BY check_name ORDER BY failed DESC
            """
        )

        totals = duck.fetch_dicts(
            "SELECT count(*) AS checks, count(*) FILTER (WHERE NOT passed) AS failed, "
            "count(DISTINCT CASE WHEN NOT passed THEN cik END) AS companies_with_failure, "
            "count(DISTINCT cik) AS companies_checked "
            "FROM sc WHERE lhs IS NOT NULL AND rhs IS NOT NULL"
        )[0]

        name_col = "c.name" if have_companies else "NULL"
        name_join = "LEFT JOIN companies c ON c.cik = q.cik" if have_companies else ""
        worst = duck.fetch_dicts(
            base
            + f"""
            SELECT q.check_name, q.cik, {name_col} AS name, q.accession, q.lhs, q.rhs, q.q AS q
            FROM q {name_join}
            WHERE NOT q.passed AND q.q IS NOT NULL
            ORDER BY q.q DESC LIMIT {int(examples)}
            """
        )

        return {
            "total": totals["checks"],
            "failed": totals["failed"],
            "companies_checked": totals["companies_checked"],
            "companies_with_failure": totals["companies_with_failure"],
            "per_check": per_check,
            "worst": worst,
        }
    finally:
        duck.close()


def format_failure_report(report: dict[str, Any]) -> str:
    if report.get("total", 0) == 0:
        return report.get("message", "no checks found")
    checked = report["companies_checked"] or 1
    out = [
        f"Checks: {report['total']:,}   failed: {report['failed']:,} "
        f"({report['failed'] / max(report['total'], 1) * 100:.1f} %)",
        f"Companies checked: {report['companies_checked']:,}   "
        f"with at least one failing check: {report['companies_with_failure']:,} "
        f"({report['companies_with_failure'] / checked * 100:.1f} %)",
        "",
        "By check (worst first):",
        f"  {'check':<52} {'ran':>9} {'fail':>9} {'fail%':>6}  {'just':>7} {'2-10x':>7} {'>10x':>8}",
    ]
    for r in report["per_check"]:
        label = CHECK_LABELS.get(r["check_name"], r["check_name"])
        rate = f"{r['failed'] / r['total'] * 100:.0f}%" if r["total"] else "-"
        out.append(
            f"  {label:<52.52} {r['total']:>9,} {r['failed']:>9,} {rate:>6}  "
            f"{r['just_over']:>7,} {r['mid']:>7,} {r['far']:>8,}"
        )
    if report["worst"]:
        out.append("")
        out.append(f"Worst {len(report['worst'])} failures (most out of line):")
        for w in report["worst"]:
            who = w.get("name") or f"CIK {w['cik']}"
            tol = EPS_RELATIVE_TOLERANCE if w["check_name"].startswith("eps") else RELATIVE_TOLERANCE
            pct = (w["q"] or 0) * tol
            out.append(
                f"  {who[:34]:<34} {CHECK_LABELS.get(w['check_name'], w['check_name'])[:34]:<34} "
                f"{w['lhs']:>18,.0f} vs {w['rhs']:>18,.0f}  ({pct * 100:.1f}% off)"
            )
    return "\n".join(out)
