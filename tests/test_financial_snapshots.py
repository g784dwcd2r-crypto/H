import io
from copy import deepcopy
from datetime import date

import pytest
from openpyxl import load_workbook

from filings_hub.export.excel import export_excel
from filings_hub.export.grid import build_grid
from filings_hub.platform.financials import compare_snapshots, financial_snapshot
from filings_hub.testing import edgar_fixtures as fx


@pytest.mark.parametrize("mode", ["as_filed", "annual", "quarterly", "ltm"])
def test_cutoff_applies_to_columns_comparatives_and_all_operands(db, mode):
    cutoff = date(2025, 11, 15)
    grid = build_grid(db, fx.APPLE, limit=60, period_mode=mode, restated=True, as_of=cutoff)
    assert grid.periods
    assert all(p.filed_date <= cutoff for p in grid.periods)
    for stmt in grid.statements:
        for line in stmt.lines:
            for evidence in line.value_metadata.values():
                for source in evidence["sources"]:
                    assert source["filed_date"] and date.fromisoformat(source["filed_date"]) <= cutoff
    assert build_grid(db, fx.APPLE, as_of=date(1900, 1, 1)).periods == []


def test_snapshot_is_reproducible_and_matches_statement_values(db):
    options = {"as_of": date(2025, 11, 15), "presentation": "latest"}
    left = financial_snapshot(db, fx.APPLE, **options)
    assert left == financial_snapshot(db, fx.APPLE, **options)
    assert left["grid"] == build_grid(db, fx.APPLE, as_of=options["as_of"], restated=True).to_dict()
    assert left["snapshot_id"] != financial_snapshot(db, fx.APPLE)["snapshot_id"]
    assert compare_snapshots(left, left)["changes"] == []
    with pytest.raises(ValueError, match="latest presentation"):
        financial_snapshot(db, fx.APPLE, period_mode="ltm", presentation="latest")


def _snapshot(value, unit="USD", accession="a"):
    return {
        "snapshot_id": accession,
        "grid": {
            "periods": [{"period_label": "FY2024"}],
            "statements": [
                {
                    "code": "IS",
                    "lines": [
                        {
                            "key": "Revenue",
                            "concept": "Revenue",
                            "label": "Sales",
                            "labels": {},
                            "unit": unit,
                            "is_abstract": False,
                            "values": {"FY2024": value},
                            "value_metadata": {"FY2024": {"sources": [{"accession": accession}]}},
                        }
                    ],
                }
            ],
        },
    }


def test_change_review_never_subtracts_missing_values_or_different_currencies():
    changed = compare_snapshots(_snapshot(100), _snapshot(125, accession="b"))["changes"][0]
    assert changed["kind"] == "value_changed" and changed["delta"] == 25
    assert changed["before"]["evidence"]["sources"][0]["accession"] == "a"
    assert changed["after"]["evidence"]["sources"][0]["accession"] == "b"
    assert compare_snapshots(_snapshot(100), _snapshot(125, unit="EUR"))["changes"][0]["delta"] is None
    assert compare_snapshots(_snapshot(None), _snapshot(125))["changes"][0]["delta"] is None


def test_export_records_availability_cutoff(db):
    data = export_excel(db, fx.APPLE, as_of=date(2025, 11, 15))
    workbook = load_workbook(io.BytesIO(data))
    assert any(
        "Availability cutoff: filings dated on or before 2025-11-15" in str(cell.value)
        for row in workbook["Source"]
        for cell in row
    )


def test_label_alias_changes_do_not_invent_added_and_removed_lines():
    before = _snapshot(100)
    after = deepcopy(before)
    line = after["grid"]["statements"][0]["lines"][0]
    line["key"] = "Revenue|new presentation alias"
    assert compare_snapshots(before, after)["changes"] == []
    line["label"] = "New sales label"
    changes = compare_snapshots(before, after)["changes"]
    assert len(changes) == 1 and changes[0]["kind"] == "label_changed"
