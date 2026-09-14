"""Step 1: how much is the flat check tolerance hiding?

Every arithmetic check stores its two sides (`lhs`, `rhs`) and the gap between them in
`statement_checks`. A check passes when that gap is within a flat tolerance: 0.5 % of the larger
side, or a 1.0 absolute floor for small numbers; the earnings-per-share checks use 1 % instead. Those
numbers are a guess we chose, not something the filing told us.

This reads every check ever run and asks one question: how close were the passing checks to the line?

* If almost every pass is exact or nowhere near the line, the flat tolerance is harmless in practice
  and the per-line fix (step 9, a tolerance from the filing's own `decimals`) can wait.
* If many passes sit *just* under the line, we have been waving real breaks through, and the per-line
  fix should move up the order.

It is read-only. It writes nothing; it reads `statement_checks` and reports. The band edges are taken
from the real tolerance constants in `checks.py`, so if the tolerance ever changes, this measurement
follows it rather than drifting.
"""

from __future__ import annotations

from typing import Any

from filings_hub.ingest.checks import (
    ABSOLUTE_TOLERANCE,
    EPS_ABSOLUTE_TOLERANCE,
    EPS_RELATIVE_TOLERANCE,
    RELATIVE_TOLERANCE,
)
from filings_hub.lake import layout
from filings_hub.lake.duck import Duck
from filings_hub.lake.storage import Storage

# A pass counts as a "near miss" when its gap is at least this fraction of the way to the line. A
# near miss is a break that the flat tolerance let through by a whisker: tighten the tolerance a
# little and it would flip to a failure, so it is exactly where a real error can hide.
NEAR_MISS_FRACTION = 0.8

# If more than this share of the passes that the relative tolerance actually governs are near misses,
# the flat tolerance is likely hiding real breaks and the per-line fix (step 9) is worth prioritising.
# A heuristic to guide a human, not an automated verdict.
DANGER_SHARE_WARN = 0.01

# Bands for a passing check, as a fraction q = (relative gap) / (that check's relative tolerance).
# q is 0 for an exact pass and approaches 1 at the line. Reported low to high.
PASS_BANDS = ["exact", "<0.2", "0.2-0.6", "0.6-0.8", "near-miss"]
# Bands for a failing check, same q but now q >= 1 (it crossed the line).
FAIL_BANDS = ["just-over", "2-10x", ">10x"]


def _band_sql(near: float) -> str:
    """SQL that labels each row by its band. `q` is the gap as a fraction of the check's own line."""
    return f"""
        CASE
            WHEN floor_regime AND passed THEN 'floor'
            WHEN floor_regime AND NOT passed THEN 'fail-floor'
            WHEN q IS NULL THEN 'exact'
            WHEN passed AND q <= 0 THEN 'exact'
            WHEN passed AND q < 0.2 THEN '<0.2'
            WHEN passed AND q < 0.6 THEN '0.2-0.6'
            WHEN passed AND q < {near} THEN '0.6-0.8'
            WHEN passed THEN 'near-miss'
            WHEN q < 2 THEN 'just-over'
            WHEN q < 10 THEN '2-10x'
            ELSE '>10x'
        END
    """


def _rows(duck: Duck) -> list[dict[str, Any]]:
    """One row per (eps?, passed, band): the count. Everything is aggregated in the query."""
    query = f"""
        WITH c AS (
            SELECT
                check_name LIKE 'eps\\_%' ESCAPE '\\' AS is_eps,
                passed,
                abs(coalesce(difference, lhs - rhs)) AS gap,
                greatest(abs(lhs), abs(rhs)) AS mag,
                abs(rhs) AS rhs_mag
            FROM sc
            WHERE lhs IS NOT NULL AND rhs IS NOT NULL
        ),
        t AS (
            SELECT
                is_eps, passed, gap, mag,
                CASE WHEN is_eps THEN {EPS_RELATIVE_TOLERANCE} ELSE {RELATIVE_TOLERANCE} END AS rel_tol,
                -- the absolute floor is the binding tolerance when it is larger than the relative one
                CASE
                    WHEN is_eps THEN {EPS_RELATIVE_TOLERANCE} * rhs_mag <= {EPS_ABSOLUTE_TOLERANCE}
                    ELSE {RELATIVE_TOLERANCE} * mag <= {ABSOLUTE_TOLERANCE}
                END AS floor_regime,
                CASE WHEN mag = 0 OR mag IS NULL THEN NULL ELSE gap / mag END AS rel
            FROM c
        ),
        q AS (
            SELECT is_eps, passed, floor_regime,
                CASE WHEN rel IS NULL THEN NULL ELSE rel / rel_tol END AS q
            FROM t
        )
        SELECT is_eps, passed, {_band_sql(NEAR_MISS_FRACTION)} AS band, count(*) AS n
        FROM q
        GROUP BY 1, 2, 3
    """
    return duck.fetch_dicts(query)


