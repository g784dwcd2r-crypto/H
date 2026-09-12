"""Statement grid: periods as columns, as-reported lines as rows, merged across filings.

Shared by the Excel exporter and the API's statements endpoint so both show the same thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from filings_hub.db.database import Database
from filings_hub.ingest.sync_statements import CORE_STATEMENTS, STATEMENT_NAMES


@dataclass
class PeriodColumn:
    period_label: str
    period_end: date
    fiscal_year: int
    fiscal_quarter: int
    accession: str
    form: str | None
    filed_date: date | None
    filing_index_url: str | None
    primary_doc_url: str | None
    earnings_release_accession: str | None
    earnings_release_url: str | None
    statements_source: str | None
    checks_passed: bool | None

    @property
    def is_provisional(self) -> bool:
        return self.statements_source == "facts_fallback"


@dataclass
class GridLine:
    key: str  # concept (+ occurrence suffix when a concept repeats)
    concept: str
    label: str
    is_abstract: bool
    is_subtotal: bool
    parent_concept: str | None
    unit: str | None
    values: dict[str, float | None] = field(default_factory=dict)  # period_label -> value_presented
    labels: dict[str, str] = field(default_factory=dict)  # per period as-reported label (may differ)


@dataclass
class StatementGrid:
    code: str
    name: str
    lines: list[GridLine]


@dataclass
class Grid:
    cik: int
    company_name: str
    ticker: str | None
    periods: list[PeriodColumn]  # oldest -> newest
    statements: list[StatementGrid]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cik": self.cik,
            "company_name": self.company_name,
            "ticker": self.ticker,
            "periods": [
                {
                    "period_label": p.period_label,
                    "period_end": p.period_end.isoformat(),
                    "accession": p.accession,
                    "form": p.form,
                    "filed_date": p.filed_date.isoformat() if p.filed_date else None,
                    "filing_index_url": p.filing_index_url,
                    "primary_doc_url": p.primary_doc_url,
                    "statements_source": p.statements_source,
                    "is_provisional": p.is_provisional,
                    "checks_passed": p.checks_passed,
                }
                for p in self.periods
            ],
            "statements": [
                {
                    "code": s.code,
                    "name": s.name,
                    "lines": [
                        {
                            "key": ln.key,
                            "concept": ln.concept,
                            "label": ln.label,
                            "is_abstract": ln.is_abstract,
                            "is_subtotal": ln.is_subtotal,
                            "parent_concept": ln.parent_concept,
                            "unit": ln.unit,
                            "values": ln.values,
                        }
                        for ln in s.lines
                    ],
                }
                for s in self.statements
            ],
        }


def _period_columns(db: Database, cik: int, period_labels: list[str] | None, limit: int) -> list[PeriodColumn]:
    if period_labels:
        placeholders = ", ".join("?" for _ in period_labels)
        rows = db.query(
            f"SELECT p.*, f.filing_index_url, f.primary_doc_url, e.primary_doc_url AS er_url "
            f"FROM {db.periods_table} p LEFT JOIN filings f ON f.accession = p.results_accession "
            f"LEFT JOIN filings e ON e.accession = p.earnings_release_accession "
            f"WHERE p.cik = ? AND p.period_label IN ({placeholders}) ORDER BY p.period_end",
            [cik, *period_labels],
        )
    else:
        rows = db.query(
            f"SELECT * FROM (SELECT p.*, f.filing_index_url, f.primary_doc_url, e.primary_doc_url AS er_url "
            f"FROM {db.periods_table} p LEFT JOIN filings f ON f.accession = p.results_accession "
            f"LEFT JOIN filings e ON e.accession = p.earnings_release_accession "
            f"WHERE p.cik = ? ORDER BY p.period_end DESC LIMIT ?) t ORDER BY period_end",
            [cik, limit],
        )
    return [
        PeriodColumn(
            period_label=r["period_label"],
            period_end=r["period_end"],
            fiscal_year=r["fiscal_year"],
            fiscal_quarter=r["fiscal_quarter"],
            accession=r["results_accession"],
            form=r.get("results_form"),
            filed_date=r.get("results_filed_date"),
            filing_index_url=r.get("filing_index_url"),
            primary_doc_url=r.get("primary_doc_url") or r.get("results_primary_doc_url"),
            earnings_release_accession=r.get("earnings_release_accession"),
            earnings_release_url=r.get("er_url") or r.get("earnings_release_primary_doc_url"),
            statements_source=r.get("statements_source"),
            checks_passed=r.get("checks_passed"),
        )
        for r in rows
    ]


def _statement_rows(
    db: Database, accessions: list[str], statements: tuple[str, ...]
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """accession -> statement code -> primary-period lines (ordered)."""
    if not accessions:
        return {}
    ph_acc = ", ".join("?" for _ in accessions)
    ph_stmt = ", ".join("?" for _ in statements)
    rows = db.query(
        f"SELECT accession, statement, line_order, concept, label, is_abstract, is_subtotal, parent_concept, unit, "
        f"value_presented, value FROM statements WHERE accession IN ({ph_acc}) AND statement IN ({ph_stmt}) "
        f"AND is_primary_period AND NOT is_parenthetical ORDER BY accession, statement, line_order",
        [*accessions, *statements],
    )
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for r in rows:
        out.setdefault(r["accession"], {}).setdefault(r["statement"], []).append(r)
    return out


def _keyed_lines(rows: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Assign a stable key per line: concept, with #n suffix for repeats within the statement."""
    seen: dict[str, int] = {}
    out = []
    for r in rows:
        n = seen.get(r["concept"], 0)
        seen[r["concept"]] = n + 1
        key = r["concept"] if n == 0 else f"{r['concept']}#{n + 1}"
        out.append((key, r))
    return out


