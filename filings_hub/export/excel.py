"""Excel export: statements as sheets (or one sheet), periods across (or down), as-reported lines.

Numbers are numbers and negatives are negative. Subtotals are values unless the export asks for
formulas, and a formula is written only where the children really add up to the reported total, so
the workbook never shows a number the company did not report. A `Source` sheet lists the filing
behind every column and the basis of each column (as filed, derived, restated).
"""

from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from filings_hub.db.database import Database
from filings_hub.export.grid import COLUMN_ORDERS, PERIOD_MODES, Grid, GridLine, PeriodColumn, build_grid
from filings_hub.ingest.sync_statements import CORE_STATEMENTS, STATEMENT_NAMES

LAYOUTS = ("sheet_per_statement", "one_sheet")
ORIENTATIONS = ("periods_across", "periods_down")
SUBTOTAL_STYLES = ("values", "formulas")
SCALES = {"units": 1.0, "thousands": 1e3, "millions": 1e6, "billions": 1e9}
NEGATIVE_STYLES = ("parentheses", "minus")
FILENAME_FIELDS = ("ticker", "cik", "name", "mode", "date", "periods")

HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
HEADER_FONT = Font(bold=True, color="FFFFFF")
SUBTOTAL_FONT = Font(bold=True)
ABSTRACT_FONT = Font(bold=True, italic=True, color="1F3A5F")
PROVISIONAL_FILL = PatternFill("solid", fgColor="FFF4CE")
DERIVED_FILL = PatternFill("solid", fgColor="E8F0FB")
THIN = Side(style="thin", color="999999")


