"""Acceptance harness for the plan's phase 1 definition of done.

Every criterion that needs real SEC data lives here so the whole set runs as one command:

    filings-hub verify

Each criterion reports pass / fail / not-evaluated with the evidence behind it, and the command
exits non-zero if any of them failed. Nothing here is fixture-specific: it reads the serving tables,
so it works against a lake built by `filings-hub backfill` or a loaded Postgres.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from filings_hub.db.database import Database

DATA_DIR = Path(__file__).parent / "data"
SP500_CSV = DATA_DIR / "sp500_constituents.csv"
GOLDEN_CSV = DATA_DIR / "golden_set.csv"

PERIOD_LABEL_RE = re.compile(r"^(FY\d{4}|Q[1-3] \d{4})T?$")

MAX_BACKFILL_HOURS = 4.0
REFRESH_WEEKDAY_STREAK = 5
CHECKS_PASS_THRESHOLD = 0.95
QUALITY_SINCE_FISCAL_YEAR = 2020


@dataclass
class Criterion:
    name: str
    passed: bool | None  # None: could not be evaluated from the data present
    detail: str
    evidence: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return {True: "PASS", False: "FAIL", None: "NOT EVALUATED"}[self.passed]


def load_golden_set(path: Path | None = None) -> list[dict[str, str]]:
    with (path or GOLDEN_CSV).open() as f:
        return [r for r in csv.DictReader(f) if r.get("ticker")]


def load_sp500(path: Path | None = None) -> list[int]:
    """Distinct CIKs of the vendored S&P 500 list.

    The index lists ~503 tickers for ~500 companies because a dual-class listing (GOOGL/GOOG,
    FOXA/FOX, NWSA/NWS) is two symbols against one CIK, so the CIKs are deduplicated: the hub's unit
    is the filer, and counting one twice would make the universe look larger than it can ever be.
    Rows without an integer CIK are skipped.
    """
    seen: dict[int, None] = {}
    with (path or SP500_CSV).open() as f:
        for row in csv.DictReader(f):
            cik = (row.get("CIK") or "").strip()
            if cik.isdigit():
                seen.setdefault(int(cik))
    return list(seen)


def load_tickers_file(path: Path) -> list[str]:
    return [ln.strip().upper() for ln in path.read_text().splitlines() if ln.strip()]


# ---------------------------------------------------------------------------------------------
# 1. bulk backfill runs end to end in under four hours
# ---------------------------------------------------------------------------------------------
def check_backfill_duration(db: Database, max_hours: float = MAX_BACKFILL_HOURS) -> Criterion:
    runs = db.query(
        "SELECT run_id, started_at, duration_seconds, status, new_filings, facts_rows, db_loaded, steps "
        "FROM run_log WHERE kind = 'backfill' ORDER BY started_at DESC LIMIT 5"
    )
    name = f"Bulk backfill completes in < {max_hours:g} h"
    if not runs:
        return Criterion(name, None, "no backfill has been recorded in run_log")
    ok = [r for r in runs if r["status"] == "ok" and r["duration_seconds"] is not None]
    if not ok:
        return Criterion(
            name, False, "no backfill has completed successfully", [f"{r['run_id']}: {r['status']}" for r in runs]
        )
    latest = ok[0]
    seconds = latest["duration_seconds"]
    hours = seconds / 3600
    spent = f"{hours:.2f} h" if hours >= 1 else f"{seconds / 60:.1f} min"
    evidence = [
        f"run {latest['run_id']} started {latest['started_at']}",
        f"{latest['new_filings']:,} filings, {latest['facts_rows']:,} facts, "
        f"serving tables loaded: {bool(latest['db_loaded'])}",
    ]
    if latest.get("steps"):
        evidence.append("steps: " + ", ".join(f"{step}s" for step in latest["steps"]))
    return Criterion(name, hours < max_hours, f"last successful backfill took {spent}", evidence)


# ---------------------------------------------------------------------------------------------
# 2. the daily refresh has run five consecutive weekdays unattended
# ---------------------------------------------------------------------------------------------
def _weekdays_back(end: date, n: int) -> list[date]:
    out: list[date] = []
    day = end
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day -= timedelta(days=1)
    return sorted(out)


def check_refresh_streak(db: Database, streak: int = REFRESH_WEEKDAY_STREAK) -> Criterion:
    name = f"Daily refresh ran {streak} consecutive weekdays without intervention"
    runs = db.query(
        "SELECT run_id, status, started_at, index_dates, failures FROM run_log "
        "WHERE kind = 'refresh' ORDER BY started_at DESC LIMIT 200"
    )
    if not runs:
        return Criterion(name, None, "no refresh has been recorded in run_log")
    covered: dict[date, str] = {}
    failures = 0
    for r in runs:
        if r["status"] == "failed":
            failures += 1
        for d in r["index_dates"] or []:
            day = date.fromisoformat(d) if isinstance(d, str) else d
            # a later run supersedes an earlier one for the same index date
            covered.setdefault(day, r["status"])
    if not covered:
        return Criterion(name, False, f"{len(runs)} refresh runs, none of which processed a daily index")
    wanted = _weekdays_back(max(covered), streak)
    missing = [d for d in wanted if d not in covered]
    bad = [d for d in wanted if covered.get(d) == "failed"]
    evidence = [
        f"latest index date processed: {max(covered)}",
        f"weekdays checked: {', '.join(d.isoformat() for d in wanted)}",
        f"{failures} failed run(s) in the last {len(runs)} refreshes",
    ]
    if missing:
        evidence.append(f"not processed: {', '.join(d.isoformat() for d in missing)}")
    passed = not missing and not bad and failures == 0
    return Criterion(name, passed, f"{len(wanted) - len(missing)}/{streak} weekdays covered", evidence)


# ---------------------------------------------------------------------------------------------
# 3. the golden set has periods, statements and an Excel export a human can check
# ---------------------------------------------------------------------------------------------
def _resolve(db: Database, ticker: str) -> int | None:
    rows = db.query("SELECT cik FROM tickers WHERE ticker = ? ORDER BY is_primary DESC LIMIT 1", [ticker.upper()])
    return int(rows[0]["cik"]) if rows else None


def check_golden_company(db: Database, ticker: str) -> tuple[bool, str]:
    """Every invariant a human would check on the company page, for one company."""
    cik = _resolve(db, ticker)
    if cik is None:
        return False, "not in the universe"
    periods = db.query(f"SELECT * FROM {db.periods_table} WHERE cik = ? ORDER BY period_end DESC LIMIT 20", [cik])
    if not periods:
        return False, "no periods"
    bad_labels = [p["period_label"] for p in periods if not PERIOD_LABEL_RE.match(p["period_label"])]
    if bad_labels:
        return False, f"malformed period labels: {', '.join(sorted(set(bad_labels))[:3])}"
    if len({p["period_label"] for p in periods}) != len(periods):
        return False, "duplicate period labels"
    if not any(p["fiscal_quarter"] == 4 for p in periods):
        return False, "no annual period in the latest 20"
    missing_results = [p["period_label"] for p in periods if not p["results_accession"]]
    if missing_results:
        return False, f"periods with no results filing: {len(missing_results)}"

    with_statements = [p for p in periods if p["statements_source"]]
    if not with_statements:
        return False, "no period has statements"
    failed = [p["period_label"] for p in with_statements if p["checks_passed"] is False]
    latest = with_statements[0]
    grid_lines = db.query(
        "SELECT statement, count(*) AS n FROM statements WHERE accession = ? AND is_primary_period "
        "AND statement IN ('IS', 'BS', 'CF') GROUP BY statement",
        [latest["results_accession"]],
    )
    have = {r["statement"] for r in grid_lines}
    if not {"IS", "BS"} <= have:
        return False, f"{latest['period_label']} has no {'income statement' if 'IS' not in have else 'balance sheet'}"
    er = sum(1 for p in periods if p["earnings_release_accession"])
    detail = (
        f"{len(periods)} periods, {len(with_statements)} with statements, {er} with an earnings release; "
        f"latest {latest['period_label']} ({latest['statements_source']}, "
        f"{sum(r['n'] for r in grid_lines)} lines)"
    )
    if failed:
        return False, f"{detail}; arithmetic checks failed on {', '.join(failed[:3])}"
    return True, detail


def check_golden_set(db: Database, golden: list[dict[str, str]]) -> Criterion:
    name = f"{len(golden)}-company golden set has periods, statements and an export"
    results: list[tuple[str, bool, str]] = []
    for row in golden:
        ok, detail = check_golden_company(db, row["ticker"])
        results.append((row["ticker"], ok, detail))
    failed = [r for r in results if not r[1]]
    missing = [r for r in results if r[2] == "not in the universe"]
    evidence = [f"{'ok  ' if ok else 'FAIL'} {t:<6} {d}" for t, ok, d in results]
    if len(missing) > len(results) // 2:
        return Criterion(
            name,
            None,
            f"{len(missing)}/{len(results)} of the golden set is not in this universe; "
            "build the lake from real SEC data before this means anything",
            evidence,
        )
    return Criterion(name, not failed, f"{len(results) - len(failed)}/{len(results)} companies pass", evidence)


def export_golden_set(db: Database, golden: list[dict[str, str]], out_dir: Path, periods: int = 8) -> list[Path]:
    """Write one workbook per golden-set company for the Friday eyeball check."""
    from filings_hub.export.excel import export_excel

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for row in golden:
        cik = _resolve(db, row["ticker"])
        if cik is None:
            continue
        path = out_dir / f"{row['ticker'].replace('.', '-')}-statements.xlsx"
        path.write_bytes(export_excel(db, cik, None, periods))
        written.append(path)
    return written


# ---------------------------------------------------------------------------------------------
# 4. checks_passed >= 95 % on S&P 500 filings since 2020
# ---------------------------------------------------------------------------------------------
def check_statement_quality(
    db: Database,
    ciks: Iterable[int] | None = None,
    tickers: Iterable[str] | None = None,
    since: int = QUALITY_SINCE_FISCAL_YEAR,
    threshold: float = CHECKS_PASS_THRESHOLD,
) -> Criterion:
    name = f"checks_passed >= {threshold:.0%} on S&P 500 filings since {since}"
    where = "p.fiscal_year >= ?"
    params: list[Any] = [since]
    if tickers:
        tl = sorted({t.upper() for t in tickers})
        where += f" AND p.cik IN (SELECT cik FROM tickers WHERE ticker IN ({', '.join('?' for _ in tl)}))"
        params += tl
    elif ciks:
        cl = sorted(set(ciks))
        where += f" AND p.cik IN ({', '.join('?' for _ in cl)})"
        params += cl
    rows = db.query(
        f"""
        SELECT count(*) AS periods,
               sum(CASE WHEN p.checks_passed IS NOT NULL THEN 1 ELSE 0 END) AS applicable,
               sum(CASE WHEN p.checks_passed THEN 1 ELSE 0 END) AS passed,
               count(DISTINCT p.cik) AS companies,
               sum(CASE WHEN p.statements_source = 'facts_fallback' THEN 1 ELSE 0 END) AS provisional
        FROM {db.periods_table} p WHERE {where}
        """,
        params,
    )
    r = rows[0] if rows else {}
    applicable = r.get("applicable") or 0
    if not applicable:
        return Criterion(name, None, "no filings with applicable arithmetic checks in range")
    rate = (r["passed"] or 0) / applicable
    wanted = len(set(tickers)) if tickers else len(set(ciks or ()))
    found = r["companies"] or 0
    evidence = [
        f"{found} of {wanted} companies in the universe, {r['periods']} periods, {applicable} with applicable checks",
        f"{r['passed']} passed, {applicable - r['passed']} failed, {r['provisional']} provisional",
    ]
    detail = f"pass rate {rate:.1%} over {found} companies"
    if wanted and found < wanted / 2:
        # a rate measured over a fraction of the universe verifies the criterion neither way
        return Criterion(name, None, f"{detail}; only {found}/{wanted} of the universe is in this lake", evidence)
    return Criterion(name, rate >= threshold, detail, evidence)


# ---------------------------------------------------------------------------------------------
# 5. every golden-set period has the correct label, results filing and earnings release
# ---------------------------------------------------------------------------------------------
def check_earnings_release_coverage(db: Database, golden: list[dict[str, str]], min_coverage: float = 0.8) -> Criterion:
    """Quarterly and annual results are normally preceded by an 8-K item 2.02. Some filers never file
    one, so this reports coverage across the golden set rather than demanding it company by company."""
    name = "Golden-set periods have their earnings-release 8-K attached"
    total = matched = 0
    per_company: list[str] = []
    for row in golden:
        cik = _resolve(db, row["ticker"])
        if cik is None:
            continue
        periods = db.query(
            f"SELECT period_label, earnings_release_accession, earnings_release_filed_date, period_end "
            f"FROM {db.periods_table} WHERE cik = ? ORDER BY period_end DESC LIMIT 8",
            [cik],
        )
        if not periods:
            continue
        hit = sum(1 for p in periods if p["earnings_release_accession"])
        total += len(periods)
        matched += hit
        per_company.append(f"{row['ticker']:<6} {hit}/{len(periods)} periods")
        for p in periods:
            if p["earnings_release_filed_date"] and p["period_end"]:
                lag = (p["earnings_release_filed_date"] - p["period_end"]).days
                if not 0 < lag <= 90:
                    per_company.append(f"{row['ticker']:<6} {p['period_label']}: 8-K {lag} days after period end")
    if not total:
        return Criterion(name, None, "no golden-set periods found")
    present = sum(1 for row in golden if _resolve(db, row["ticker"]) is not None)
    coverage = matched / total
    detail = f"{matched}/{total} periods ({coverage:.0%}) across {present} companies"
    if present < len(golden) // 2:
        return Criterion(name, None, f"{detail}; most of the golden set is not in this lake", per_company)
    return Criterion(name, coverage >= min_coverage, detail, per_company)


# ---------------------------------------------------------------------------------------------
def run_acceptance(
    db: Database,
    golden: list[dict[str, str]] | None = None,
    tickers: list[str] | None = None,
    since: int = QUALITY_SINCE_FISCAL_YEAR,
) -> list[Criterion]:
    golden = golden if golden is not None else load_golden_set()
    return [
        check_backfill_duration(db),
        check_refresh_streak(db),
        check_golden_set(db, golden),
        check_earnings_release_coverage(db, golden),
        check_statement_quality(db, ciks=None if tickers else load_sp500(), tickers=tickers, since=since),
    ]


def format_report(criteria: list[Criterion], verbose: bool = False) -> str:
    width = max(len(c.name) for c in criteria) + 2
    lines = ["", "Phase 1 definition of done", "=" * (width + 30), ""]
    for c in criteria:
        lines.append(f"{c.status:<14} {c.name:<{width}} {c.detail}")
        if verbose or c.passed is not True:
            lines.extend(f"{'':<14} - {e}" for e in c.evidence[:60])
    passed = sum(c.passed is True for c in criteria)
    failed = sum(c.passed is False for c in criteria)
    skipped = sum(c.passed is None for c in criteria)
    lines += ["", f"{passed} passed, {failed} failed, {skipped} not evaluated", ""]
    return "\n".join(lines)
