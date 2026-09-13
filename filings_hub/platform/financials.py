"""Versioned financial evidence shared by integrations and research work products.

No inferred market data, normalization or investment estimates are introduced here.
The snapshot hash identifies returned content; it is not a claim to archive that content.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query

from filings_hub.db.database import Database
from filings_hub.export.grid import COLUMN_ORDERS, PERIOD_MODES, build_grid
from filings_hub.platform.contracts import issuer_id

METHODOLOGY_VERSION = "disclosure-statements/1"
LIMITATIONS = [
    "Availability uses SEC filing dates, inclusive through the selected date; intraday cutoffs are unsupported.",
    "Current company metadata and period mapping are used; this is not a historical database snapshot.",
    "Latest means the latest available comparative in the period spine, not comprehensive amendment reconstruction.",
    "Values retain the existing float64 source precision; content hashes do not certify accounting accuracy.",
]


def fingerprint(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def financial_snapshot(
    database: Database,
    cik: int,
    *,
    periods: list[str] | None = None,
    limit: int = 8,
    period_mode: str = "as_filed",
    presentation: str = "original",
    as_of: date | None = None,
    column_order: str = "newest_right",
) -> dict[str, Any]:
    if presentation not in ("original", "latest"):
        raise ValueError("presentation must be original or latest")
    if presentation == "latest" and period_mode in ("quarterly", "ltm"):
        raise ValueError("latest presentation is supported only in as_filed and annual modes")
    grid = build_grid(
        database,
        cik,
        periods,
        limit,
        period_mode=period_mode,
        restated=presentation == "latest",
        column_order=column_order,
        as_of=as_of,
    ).to_dict()
    payload = {"methodology_version": METHODOLOGY_VERSION, "issuer_id": issuer_id(cik), "grid": grid}
    return {
        "api_version": "v1",
        "snapshot_id": fingerprint(payload),
        **payload,
        "presentation": presentation,
        "limitations": LIMITATIONS,
    }


def _cells(snapshot: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    cells = {}
    for statement in snapshot["grid"]["statements"]:
        for line in statement["lines"]:
            if line["is_abstract"]:
                continue
            for period, value in line["values"].items():
                cells[statement["code"], line["key"], period] = {
                    "statement": statement["code"],
                    "line_key": line["key"],
                    "concept": line["concept"],
                    "label": line["labels"].get(period, line["label"]),
                    "period": period,
                    "unit": line["unit"],
                    "value": value,
                    "evidence": line["value_metadata"].get(period, {}),
                }
    return cells


def _context(cell: dict[str, Any]) -> tuple:
    return tuple(
        sorted(
            {
                ((s.get("taxonomy") or "").split("/")[0], s.get("period_start"), s.get("period_end"), s.get("qtrs"))
                for s in cell["evidence"].get("sources", [])
            },
            key=str,
        )
    )


def _align_unique_concepts(left, right):
    """Labels are presentation, not identity. Never guess which repeated concept occurrence moved."""

    def grouped(cells):
        groups = defaultdict(list)
        for key, cell in cells.items():
            groups[(cell["statement"], cell["concept"], cell["period"], cell["unit"], _context(cell))].append(key)
        return groups

    a, b = grouped(left), grouped(right)
    aligned = dict(right)
    for signature, left_keys in a.items():
        right_keys = b.get(signature, [])
        if len(left_keys) == len(right_keys) == 1:
            old_key, new_key = left_keys[0], right_keys[0]
            if old_key != new_key and old_key not in right and new_key not in left:
                aligned[old_key] = aligned.pop(new_key)
    return aligned


def compare_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    left, right = _cells(before), _cells(after)
    right = _align_unique_concepts(left, right)
    changes = []
    common_periods = {p["period_label"] for p in before["grid"]["periods"]} & {
        p["period_label"] for p in after["grid"]["periods"]
    }
    # Compare only overlapping periods. A newly filed period is a new observation, not a restatement.
    for key in sorted(left.keys() | right.keys()):
        if key[2] not in common_periods:
            continue
        old, new = left.get(key), right.get(key)
        if (
            old
            and new
            and {k: v for k, v in old.items() if k != "line_key"} == {k: v for k, v in new.items() if k != "line_key"}
        ):
            continue
        kind = "added_line" if old is None else "removed_line" if new is None else "evidence_changed"
        delta = None
        if old and new:
            if old["unit"] != new["unit"]:
                kind = "unit_changed"
            elif _context(old) != _context(new) and old["value"] is not None and new["value"] is not None:
                kind = "context_changed"
            elif old["value"] != new["value"]:
                kind = "value_changed"
                if old["value"] is not None and new["value"] is not None:
                    delta = new["value"] - old["value"]
            elif old["label"] != new["label"]:
                kind = "label_changed"
        changes.append({"kind": kind, "before": old, "after": new, "delta": delta})
    return {
        "api_version": "v1",
        "before_snapshot_id": before["snapshot_id"],
        "after_snapshot_id": after["snapshot_id"],
        "compared_periods": sorted(common_periods),
        "changes": changes,
        "count": len(changes),
        "limitations": LIMITATIONS,
    }


def attach_financial_routes(app: FastAPI, *, database: Database, auth, resolve_cik) -> None:
    @app.get("/v1/companies/{cik}/financials")
    def financials(
        cik: str,
        periods: str | None = None,
        limit: int = Query(8, ge=1, le=60),
        period_mode: str = "as_filed",
        presentation: Literal["original", "latest"] = "original",
        as_of: date | None = None,
        column_order: str = "newest_right",
        _: str = Depends(auth),
    ) -> dict[str, Any]:
        if period_mode not in PERIOD_MODES or column_order not in COLUMN_ORDERS:
            raise HTTPException(422, "unsupported period mode or column order")
        try:
            return financial_snapshot(
                database,
                resolve_cik(cik),
                periods=[p.strip() for p in periods.split(",") if p.strip()] if periods else None,
                limit=limit,
                period_mode=period_mode,
                presentation=presentation,
                as_of=as_of,
                column_order=column_order,
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/v1/companies/{cik}/financial-changes")
    def financial_changes(
        cik: str,
        before: date,
        after: date,
        periods: str | None = None,
        limit: int = Query(20, ge=1, le=60),
        _: str = Depends(auth),
    ) -> dict[str, Any]:
        if after < before:
            raise HTTPException(422, "after must be on or after before")
        c = resolve_cik(cik)
        labels = [p.strip() for p in periods.split(",") if p.strip()] if periods else None
        try:
            with database.read_snapshot() as reader:
                left = financial_snapshot(reader, c, periods=labels, limit=limit, presentation="latest", as_of=before)
                right = financial_snapshot(reader, c, periods=labels, limit=limit, presentation="latest", as_of=after)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        result = compare_snapshots(left, right)
        result.update({"cik": c, "before": before, "after": after})
        return result