def merge_line_order(per_period: list[list[str]]) -> list[str]:
    """Merge ordered key lists, newest first: unseen keys go right after their predecessor."""
    merged: list[str] = []
    for keys in per_period:
        prev: str | None = None
        for k in keys:
            if k in merged:
                prev = k
                continue
            pos = merged.index(prev) + 1 if prev is not None else 0
            merged.insert(pos, k)
            prev = k
    return merged


def build_grid(
    db: Database,
    cik: int,
    period_labels: list[str] | None = None,
    limit: int = 8,
    statements: tuple[str, ...] = CORE_STATEMENTS,
) -> Grid:
    comp = db.query("SELECT name, ticker FROM companies WHERE cik = ?", [cik])
    if not comp:
        raise KeyError(f"unknown CIK {cik}")
    periods = _period_columns(db, cik, period_labels, limit)
    rows_by_acc = _statement_rows(db, [p.accession for p in periods], statements)
    grids: list[StatementGrid] = []
    for code in statements:
        per_period_keys: list[list[str]] = []
        per_period_lines: list[tuple[str, dict[str, dict[str, Any]]]] = []
        for p in reversed(periods):  # newest first
            keyed = _keyed_lines(rows_by_acc.get(p.accession, {}).get(code, []))
            if not keyed:
                continue
            per_period_keys.append([k for k, _ in keyed])
            per_period_lines.append((p.period_label, {k: r for k, r in keyed}))
        if not per_period_keys:
            continue
        order = merge_line_order(per_period_keys)
        lines: dict[str, GridLine] = {}
        for label, keyed in per_period_lines:  # newest first -> newest label/attributes win
            for key, r in keyed.items():
                ln = lines.get(key)
                if ln is None:
                    ln = GridLine(
                        key=key,
                        concept=r["concept"],
                        label=r["label"] or r["concept"],
                        is_abstract=bool(r["is_abstract"]),
                        is_subtotal=bool(r["is_subtotal"]),
                        parent_concept=r.get("parent_concept"),
                        unit=r.get("unit"),
                    )
                    lines[key] = ln
                ln.values[label] = r.get("value_presented")
                if r.get("label"):
                    ln.labels[label] = r["label"]
                if ln.unit is None and r.get("unit"):
                    ln.unit = r["unit"]
        ordered = [lines[k] for k in order]
        for ln in ordered:
            for p in periods:
                ln.values.setdefault(p.period_label, None)
        grids.append(StatementGrid(code=code, name=STATEMENT_NAMES[code], lines=ordered))
    return Grid(
        cik=cik,
        company_name=comp[0]["name"],
        ticker=comp[0].get("ticker"),
        periods=periods,
        statements=grids,
    )
