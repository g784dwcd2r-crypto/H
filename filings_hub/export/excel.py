"""Excel export: one sheet per statement, periods as columns (newest right), as-reported lines as rows.

Numbers are numbers, negatives are negative, no formulas. A `Source` sheet lists the filing behind
every column.
"""

from __future__ import annotations

import io
import re
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from filings_hub.db.database import Database
from filings_hub.export.grid import Grid, build_grid

MONEY_FMT = '#,##0;(#,##0);"-"'
PER_SHARE_FMT = '0.00;(0.00);"-"'
SHARES_FMT = '#,##0;(#,##0);"-"'
PCT_FMT = "0.0%"

HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
HEADER_FONT = Font(bold=True, color="FFFFFF")
SUBTOTAL_FONT = Font(bold=True)
ABSTRACT_FONT = Font(bold=True, italic=True, color="1F3A5F")
PROVISIONAL_FILL = PatternFill("solid", fgColor="FFF4CE")
THIN = Side(style="thin", color="999999")


def _number_format(unit: str | None) -> str:
    if not unit:
        return MONEY_FMT
    u = unit.lower()
    if "/" in u:  # USD/shares
        return PER_SHARE_FMT
    if u in ("shares", "pure", "ratio"):
        return SHARES_FMT if u == "shares" else "0.0000"
    return MONEY_FMT


def _sheet_title(name: str) -> str:
    return re.sub(r"[\[\]\*\?/\\:]", "", name)[:31]


def _write_statement(wb: Workbook, grid: Grid, code: str, name: str, lines: list[Any]) -> None:
    ws = wb.create_sheet(_sheet_title(name))
    periods = grid.periods
    ws["A1"] = grid.company_name + (f" ({grid.ticker})" if grid.ticker else "")
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = f"{name} - as reported (XBRL, full units; USD unless the Unit column says otherwise)"
    ws["A2"].font = Font(italic=True, color="555555")

    header_row = 4
    ws.cell(header_row, 1, "Line item")
    ws.cell(header_row, 2, "Concept")
    ws.cell(header_row, 3, "Unit")
    for j, p in enumerate(periods):
        c = ws.cell(header_row, 4 + j, p.period_label)
        if p.is_provisional:
            c.value = f"{p.period_label} (provisional)"
    for col in range(1, 4 + len(periods)):
        cell = ws.cell(header_row, col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center" if col > 3 else "left", vertical="center")
    ws.cell(header_row + 1, 1, "Period end")
    ws.cell(header_row + 2, 1, "Filing")
    for j, p in enumerate(periods):
        ws.cell(header_row + 1, 4 + j, p.period_end).number_format = "yyyy-mm-dd"
        ws.cell(header_row + 2, 4 + j, f"{p.form or ''} {p.accession}".strip())
        for r in (header_row + 1, header_row + 2):
            ws.cell(r, 4 + j).alignment = Alignment(horizontal="center")
            ws.cell(r, 4 + j).font = Font(color="555555", size=9)

    row = header_row + 3
    for ln in lines:
        ws.cell(row, 1, ln.label)
        ws.cell(row, 2, ln.concept)
        ws.cell(row, 3, None if ln.is_abstract else ln.unit)
        if ln.is_abstract:
            ws.cell(row, 1).font = ABSTRACT_FONT
        elif ln.is_subtotal:
            for col in range(1, 4 + len(periods)):
                ws.cell(row, col).font = SUBTOTAL_FONT
            ws.cell(row, 1).border = Border(top=THIN)
        if not ln.is_abstract:
            fmt = _number_format(ln.unit)
            for j, p in enumerate(periods):
                v = ln.values.get(p.period_label)
                cell = ws.cell(row, 4 + j, v)
                cell.number_format = fmt
                if ln.is_subtotal:
                    cell.font = SUBTOTAL_FONT
                    cell.border = Border(top=THIN)
                if p.is_provisional:
                    cell.fill = PROVISIONAL_FILL
        row += 1

    ws.column_dimensions["A"].width = 58
    ws.column_dimensions["B"].hidden = True
    ws.column_dimensions["C"].width = 11
    for j in range(len(periods)):
        ws.column_dimensions[get_column_letter(4 + j)].width = 18
    ws.freeze_panes = ws.cell(header_row + 3, 4)
    ws.sheet_view.showGridLines = False


def _write_source(wb: Workbook, grid: Grid) -> None:
    ws = wb.create_sheet("Source")
    headers = [
        "Period",
        "Period end",
        "Form",
        "Accession",
        "Filed",
        "Filing index",
        "Primary document",
        "Earnings release (8-K 2.02)",
        "Statements source",
        "Arithmetic checks",
    ]
    for j, h in enumerate(headers, 1):
        c = ws.cell(1, j, h)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
    for i, p in enumerate(grid.periods, 2):
        ws.cell(i, 1, p.period_label)
        ws.cell(i, 2, p.period_end).number_format = "yyyy-mm-dd"
        ws.cell(i, 3, p.form)
        ws.cell(i, 4, p.accession)
        if p.filed_date:
            ws.cell(i, 5, p.filed_date).number_format = "yyyy-mm-dd"
        if p.filing_index_url:
            ws.cell(i, 6, p.filing_index_url).hyperlink = p.filing_index_url
        if p.primary_doc_url:
            ws.cell(i, 7, p.primary_doc_url).hyperlink = p.primary_doc_url
        if p.earnings_release_url:
            ws.cell(i, 8, p.earnings_release_url).hyperlink = p.earnings_release_url
        ws.cell(
            i,
            9,
            "SEC Financial Statement Data Sets"
            if p.statements_source == "fsds"
            else (
                "provisional (built from XBRL facts; FSDS not yet published)"
                if p.statements_source == "facts_fallback"
                else "none"
            ),
        )
        ws.cell(i, 10, {True: "passed", False: "FAILED", None: "n/a"}[p.checks_passed])
    ws.cell(
        len(grid.periods) + 3,
        1,
        "Source: SEC EDGAR (https://www.sec.gov). Values are the XBRL-reported amounts in full units; "
        "labels and line order are the company's own as filed. Provisional columns are rebuilt from the SEC's "
        "Financial Statement Data Sets when the quarter is published.",
    )
    for j, w in enumerate([12, 12, 8, 24, 12, 60, 60, 60, 40, 16], 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = "A2"


def workbook_from_grid(grid: Grid) -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)
    for s in grid.statements:
        _write_statement(wb, grid, s.code, s.name, s.lines)
    if not grid.statements:
        ws = wb.create_sheet("No statements")
        ws["A1"] = f"No as-reported statements available for {grid.company_name} in the requested periods."
    _write_source(wb, grid)
    wb.properties.title = f"{grid.company_name} - as-reported statements"
    wb.properties.creator = "filings-hub"
    return wb


def export_excel(db: Database, cik: int, period_labels: list[str] | None = None, limit: int = 8) -> bytes:
    grid = build_grid(db, cik, period_labels, limit)
    wb = workbook_from_grid(grid)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
