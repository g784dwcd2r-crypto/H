"""Statement grid: periods as columns, as-reported lines as rows, merged across filings.

Shared by the Excel exporter and the API's statements endpoint so both show the same thing.

The grid has a *period mode*:

* ``as_filed``  -- each column is the filing's own primary period (the quarter on an income statement,
  the year to date on a 10-Q cash flow statement, the year on a 10-K). Nothing is derived.
* ``annual``    -- fiscal years only.
* ``quarterly`` -- reported discrete quarters first; validated additive flows can be differences of
  compatible year-to-date columns. Q4 can be fiscal year less nine-month YTD. No per-share amounts,
  weighted averages, unknown concepts or mixed reporting bases are approximated.
* ``ltm``       -- trailing four quarters at each quarter end: YTD(n) + FY(prior) - YTD(n, prior year).

``restated`` (as-filed and annual modes) takes each column's numbers from the newest later filing
that presents the same period as a comparative, so a restated or reclassified prior year shows the
company's latest view; the filing the numbers came from is named on the column.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from filings_hub.db.database import Database
from filings_hub.export.methodology import additive_reason
from filings_hub.ingest.sync_statements import CORE_STATEMENTS, STATEMENT_NAMES, month_end_round

PERIOD_MODES = ("as_filed", "quarterly", "annual", "ltm")
COLUMN_ORDERS = ("newest_right", "newest_left")
INSTANT_STATEMENTS = ("BS",)  # points in time: never derived

# Which line rolls into which subtotal (`parent_concept`, and `is_subtotal` itself) is inferred from
# the order the lines are printed in, because the SEC's summary data sets drop the filing's own
# calculation tree. It is a positional guess, not the company's declared arithmetic. This note ships
# in the payload so no consumer mistakes the grouping for fact; it becomes real, and this note goes
# away, once the calculation tree is read from the filing (steps.md step 8).
LINE_GROUPING_BASIS = (
    "which line rolls into which subtotal is inferred from presentation order, not the filing's own "
    "calculation tree (the SEC summary data sets omit it); treat the grouping as provisional"
)


@dataclass
class PeriodColumn:
    period_label: str  # column label; the values dict is keyed by it
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
    filed_label: str = ""  # the lake's period label (FY2025, Q3 2026); equals period_label when as filed
    period_type: str = "quarter"
    basis: str = "as filed"  # as filed | derived | restated
    basis_note: str | None = None  # "FY2025 less nine months to Q3 2025", "from 0000320193-25-000079"
    restated_from: str | None = None

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
    value_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)


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
    periods: list[PeriodColumn]  # oldest -> newest unless column_order is newest_left
    statements: list[StatementGrid]
    period_mode: str = "as_filed"
    restated: bool = False
    column_order: str = "newest_right"
    as_of: date | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cik": self.cik,
            "company_name": self.company_name,
            "ticker": self.ticker,
            "period_mode": self.period_mode,
            "restated": self.restated,
            "column_order": self.column_order,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "availability_basis": "SEC filing date; end of selected day, not intraday availability",
            "line_grouping_basis": LINE_GROUPING_BASIS,
            "periods": [
                {
                    "period_label": p.period_label,
                    "filed_label": p.filed_label,
                    "period_end": p.period_end.isoformat(),
                    "fiscal_year": p.fiscal_year,
                    "fiscal_quarter": p.fiscal_quarter,
                    "period_type": p.period_type,
                    "accession": p.accession,
                    "form": p.form,
                    "filed_date": p.filed_date.isoformat() if p.filed_date else None,
                    "filing_index_url": p.filing_index_url,
                    "primary_doc_url": p.primary_doc_url,
                    "statements_source": p.statements_source,
                    "is_provisional": p.is_provisional,
                    "checks_passed": p.checks_passed,
                    "basis": p.basis,
                    "basis_note": p.basis_note,
                    "restated_from": p.restated_from,
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
                            "labels": ln.labels,
                            "value_metadata": ln.value_metadata,
                        }
                        for ln in s.lines
                    ],
                }
                for s in self.statements
            ],
        }


def _all_periods(db: Database, cik: int) -> list[PeriodColumn]:
    """Every period the lake knows for the company, oldest first."""
    rows = db.query(
        f"SELECT p.*, f.filing_index_url, f.primary_doc_url, e.primary_doc_url AS er_url "
        f"FROM {db.periods_table_for(cik)} p "
        f"LEFT JOIN filings f ON f.accession = p.results_accession AND f.cik = p.cik "
        f"LEFT JOIN filings e ON e.accession = p.earnings_release_accession AND e.cik = p.cik "
        f"WHERE p.cik = ? ORDER BY p.period_end, p.results_filed_date",
        [cik],
    )
    return [
        PeriodColumn(
            period_label=r["period_label"],
            filed_label=r["period_label"],
            period_end=r["period_end"],
            fiscal_year=r["fiscal_year"],
            fiscal_quarter=r["fiscal_quarter"],
            period_type=r.get("period_type") or "quarter",
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
    db: Database, accessions: list[str], statements: tuple[str, ...], primary_only: bool = True, cik: int | None = None
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """accession -> statement code -> lines (ordered). Primary-period lines only unless asked."""
    if not accessions:
        return {}
    ph_acc = ", ".join("?" for _ in accessions)
    ph_stmt = ", ".join("?" for _ in statements)
    rows = db.query(
        f"SELECT accession, statement, line_order, concept, label, is_abstract, is_subtotal, parent_concept, unit, "
        f"value_presented, value, period_start, period_end, period_end_rounded, qtrs, is_primary_period, "
        f"taxonomy, is_custom, datatype, source, filed_date, negating "
        f"FROM {db.table('statements', cik)} WHERE accession IN ({ph_acc}) AND statement IN ({ph_stmt}) "
        f"{'AND cik = ?' if cik is not None else ''} "
        f"AND NOT is_parenthetical {'AND is_primary_period' if primary_only else ''} "
        f"ORDER BY accession, statement, line_order",
        [*accessions, *statements, *([cik] if cik is not None else [])],
    )
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for r in rows:
        datatype = (r.get("datatype") or "").split(":")[-1].lower()
        unit = r.get("unit") or ""
        # The SEC FSDS exports perShare facts with a currency-only UOM. The taxonomy type retains
        # the missing denominator. Normalize the serving unit before any scale/format operation;
        # retain the stored UOM in evidence rather than silently rewriting source data.
        if datatype in {"pershare", "pershareitemtype"} and len(unit) == 3 and unit.isupper():
            r["reported_unit"] = unit
            r["unit"] = f"{unit}/shares"
            r["unit_note"] = "Per-share unit restored from the taxonomy datatype; stored FSDS unit was currency-only."
        out.setdefault(r["accession"], {}).setdefault(r["statement"], []).append(r)
    return out


def _keyed_lines(rows: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """A stable key per line, used to match the same line across filings.

    The concept alone is not enough: a cash flow statement presents one cash concept twice, as opening
    and closing balances, and an equity statement repeats a concept on every movement line. The
    as-reported label is what distinguishes them and the company keeps it stable between filings, so the
    key is (concept, label). A positional suffix is added only when a filing repeats both, which leaves
    it out of the common case -- keying by position alone meant that a filing presenting one occurrence
    fewer shifted every later occurrence onto the wrong row.
    """
    seen: dict[tuple[str, str], int] = {}
    out = []
    for r in rows:
        label = (r.get("label") or "").strip().casefold()
        base = f"{r['concept']}|{label}" if label else r["concept"]
        n = seen.get((r["concept"], label), 0)
        seen[(r["concept"], label)] = n + 1
        out.append((base if n == 0 else f"{base}#{n + 1}", r))
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


PeriodKey = tuple[date | None, int | None]  # (period_end_rounded, qtrs)


@dataclass
class _Cell:
    value: float | None
    status: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None
    formula: str | None = None

    def metadata(self) -> dict[str, Any]:
        return {
            k: v
            for k, v in {
                "status": self.status,
                "sources": self.sources,
                "reason": self.reason,
                "formula": self.formula,
            }.items()
            if v is not None
        }


def _unavailable(reason: str, sources: list[dict[str, Any]] | None = None) -> _Cell:
    return _Cell(None, "unavailable", sources or [], reason)


class _Rows:
    """Statement rows of many filings, indexed by filing, statement and reported period."""

    def __init__(self, rows_by_acc: dict[str, dict[str, list[dict[str, Any]]]], periods: list[PeriodColumn] = ()):
        self._rows = rows_by_acc
        self._filings = {p.accession: p for p in periods}
        self._aliases: dict[tuple[str, str], str] = {}
        candidates: dict[tuple[str, str], list[tuple[str, str, dict[str, Any]]]] = {}
        repeated: set[tuple[str, str]] = set()
        for acc, statements in rows_by_acc.items():
            for stmt, raw in statements.items():
                primary = [r for r in raw if r.get("is_primary_period") and not r.get("is_abstract")]
                repeated.update(
                    (stmt, concept) for concept, count in Counter(r["concept"] for r in primary).items() if count > 1
                )
                # A comparative may repeat a concept even when the primary column does not.
                repeated.update(
                    (stmt, concept)
                    for (concept, _, _), count in Counter(
                        (r["concept"], r.get("period_end_rounded"), r.get("qtrs"))
                        for r in raw
                        if not r.get("is_abstract")
                    ).items()
                    if count > 1
                )
                for key, row in _keyed_lines(primary):
                    candidates.setdefault((stmt, row["concept"]), []).append((acc, key, row))
        for (stmt, concept), occurrences in candidates.items():
            if (stmt, concept) in repeated:
                continue
            signatures = {((r.get("taxonomy") or "").split("/")[0], r.get("unit")) for _, _, r in occurrences}
            if (
                len(signatures) != 1
                or any(not namespace or not unit for namespace, unit in signatures)
                or len({key for _, key, _ in occurrences}) < 2
            ):
                continue
            latest = max(
                occurrences,
                key=lambda item: (
                    item[2].get("filed_date")
                    or (self._filings[item[0]].filed_date if item[0] in self._filings else None)
                    or date.min,
                    item[0],
                ),
            )
            for _, key, _ in occurrences:
                self._aliases[(stmt, key)] = latest[1]
        self._primary: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = {}
        self._groups: dict[tuple[str, str], dict[PeriodKey, dict[str, dict[str, Any]]]] = {}
        self._concepts: dict[tuple[str, str, PeriodKey], dict[str, list[dict[str, Any]]]] = {}

    def primary(self, acc: str, stmt: str) -> list[tuple[str, dict[str, Any]]]:
        """The filing's own primary-period lines, keyed and in line order."""
        k = (acc, stmt)
        if k not in self._primary:
            rows = [r for r in self._rows.get(acc, {}).get(stmt, []) if r.get("is_primary_period")]
            self._primary[k] = [(self._aliases.get((stmt, key), key), row) for key, row in _keyed_lines(rows)]
        return self._primary[k]

    def groups(self, acc: str, stmt: str) -> dict[PeriodKey, dict[str, dict[str, Any]]]:
        """(period_end_rounded, qtrs) -> key -> row, for every period the filing presents."""
        k = (acc, stmt)
        if k not in self._groups:
            by_period: dict[PeriodKey, list[dict[str, Any]]] = {}
            for r in self._rows.get(acc, {}).get(stmt, []):
                by_period.setdefault((r.get("period_end_rounded"), r.get("qtrs")), []).append(r)
            self._groups[k] = {
                pk: {self._aliases.get((stmt, key), key): row for key, row in _keyed_lines(rows)}
                for pk, rows in by_period.items()
            }
        return self._groups[k]

    def has_period(self, acc: str, stmt: str, pk: PeriodKey) -> bool:
        g = self.groups(acc, stmt).get(pk)
        return bool(g) and any(r.get("value_presented") is not None for r in g.values())

    def row(self, acc: str, stmt: str, key: str, pk: PeriodKey, concept: str | None = None) -> dict[str, Any] | None:
        """The presented value of line `key` for the period `pk` in filing `acc`; None when absent.

        Falls back to the concept when the filing's label for the line drifted, provided the concept
        appears once in that period.
        """
        g = self.groups(acc, stmt).get(pk)
        if not g:
            return None
        r = g.get(key)
        if r is None and concept:
            ck = (acc, stmt, pk)
            if ck not in self._concepts:
                by_c: dict[str, list[dict[str, Any]]] = {}
                for row in g.values():
                    by_c.setdefault(row["concept"], []).append(row)
                self._concepts[ck] = by_c
            cands = self._concepts[ck].get(concept, [])
            r = cands[0] if len(cands) == 1 else None
        return r

    def value(self, acc: str, stmt: str, key: str, pk: PeriodKey, concept: str | None = None) -> float | None:
        r = self.row(acc, stmt, key, pk, concept)
        return None if r is None else r.get("value_presented")

    def reported(self, r: dict[str, Any] | None, status: str = "reported") -> _Cell:
        if r is None or r.get("value_presented") is None:
            return _unavailable("The required reported value is not available in this filing.")
        p = self._filings.get(r["accession"])
        source = {
            k: r.get(k) for k in ("accession", "concept", "taxonomy", "unit", "qtrs", "source", "is_custom", "negating")
        }
        source["value"] = r["value_presented"]
        source["label"] = r.get("label")
        for k in ("reported_unit", "unit_note"):
            if r.get(k):
                source[k] = r[k]
        if r.get("source") == "fsds":
            source["date_note"] = (
                "These stored dates may be rounded or inferred. Confirm exact reporting dates in the original filing."
            )
        for k in ("period_start", "period_end", "filed_date"):
            d = r.get(k)
            source[k] = d.isoformat() if d else None
        if p:
            source["document_url"] = p.primary_doc_url or p.filing_index_url
            source["filing_index_url"] = p.filing_index_url
            if not source["filed_date"]:
                source["filed_date"] = p.filed_date.isoformat() if p.filed_date else None
        return _Cell(r["value_presented"], status, [source])

    def cell(self, acc: str, stmt: str, key: str, pk: PeriodKey, concept: str) -> _Cell:
        return self.reported(self.row(acc, stmt, key, pk, concept))

    def primary_qtrs(self, acc: str, stmt: str) -> int:
        """Duration of the filing's own column on this statement (0 when it presents instants only)."""
        qs = [r["qtrs"] for _, r in self.primary(acc, stmt) if r.get("qtrs")]
        return max(qs) if qs else 0