def tolerance_report(storage: Storage) -> dict[str, Any]:
    """Measure how close the passing checks in the lake sit to the flat tolerance line.

    Scans every `statement_checks` partition. On a local lake this is quick; on a remote lake it is a
    whole-table scan and should be run against a local copy (see steps.md, Part 9).
    """
    duck = Duck(storage)
    try:
        if not duck.view("sc", f"{layout.STATEMENT_CHECKS}/*/*.parquet"):
            return {"total": 0, "message": "no statement_checks in the lake"}
        rows = _rows(duck)
    finally:
        duck.close()
    return _assemble(rows)


def _assemble(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Turn the grouped counts into a report. Kept pure so it can be tested on its own."""
    total = sum(r["n"] for r in rows)
    report: dict[str, Any] = {"total": total}
    for kind, is_eps in (("standard", False), ("eps", True)):
        sub = [r for r in rows if bool(r["is_eps"]) == is_eps]
        passes = {r["band"]: r["n"] for r in sub if r["passed"]}
        fails = {r["band"]: r["n"] for r in sub if not r["passed"]}
        # passes the relative tolerance actually governs: the floor regime is a different rule
        governed = {b: passes.get(b, 0) for b in PASS_BANDS}
        governed_total = sum(governed.values())
        near_miss = governed.get("near-miss", 0)
        report[kind] = {
            "passes": sum(passes.values()),
            "fails": sum(fails.values()),
            "floor_passes": passes.get("floor", 0),
            "governed_passes": governed_total,
            "pass_bands": governed,
            "near_miss": near_miss,
            "near_miss_share": (near_miss / governed_total) if governed_total else 0.0,
            "fail_bands": {b: fails.get(b, 0) for b in FAIL_BANDS},
            "fail_floor": fails.get("fail-floor", 0),
        }
    report["verdict"] = _verdict(report)
    return report


def _verdict(report: dict[str, Any]) -> str:
    std = report["standard"]
    share = std["near_miss_share"]
    if std["governed_passes"] == 0:
        return "No passes are governed by the 0.5 % relative tolerance yet; nothing to judge."
    pct = share * 100
    if share > DANGER_SHARE_WARN:
        return (
            f"{pct:.2f} % of relative-tolerance passes are near misses (>{DANGER_SHARE_WARN * 100:.0f} %). "
            "The flat tolerance is likely hiding real breaks. Move step 9 (per-line tolerance) up the order."
        )
    return (
        f"{pct:.2f} % of relative-tolerance passes are near misses (<={DANGER_SHARE_WARN * 100:.0f} %). "
        "The flat tolerance looks harmless in practice; step 9 can wait."
    )


def format_report(report: dict[str, Any]) -> str:
    """Human-readable text for the CLI."""
    if report.get("total", 0) == 0:
        return report.get("message", "no checks found")
    lines = [f"Checks measured: {report['total']:,}", ""]
    for kind in ("standard", "eps"):
        r = report[kind]
        tol = "1 %" if kind == "eps" else "0.5 %"
        lines.append(f"[{kind}]  tolerance {tol}   passes {r['passes']:,}   fails {r['fails']:,}")
        gp = r["governed_passes"]
        lines.append(f"  passes on the absolute floor (small numbers, tolerance not binding): {r['floor_passes']:,}")
        lines.append(f"  passes governed by the relative tolerance: {gp:,}")
        for band in PASS_BANDS:
            n = r["pass_bands"][band]
            share = f"{(n / gp * 100):5.2f} %" if gp else "  -  "
            flag = "  <- near miss" if band == "near-miss" and n else ""
            lines.append(f"    q {band:>10}: {n:>10,}  {share}{flag}")
        fb = r["fail_bands"]
        lines.append(f"  fails by how far past the line: just-over {fb['just-over']:,}  "
                     f"2-10x {fb['2-10x']:,}  >10x {fb['>10x']:,}")
        lines.append("")
    lines.append(report["verdict"])
    return "\n".join(lines)