@dataclass
class ExportOptions:
    """Everything about the workbook that is a matter of taste. All fields have safe defaults."""

    layout: str = "sheet_per_statement"
    orientation: str = "periods_across"
    subtotals: str = "values"
    include_source: bool = True
    include_checks: bool = True
    include_concepts: bool = True
    include_filed_dates: bool = True
    scale: str = "units"
    negative_style: str = "parentheses"
    filename: str = "{ticker}-statements"
    statements: tuple[str, ...] = CORE_STATEMENTS

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> ExportOptions:
        """Build from loosely typed input (query params, a saved profile); raises ValueError."""
        d = dict(d or {})
        opts = cls()
        for k in ("layout", "orientation", "subtotals", "scale", "negative_style", "filename"):
            if d.get(k) not in (None, ""):
                setattr(opts, k, str(d[k]))
        for k in ("include_source", "include_checks", "include_concepts", "include_filed_dates"):
            if k in d and d[k] is not None:
                v = d[k]
                setattr(opts, k, v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on"))
        st = d.get("statements")
        if st:
            codes = [s.strip().upper() for s in (st.split(",") if isinstance(st, str) else st) if str(s).strip()]
            opts.statements = tuple(codes)
        problem = opts.validate()
        if problem:
            raise ValueError(problem)
        return opts

    def validate(self) -> str | None:
        if self.layout not in LAYOUTS:
            return f"layout must be one of {', '.join(LAYOUTS)}"
        if self.orientation not in ORIENTATIONS:
            return f"orientation must be one of {', '.join(ORIENTATIONS)}"
        if self.subtotals not in SUBTOTAL_STYLES:
            return f"subtotals must be one of {', '.join(SUBTOTAL_STYLES)}"
        if self.scale not in SCALES:
            return f"scale must be one of {', '.join(SCALES)}"
        if self.negative_style not in NEGATIVE_STYLES:
            return f"negative_style must be one of {', '.join(NEGATIVE_STYLES)}"
        if not self.statements or any(s not in STATEMENT_NAMES for s in self.statements):
            return f"statements must be among {', '.join(STATEMENT_NAMES)}"
        if len(self.filename) > 120:
            return "filename pattern too long"
        bad = [m for m in re.findall(r"\{(\w*)\}", self.filename) if m not in FILENAME_FIELDS]
        if bad:
            return f"filename may use {{{'}, {'.join(FILENAME_FIELDS)}}}; not {{{bad[0]}}}"
        return None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["statements"] = list(self.statements)
        return d

    def resolved_filename(self, grid: Grid, today: date | None = None) -> str:
        fields = {
            "ticker": grid.ticker or str(grid.cik),
            "cik": str(grid.cik),
            "name": re.sub(r"[^A-Za-z0-9]+", "-", grid.company_name).strip("-")[:40],
            "mode": grid.period_mode + ("-restated" if grid.restated else ""),
            "date": (today or date.today()).isoformat(),
            "periods": str(len(grid.periods)),
        }
        name = self.filename
        for k, v in fields.items():
            name = name.replace("{" + k + "}", v)
        name = re.sub(r"[^A-Za-z0-9._ -]+", "", name).strip() or f"{grid.cik}-statements"
        return name if name.lower().endswith(".xlsx") else name + ".xlsx"


def _fmt(unit: str | None, opts: ExportOptions) -> str:
    """Excel number format for a line: per-share and ratios are never scaled."""
    u = (unit or "").lower()
    neg = lambda pos: f"{pos};({pos})" if opts.negative_style == "parentheses" else f"{pos};-{pos}"  # noqa: E731
    if "/" in u:
        return neg("0.00") + ';"-"'
    if u in ("pure", "ratio"):
        return neg("0.0000") + ';"-"'
    if opts.scale != "units" and u != "shares":
        return neg("#,##0.0") + ';"-"'
    return neg("#,##0") + ';"-"'


def _scaled(v: float | None, unit: str | None, opts: ExportOptions) -> float | None:
    if v is None:
        return None
    u = (unit or "").lower()
    if "/" in u or u in ("pure", "ratio", "shares"):
        return v
    return v / SCALES[opts.scale]


def _sheet_title(name: str) -> str:
    return re.sub(r"[\[\]\*\?/\\:]", "", name)[:31]


def _header_cell(ws: Worksheet, row: int, col: int, value: Any, align: str = "center") -> None:
    c = ws.cell(row, col, value)
    c.fill = HEADER_FILL
    c.font = HEADER_FONT
    c.alignment = Alignment(horizontal=align, vertical="center")


def _period_header(p: PeriodColumn) -> str:
    label = p.period_label
    if p.is_provisional:
        label += " (provisional)"
    if p.basis == "restated":
        label += " (restated)"
    return label


def _children(lines: list[GridLine], subtotal: GridLine) -> list[GridLine]:
    return [ln for ln in lines if ln.parent_concept == subtotal.concept and not ln.is_abstract and ln is not subtotal]


def _adds_up(total: float | None, parts: list[float | None]) -> bool:
    if total is None or not parts or any(v is None for v in parts):
        return False
    s = sum(v for v in parts if v is not None)
    return abs(s - total) <= 1.0 + 1e-6 * abs(total)


def _subtitle(name: str, opts: ExportOptions) -> str:
    scale_note = "full units" if opts.scale == "units" else f"in {opts.scale}; per-share amounts and shares unscaled"
    return f"{name} - as reported (XBRL, {scale_note}; USD unless the Unit column says otherwise)"


def _write_block(
    ws: Worksheet, grid: Grid, heading: str, name: str, lines: list[GridLine], top: int, opts: ExportOptions
) -> int:
    """Write one statement: heading at row `top`, header row at `top + 3`; returns the next free row."""
    periods = grid.periods
    ws.cell(top, 1, heading).font = Font(bold=True, size=13)
    ws.cell(top + 1, 1, _subtitle(name, opts)).font = Font(italic=True, color="555555")
    header = top + 3
    cells: dict[tuple[str, str], str] = {}  # (line key, period label) -> cell ref, for formulas
    if opts.orientation == "periods_across":
        fixed = ["Line item"] + (["Concept"] if opts.include_concepts else []) + ["Unit"]
        for j, h in enumerate(fixed, 1):
            _header_cell(ws, header, j, h, "left")
        first = len(fixed) + 1
        for j, p in enumerate(periods):
            _header_cell(ws, header, first + j, _period_header(p))
        sub = header + 1
        ws.cell(sub, 1, "Period end")
        for j, p in enumerate(periods):
            ws.cell(sub, first + j, p.period_end).number_format = "yyyy-mm-dd"
        if opts.include_filed_dates:
            ws.cell(sub + 1, 1, "Filing")
            for j, p in enumerate(periods):
                ws.cell(sub + 1, first + j, f"{p.form or ''} {p.accession}".strip())
        for r in range(sub, sub + (2 if opts.include_filed_dates else 1)):
            for j in range(len(periods)):
                ws.cell(r, first + j).alignment = Alignment(horizontal="center")
                ws.cell(r, first + j).font = Font(color="555555", size=9)
        row = sub + (2 if opts.include_filed_dates else 1)
        for ln in lines:
            for j, p in enumerate(periods):
                cells[(ln.key, p.period_label)] = f"{get_column_letter(first + j)}{row}"
            row += 1
        row = sub + (2 if opts.include_filed_dates else 1)
        for ln in lines:
            ws.cell(row, 1, ln.label)
            if opts.include_concepts:
                ws.cell(row, 2, ln.concept)
            ws.cell(row, len(fixed), None if ln.is_abstract else ln.unit)
            if ln.is_abstract:
                ws.cell(row, 1).font = ABSTRACT_FONT
            elif ln.is_subtotal:
                for col in range(1, first + len(periods)):
                    ws.cell(row, col).font = SUBTOTAL_FONT
                ws.cell(row, 1).border = Border(top=THIN)
            if not ln.is_abstract:
                _write_values(ws, grid, lines, ln, opts, cells, lambda j, r=row: (r, first + j))
            row += 1
        ws.column_dimensions["A"].width = 58
        if opts.include_concepts:
            ws.column_dimensions["B"].hidden = True
        ws.column_dimensions[get_column_letter(len(fixed))].width = 11
        for j in range(len(periods)):
            ws.column_dimensions[get_column_letter(first + j)].width = 18
        if ws.freeze_panes is None:
            ws.freeze_panes = ws.cell(sub + (2 if opts.include_filed_dates else 1), first)
        return row + 1
    # periods down: one row per period, one column per line
    _header_cell(ws, header, 1, "Period", "left")
    _header_cell(ws, header, 2, "Period end", "left")
    ncol = 3
    if opts.include_filed_dates:
        _header_cell(ws, header, 3, "Filing", "left")
        ncol = 4
    body = [ln for ln in lines if not ln.is_abstract]
    for j, ln in enumerate(body):
        _header_cell(ws, header, ncol + j, ln.label + (f" ({ln.unit})" if ln.unit and ln.unit != "USD" else ""))
        if opts.include_concepts:
            ws.cell(header + 1, ncol + j, ln.concept).font = Font(color="555555", size=9)
        ws.column_dimensions[get_column_letter(ncol + j)].width = 20
    start = header + (2 if opts.include_concepts else 1)
    for i, p in enumerate(periods):
        for j, ln in enumerate(body):
            cells[(ln.key, p.period_label)] = f"{get_column_letter(ncol + j)}{start + i}"
    for i, p in enumerate(periods):
        r = start + i
        ws.cell(r, 1, _period_header(p))
        ws.cell(r, 2, p.period_end).number_format = "yyyy-mm-dd"
        if opts.include_filed_dates:
            ws.cell(r, 3, f"{p.form or ''} {p.accession}".strip())
        for j, ln in enumerate(body):
            _write_values(ws, grid, lines, ln, opts, cells, lambda jj, r=r, j=j: (r, ncol + j), only=i)
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 12
    if opts.include_filed_dates:
        ws.column_dimensions["C"].width = 26
    if ws.freeze_panes is None:
        ws.freeze_panes = ws.cell(start, ncol)
    return start + len(periods) + 1


def _write_values(ws, grid: Grid, lines, ln: GridLine, opts: ExportOptions, cells, at, only: int | None = None) -> None:
    fmt = _fmt(ln.unit, opts)
    kids = _children(lines, ln) if opts.subtotals == "formulas" and ln.is_subtotal else []
    for j, p in enumerate(grid.periods):
        if only is not None and j != only:
            continue
        v = ln.values.get(p.period_label)
        r, c = at(j)
        cell = ws.cell(r, c)
        metadata = ln.value_metadata.get(p.period_label)
        if metadata and opts.include_source:
            notes = [metadata["status"].replace("_", " ")]
            for k in ("reason", "formula"):
                if metadata.get(k):
                    notes.append(metadata[k])
            for source in metadata.get("sources", []):
                if source.get("label") and source["label"] != ln.label:
                    notes.append(f"Reported label: {source['label']}")
                notes.append(
                    f"{source['accession']} · {source['concept']} · "
                    f"{source.get('period_start') or 'instant'} to {source.get('period_end') or 'unknown'} · "
                    f"{source.get('value')} {source.get('unit') or ''}"
                    + (f" · coefficient {source['coefficient']}" if "coefficient" in source else "")
                )
                if source.get("document_url"):
                    notes.append(source["document_url"])
                if source.get("unit_note"):
                    notes.append(source["unit_note"])
                if source.get("date_note"):
                    notes.append(source["date_note"])
            cell.comment = Comment("\n".join(notes), "Disclosure")
        if kids and _adds_up(v, [k.values.get(p.period_label) for k in kids]):
            cell.value = "=" + "+".join(cells[(k.key, p.period_label)] for k in kids)
        else:
            cell.value = _scaled(v, ln.unit, opts)
        cell.number_format = fmt
        if ln.is_subtotal:
            cell.font = SUBTOTAL_FONT
            cell.border = Border(top=THIN)
        if p.is_provisional:
            cell.fill = PROVISIONAL_FILL
        elif p.basis == "derived":
            cell.fill = DERIVED_FILL


def _basis_words(p: PeriodColumn) -> str:
    if p.basis == "derived":
        return f"derived: {p.basis_note}" if p.basis_note else "derived"
    if p.basis == "restated":
        return f"restated, {p.basis_note}" if p.basis_note else "restated"
    return "as filed"


def _write_source(wb: Workbook, grid: Grid, opts: ExportOptions) -> None:
    ws = wb.create_sheet("Source")
    headers = ["Period", "Period end", "Basis", "Form", "Accession", "Filed", "Filing index", "Primary document"]
    headers += ["Earnings release (8-K 2.02)", "Statements source"]
    if opts.include_checks:
        headers.append("Arithmetic checks")
    for j, h in enumerate(headers, 1):
        _header_cell(ws, 1, j, h, "left")
    for i, p in enumerate(grid.periods, 2):
        ws.cell(i, 1, p.period_label)
        ws.cell(i, 2, p.period_end).number_format = "yyyy-mm-dd"
        ws.cell(i, 3, _basis_words(p))
        ws.cell(i, 4, p.form)
        ws.cell(i, 5, p.accession)
        if p.filed_date:
            ws.cell(i, 6, p.filed_date).number_format = "yyyy-mm-dd"
        if p.filing_index_url:
            ws.cell(i, 7, p.filing_index_url).hyperlink = p.filing_index_url
        if p.primary_doc_url:
            ws.cell(i, 8, p.primary_doc_url).hyperlink = p.primary_doc_url
        if p.earnings_release_url:
            ws.cell(i, 9, p.earnings_release_url).hyperlink = p.earnings_release_url
        ws.cell(
            i,
            10,
            "SEC Financial Statement Data Sets"
            if p.statements_source == "fsds"
            else (
                "provisional (built from XBRL facts; FSDS not yet published)"
                if p.statements_source == "facts_fallback"
                else "none"
            ),
        )
        if opts.include_checks:
            ws.cell(i, 11, {True: "passed", False: "FAILED", None: "n/a"}[p.checks_passed])
    note = (
        "Source: SEC EDGAR (https://www.sec.gov). Values are the XBRL-reported amounts; labels and line order "
        "are the company's own as filed. Provisional columns are rebuilt from the SEC's Financial Statement Data "
        "Sets when the quarter is published."
    )
    if grid.period_mode == "quarterly":
        note += (
            " Quarterly mode: year-to-date statements (cash flow) are shown as differences of consecutive "
            "year-to-date columns; Q4 is the fiscal year less the nine months when inputs are compatible. "
            "Only validated additive concepts are derived. Per-share amounts, weighted averages and "
            "unsupported calculations remain blank unless directly reported. Cell comments explain each value."
        )
    elif grid.period_mode == "ltm":
        note += (
            " LTM: twelve months to each quarter end = year to date + prior fiscal year - prior year to date. "
            "Only validated additive concepts and compatible periods are combined. Per-share amounts, "
            "weighted averages and unsupported calculations remain blank unless directly reported. "
            "Cell comments identify all source inputs and coefficients."
        )
    if grid.restated:
        note += (
            " Latest-presentation mode uses the newest available later comparative for each line; this does "
            "not establish that a formal restatement occurred. Cell comments identify the actual source, "
            "including original values retained when later filings omit a line."
        )
    if grid.as_of is not None:
        note += (
            f" Availability cutoff: filings dated on or before {grid.as_of.isoformat()}. "
            "This is filing-date resolution, not intraday availability or an archived database snapshot."
        )
    if opts.subtotals == "formulas":
        note += " Subtotals are formulas where the reported children add up to the reported total, values otherwise."
    ws.cell(len(grid.periods) + 3, 1, note)
    for j, w in enumerate([14, 12, 44, 8, 24, 12, 60, 60, 60, 40, 16], 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = "A2"


def workbook_from_grid(grid: Grid, options: ExportOptions | None = None) -> Workbook:
    opts = options or ExportOptions()
    wb = Workbook()
    wb.remove(wb.active)
    title = grid.company_name + (f" ({grid.ticker})" if grid.ticker else "")
    if opts.layout == "one_sheet":
        ws = wb.create_sheet("Statements")
        row = 1
        for s in grid.statements:
            row = _write_block(ws, grid, f"{title} - {s.name}", s.name, s.lines, row, opts)
        ws.sheet_view.showGridLines = False
    else:
        for s in grid.statements:
            ws = wb.create_sheet(_sheet_title(s.name))
            _write_block(ws, grid, title, s.name, s.lines, 1, opts)
            ws.sheet_view.showGridLines = False
    if not grid.statements:
        ws = wb.create_sheet("No statements")
        ws["A1"] = f"No as-reported statements available for {grid.company_name} in the requested periods."
    if opts.include_source:
        _write_source(wb, grid, opts)
    wb.properties.title = f"{grid.company_name} - as-reported statements"
    wb.properties.creator = "Disclosure"
    return wb


def export_excel(
    db: Database,
    cik: int,
    period_labels: list[str] | None = None,
    limit: int = 8,
    options: ExportOptions | None = None,
    period_mode: str = "as_filed",
    restated: bool = False,
    column_order: str = "newest_right",
    as_of: date | None = None,
) -> bytes:
    return export_workbook(db, cik, period_labels, limit, options, period_mode, restated, column_order, as_of)[0]


def export_workbook(
    db: Database,
    cik: int,
    period_labels: list[str] | None = None,
    limit: int = 8,
    options: ExportOptions | None = None,
    period_mode: str = "as_filed",
    restated: bool = False,
    column_order: str = "newest_right",
    as_of: date | None = None,
) -> tuple[bytes, str]:
    """The workbook bytes and the file name the options resolve to."""
    opts = options or ExportOptions()
    if period_mode not in PERIOD_MODES or column_order not in COLUMN_ORDERS:
        raise ValueError("bad period_mode or column_order")
    grid = build_grid(db, cik, period_labels, limit, opts.statements, period_mode, restated, column_order, as_of)
    wb = workbook_from_grid(grid, opts)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), opts.resolved_filename(grid)


__all__ = ["ExportOptions", "export_excel", "export_workbook", "workbook_from_grid"]