def _pk(p: PeriodColumn, qtrs: int) -> PeriodKey:
    return (month_end_round(p.period_end), qtrs)


class _Derive:
    """Quarter and trailing-four-quarter arithmetic for one statement of one company."""

    def __init__(self, rows: _Rows, stmt: str, periods: list[PeriodColumn]):
        self.rows = rows
        self.stmt = stmt
        self.byq: dict[tuple[int, int], PeriodColumn] = {}
        for p in periods:
            if p.period_type != "transition":
                self.byq.setdefault((p.fiscal_year, p.fiscal_quarter), p)

    def ytd(self, fy: int, n: int, key: str, concept: str) -> _Cell:
        p = self.byq.get((fy, n))
        if p is None:
            return _unavailable("A required fiscal-period filing is missing.")
        return self.rows.cell(p.accession, self.stmt, key, _pk(p, n), concept)

    def _calculate(self, terms: list[tuple[int, _Cell]], formula: str) -> _Cell:
        sources = [s for _, cell in terms for s in cell.sources]
        if any(cell.value is None for _, cell in terms):
            reason = next(cell.reason for _, cell in terms if cell.value is None and cell.reason)
            return _unavailable(reason, sources)
        if len({s.get("unit") for s in sources}) != 1:
            return _unavailable("Reported inputs use different units or currencies.", sources)
        if len({(s.get("taxonomy") or "").split("/")[0] for s in sources}) != 1:
            return _unavailable("Reported inputs use different accounting taxonomies.", sources)
        for source in sources:
            if reason := additive_reason(source, self.stmt):
                return _unavailable(reason, sources)
        if len({bool(s.get("negating")) for s in sources}) != 1:
            return _unavailable("Reported inputs use different presentation sign conventions.", sources)
        # Preserve every original input and its coefficient, including inputs of derived quarters.
        result_sources = [
            {**s, "coefficient": sign * s.get("coefficient", 1)} for sign, cell in terms for s in cell.sources
        ]
        return _Cell(sum(sign * cell.value for sign, cell in terms), "derived", result_sources, formula=formula)

    def _eligibility(self, p: PeriodColumn, key: str, concept: str) -> str | None:
        candidates = [r for k, r in self.rows.primary(p.accession, self.stmt) if k == key]
        return additive_reason(candidates[0], self.stmt) if candidates else "No validated source line is available."

    def _difference(self, whole: _Cell, earlier: _Cell, formula: str) -> _Cell:
        if whole.value is not None and earlier.value is not None:
            a, b = whole.sources[0], earlier.sources[0]
            if not a.get("period_start") or not b.get("period_start"):
                return _unavailable(
                    "The reporting dates needed to validate this difference are missing.",
                    whole.sources + earlier.sources,
                )
            if (
                a["period_start"] != b["period_start"]
                or not a.get("period_end")
                or not b.get("period_end")
                or a["period_end"] <= b["period_end"]
            ):
                return _unavailable(
                    "The reported periods do not share a compatible fiscal-year start.", whole.sources + earlier.sources
                )
        return self._calculate([(1, whole), (-1, earlier)], formula)

    def quarter(self, fy: int, n: int, key: str, concept: str) -> _Cell:
        p = self.byq.get((fy, n))
        if p is None:
            return _unavailable("A required fiscal-period filing is missing.")
        # A 10-K can itself contain a reported Q4: use it even for non-additive concepts.
        direct = self.rows.cell(p.accession, self.stmt, key, _pk(p, 1), concept)
        if direct.value is not None or n == 1:
            return direct
        reason = self._eligibility(p, key, concept)
        if reason:
            return _unavailable(reason)
        if n == 4:
            fy_v = self.ytd(fy, 4, key, concept)
            y3 = self.ytd(fy, 3, key, concept)
            return self._difference(fy_v, y3, "FY − nine months YTD")
        yn, yprev = self.ytd(fy, n, key, concept), self.ytd(fy, n - 1, key, concept)
        return self._difference(yn, yprev, "Current YTD − previous YTD")

    def q4_basis(self, fy: int) -> str | None:
        p3 = self.byq.get((fy, 3))
        if p3 is not None and self.rows.has_period(p3.accession, self.stmt, _pk(p3, 3)):
            return f"FY{fy} less nine months to {p3.period_label}"
        return None

    def ltm(self, fy: int, n: int, key: str, concept: str) -> _Cell:
        p = self.byq.get((fy, n))
        if p is None:
            return _unavailable("A required fiscal-period filing is missing.")
        direct = self.rows.cell(p.accession, self.stmt, key, _pk(p, 4), concept)
        if direct.value is not None or n == 4:
            return direct
        reason = self._eligibility(p, key, concept)
        if reason:
            return _unavailable(reason)
        yn = self.ytd(fy, n, key, concept)
        fy_prev = self.ytd(fy - 1, 4, key, concept)
        y_prior = _unavailable("A required prior-year YTD value is missing.")
        prior = self.byq.get((fy - 1, n))
        if prior is not None:  # the comparative column in this year's filing first
            y_prior = self.rows.cell(p.accession, self.stmt, key, _pk(prior, n), concept)
        original_prior = self.ytd(fy - 1, n, key, concept)
        if y_prior.value is not None and original_prior.value is not None and y_prior.value != original_prior.value:
            return _unavailable(
                "The later comparative changed; a consistent annual/YTD reporting basis has not been verified.",
                yn.sources + fy_prev.sources + y_prior.sources + original_prior.sources,
            )
        if y_prior.value is None:
            y_prior = self.ytd(fy - 1, n, key, concept)
        tail = self._difference(fy_prev, y_prior, "Prior FY − prior YTD")
        if yn.value is not None and tail.value is not None:
            start = yn.sources[0].get("period_start")
            end = fy_prev.sources[0].get("period_end")
            if not start or not end or (date.fromisoformat(start) - date.fromisoformat(end)).days != 1:
                return _unavailable("The annual and current YTD periods are not contiguous.", yn.sources + tail.sources)
        return self._calculate([(1, yn), (1, tail)], "Current YTD + prior FY − prior YTD")


