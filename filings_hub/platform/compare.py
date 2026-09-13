"""Explicit concept comparisons with visible missingness and reporting context."""

from datetime import date
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query

from filings_hub.platform.financials import financial_snapshot


def compare_companies(database, ciks: list[int], concept: str, period: str, statement: str, as_of: date | None = None):
    with database.read_snapshot() as reader:
        return _compare_companies(reader, ciks, concept, period, statement, as_of)


def _compare_companies(database, ciks, concept, period, statement, as_of):
    results = []
    for cik in dict.fromkeys(ciks):
        try:
            snapshot = financial_snapshot(database, cik, periods=[period], limit=1, as_of=as_of)
        except KeyError:
            results.append({"cik": cik, "company": None, "status": "unavailable", "reason": "Company not found."})
            continue
        grid = snapshot["grid"]
        candidates = [
            line
            for block in grid["statements"]
            if block["code"] == statement
            for line in block["lines"]
            if line["concept"] == concept and not line["is_abstract"] and line["values"].get(period) is not None
        ]
        row: dict[str, Any] = {
            "cik": cik,
            "company": grid["company_name"],
            "ticker": grid["ticker"],
            "period": grid["periods"][0] if grid["periods"] else None,
            "snapshot_id": snapshot["snapshot_id"],
            "value": None,
            "unit": None,
            "evidence": None,
        }
        if len(candidates) == 1:
            line = candidates[0]
            row.update(
                {
                    "status": "available",
                    "label": line["labels"].get(period, line["label"]),
                    "value": line["values"][period],
                    "unit": line["unit"],
                    "evidence": line["value_metadata"].get(period),
                }
            )
        else:
            reason = "The selected concept is not reported in this period."
            if not grid["periods"]:
                reason = "The selected period is unavailable at this filing-date cutoff."
            elif candidates:
                reason = "Multiple statement lines use this concept; select the exact line in the company statements."
            row.update({"status": "ambiguous" if candidates else "unavailable", "reason": reason})
        results.append(row)
    available = [r for r in results if r["status"] == "available"]
    units = sorted({r["unit"] for r in available if r["unit"]})
    ends = sorted({r["period"]["period_end"] for r in available})
    return {
        "api_version": "v1",
        "concept": concept,
        "period": period,
        "statement": statement,
        "as_of": as_of,
        "results": results,
        "units": units,
        "period_ends": ends,
        "notes": [
            "Values use the exact selected XBRL concept. They are not a standardized sector metric.",
            "Fiscal periods, currencies and statement contexts are retained. No FX conversion or ranking is applied.",
        ]
        + (["Companies have different fiscal period ends."] if len(ends) > 1 else [])
        + (["Values use different units or currencies and cannot be directly combined."] if len(units) > 1 else []),
    }


def attach_compare_routes(app: FastAPI, *, database, auth, resolve_cik):
    @app.get("/v1/compare")
    def compare(
        companies: str = Query(min_length=1, max_length=250),
        concept: str = Query(min_length=1, max_length=250),
        period: str = Query(min_length=1, max_length=40),
        statement: str = "IS",
        as_of: date | None = None,
        _: str = Depends(auth),
    ):
        ids = list(dict.fromkeys(x.strip() for x in companies.split(",") if x.strip()))
        if not 1 <= len(ids) <= 12:
            raise HTTPException(422, "choose between 1 and 12 companies")
        if statement not in ("IS", "BS", "CF"):
            raise HTTPException(422, "statement must be IS, BS or CF")
        return compare_companies(database, [resolve_cik(c) for c in ids], concept, period, statement, as_of)