def _select(
    all_periods: list[PeriodColumn], period_labels: list[str] | None, limit: int, mode: str
) -> list[PeriodColumn]:
    eligible = [p for p in all_periods if p.period_type == "annual"] if mode == "annual" else all_periods
    if period_labels:
        wanted = set(period_labels)
        return [p for p in eligible if p.period_label in wanted]
    return eligible[-limit:]


def _restating_filing(
    rows: _Rows, col: PeriodColumn, stmt: str, all_periods: list[PeriodColumn]
) -> PeriodColumn | None:
    """The newest later filing that presents this column's own period on this statement."""
    q = rows.primary_qtrs(col.accession, stmt)
    pk = _pk(col, q)
    later = [
        p
        for p in all_periods
        if p.accession != col.accession
        and p.filed_date
        and col.filed_date
        and p.filed_date > col.filed_date
        and rows.has_period(p.accession, stmt, pk)
    ]
    return max(later, key=lambda p: (p.filed_date, p.period_end)) if later else None


def build_grid(
    db: Database,
    cik: int,
    period_labels: list[str] | None = None,
    limit: int = 8,
    statements: tuple[str, ...] = CORE_STATEMENTS,
    period_mode: str = "as_filed",
    restated: bool = False,
    column_order: str = "newest_right",
    as_of: date | None = None,
) -> Grid:
    with db.read_snapshot() as reader:
        return _build_grid(reader, cik, period_labels, limit, statements, period_mode, restated, column_order, as_of)


def _build_grid(
    db: Database,
    cik: int,
    period_labels: list[str] | None,
    limit: int,
    statements: tuple[str, ...],
    period_mode: str,
    restated: bool,
    column_order: str,
    as_of: date | None,
) -> Grid:
    if period_mode not in PERIOD_MODES:
        raise ValueError(f"period_mode must be one of {', '.join(PERIOD_MODES)}")
    if column_order not in COLUMN_ORDERS:
        raise ValueError(f"column_order must be one of {', '.join(COLUMN_ORDERS)}")
    comp = db.query("SELECT name, ticker FROM companies WHERE cik = ?", [cik])
    if not comp:
        raise KeyError(f"unknown CIK {cik}")
    derived_mode = period_mode in ("quarterly", "ltm")
    restated = bool(restated) and not derived_mode
    all_periods = _all_periods(db, cik)
    if as_of is not None:
        # Apply before choosing columns, comparatives or any derivation operands.
        # Unknown dates fail closed. This is date-resolution availability, not transaction-time replay.
        all_periods = [p for p in all_periods if p.filed_date is not None and p.filed_date <= as_of]
    shown = _select(all_periods, period_labels, limit, period_mode)

    need = {p.accession for p in shown}
    if derived_mode:
        years = {p.fiscal_year for p in shown}
        years |= {y - 1 for y in years}
        need |= {p.accession for p in all_periods if p.fiscal_year in years}
    if restated and shown:
        oldest = min(p.filed_date for p in shown if p.filed_date) if any(p.filed_date for p in shown) else None
        if oldest:
            need |= {p.accession for p in all_periods if p.filed_date and p.filed_date >= oldest}
    rows = _Rows(
        _statement_rows(db, sorted(need), statements, primary_only=not (derived_mode or restated), cik=cik), all_periods
    )

    # column labels and basis
    for p in shown:
        p.period_label, p.basis, p.basis_note = p.filed_label, "as filed", None
        if p.period_type == "transition":
            continue
        if period_mode == "quarterly" and p.fiscal_quarter == 4:
            p.period_label, p.basis = f"Q4 {p.fiscal_year}", "derived"
        elif period_mode == "ltm" and p.fiscal_quarter != 4:
            p.period_label, p.basis = f"LTM {p.filed_label}", "derived"
            p.basis_note = f"twelve months to {p.filed_label}"

    grids: list[StatementGrid] = []
    for code in statements:
        per_period_keys: list[list[str]] = []
        per_period_lines: list[tuple[PeriodColumn, dict[str, dict[str, Any]]]] = []
        for p in reversed(shown):  # newest first
            keyed = rows.primary(p.accession, code)
            if not keyed:
                continue
            per_period_keys.append([k for k, _ in keyed])
            per_period_lines.append((p, dict(keyed)))
        if not per_period_keys:
            continue
        order = merge_line_order(per_period_keys)
        lines: dict[str, GridLine] = {}
        derive = _Derive(rows, code, all_periods) if derived_mode and code not in INSTANT_STATEMENTS else None
        for p, keyed in per_period_lines:  # newest first -> newest label/attributes win
            source: PeriodColumn | None = None
            if restated:
                source = _restating_filing(rows, p, code, all_periods)
                if source is not None and p.basis == "as filed":
                    p.basis, p.restated_from = "restated", source.accession
                    p.basis_note = f"as presented in {source.form or 'the filing'} {source.accession}"
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
                cell = rows.reported(r)
                if ln.is_abstract:
                    cell = _unavailable("This is a statement heading, not a reported value.")
                elif derive is not None and p.period_type != "transition":
                    if r.get("qtrs"):  # a duration: derive it
                        fn = derive.quarter if period_mode == "quarterly" else derive.ltm
                        cell = fn(p.fiscal_year, p.fiscal_quarter, key, r["concept"])
                    elif r.get("period_end_rounded") and r["period_end_rounded"] != month_end_round(p.period_end):
                        # an opening balance: the closing balance of the period the derived flows start after
                        fy, n = p.fiscal_year, p.fiscal_quarter
                        prev = (fy, n - 1) if n > 1 else (fy - 1, 4)
                        if period_mode == "ltm":
                            prev = (fy - 1, n)
                        pp = derive.byq.get(prev) if n < 4 or period_mode == "quarterly" else None
                        if pp is not None:
                            cell = rows.cell(pp.accession, code, key, _pk(pp, 0), r["concept"])
                        elif (period_mode == "quarterly" and n > 1) or (period_mode == "ltm" and n < 4):
                            cell = _unavailable("The opening balance for this derived period is unavailable.")
                elif source is not None:
                    # A newer filing can omit a line that an earlier later filing still presents.
                    # Resolve provenance per cell, not from the column's first statement.
                    latest_row = None
                    for later in sorted(all_periods, key=lambda col: col.filed_date or date.min, reverse=True):
                        if not later.filed_date or not p.filed_date or later.filed_date <= p.filed_date:
                            continue
                        candidate = rows.row(
                            later.accession, code, key, (r.get("period_end_rounded"), r.get("qtrs")), r["concept"]
                        )
                        if candidate is not None and candidate.get("value_presented") is not None:
                            latest_row = candidate
                            break
                    if latest_row is not None and latest_row.get("value_presented") is not None:
                        if latest_row.get("unit") != r.get("unit"):
                            cell = _unavailable("The later presentation uses different units or currency.")
                        else:
                            cell = rows.reported(latest_row, "latest_presentation")
                    else:
                        cell.reason = (
                            "No value for this line was found in the later comparative; "
                            "the original reported value is retained."
                        )
                ln.values[p.period_label] = cell.value
                ln.value_metadata[p.period_label] = cell.metadata()
                if r.get("label"):
                    ln.labels[p.period_label] = (
                        cell.sources[0].get("label") or r["label"]
                        if cell.status == "latest_presentation" and cell.sources
                        else r["label"]
                    )
                if ln.unit is None and r.get("unit"):
                    ln.unit = r["unit"]
            if derive is not None and p.basis == "derived" and period_mode == "quarterly" and not p.basis_note:
                p.basis_note = derive.q4_basis(p.fiscal_year) or "Q1-Q3 filings missing; nothing to derive from"
        ordered = [lines[k] for k in order]
        for ln in ordered:
            for p in shown:
                ln.values.setdefault(p.period_label, None)
                ln.value_metadata.setdefault(
                    p.period_label, _unavailable("This line is not available for the selected period.").metadata()
                )
        grids.append(StatementGrid(code=code, name=STATEMENT_NAMES[code], lines=ordered))
    periods = list(shown) if column_order == "newest_right" else list(reversed(shown))
    return Grid(
        cik=cik,
        company_name=comp[0]["name"],
        ticker=comp[0].get("ticker"),
        periods=periods,
        statements=grids,
        period_mode=period_mode,
        restated=restated,
        column_order=column_order,
        as_of=as_of,
    )
