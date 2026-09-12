"""Period spine: turn a company's filings into labelled fiscal periods.

Rules
-----
* Results filings: annual (10-K, 10-KT, 10-K405, 10-KSB, 20-F, 40-F) and quarterly (10-Q, 10-QT, 10-QSB).
* Labels: ``FY2025`` for annual, ``Q1 2026`` for quarters. Fiscal year = calendar year in which the fiscal
  year *ends* (Apple's quarter ending December 2025 is Q1 FY2026). Transition periods get a ``T`` suffix.
* Fiscal quarter is derived from the distance between the report date and the fiscal year end. The FYE
  anchor is the company's *actual* next annual report date when we have one (robust to 52/53-week years
  and fiscal year-end changes), otherwise the nominal ``fiscalYearEnd`` (MMDD) from EDGAR.
* Earnings release: earliest 8-K with item 2.02 filed within 60 days (quarters) / 90 days (annual) after
  the period end.
* Amendments (10-K/A, 10-Q/A ...) hang off the original period; they never create periods of their own
  unless no original exists in the data.
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pyarrow as pa

log = logging.getLogger(__name__)

ANNUAL_FORMS = {"10-K", "10-KT", "10-K405", "10-KSB", "20-F", "40-F", "10-KT405", "10-KSB40"}
QUARTERLY_FORMS = {"10-Q", "10-QT", "10-QSB"}
TRANSITION_FORMS = {"10-KT", "10-QT", "10-KT405"}
RESULTS_FORMS = ANNUAL_FORMS | QUARTERLY_FORMS
EARNINGS_ITEM = "2.02"
EARNINGS_WINDOW_QUARTER_DAYS = 60
EARNINGS_WINDOW_ANNUAL_DAYS = 90
FYE_DRIFT_DAYS = 14  # 52/53-week years end up to ~a week either side of the nominal FYE

PERIODS_SCHEMA = pa.schema(
    [
        ("cik", pa.int64()),
        ("period_label", pa.string()),
        ("fiscal_year", pa.int32()),
        ("fiscal_quarter", pa.int8()),  # 1..3 quarters, 4 = annual
        ("period_type", pa.string()),  # annual | quarter | transition
        ("period_end", pa.date32()),
        ("results_accession", pa.string()),
        ("results_form", pa.string()),
        ("results_filed_date", pa.date32()),
        ("results_primary_doc_url", pa.string()),
        ("earnings_release_accession", pa.string()),
        ("earnings_release_filed_date", pa.date32()),
        ("earnings_release_primary_doc_url", pa.string()),
        ("amendment_accessions", pa.list_(pa.string())),
        ("label_method", pa.string()),  # anchor | nominal_fye | fallback
    ]
)


def base_form(form: str) -> str:
    return form.split("/")[0].strip().upper()


def is_amendment(form: str) -> bool:
    return form.strip().upper().endswith("/A")


def form_family(form: str) -> str | None:
    b = base_form(form)
    if b in ANNUAL_FORMS:
        return "annual"
    if b in QUARTERLY_FORMS:
        return "quarter"
    return None


def safe_date(year: int, month: int, day: int) -> date:
    """Date with day clamped to the month's length (handles 0229 fiscal year ends)."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def parse_fye(fye: str | None) -> tuple[int, int] | None:
    """EDGAR fiscalYearEnd 'MMDD' -> (month, day) or None."""
    if not fye or len(fye) != 4 or not fye.isdigit():
        return None
    m, d = int(fye[:2]), int(fye[2:])
    if not (1 <= m <= 12 and 1 <= d <= 31):
        return None
    return m, d


def nominal_fye_after(report_date: date, fye: tuple[int, int]) -> date:
    """The nominal fiscal year end on/after `report_date` (allowing 52/53-week drift before it)."""
    m, d = fye
    end = safe_date(report_date.year, m, d)
    if end < report_date - timedelta(days=FYE_DRIFT_DAYS):
        end = safe_date(report_date.year + 1, m, d)
    return end


def fiscal_year_of(end: date, fye: tuple[int, int] | None) -> int:
    """The fiscal year a period ending on `end` belongs to.

    Normally that is the calendar year the period ends in, but a 52/53-week year pinned to a weekday can
    end a few days either side of its nominal date and so cross New Year: Snap-on's fiscal 2021 ended
    2022-01-01 and its fiscal 2022 ended 2022-12-31. Naming both FY2022 collapses two years into one.
    So when `end` sits within the 52/53-week drift of a nominal year end, that nominal year names it.

    The drift window also keeps a company that *changed* its year end honest: an annual report ending
    2019-06-30 for a filer whose year end is now December is nowhere near a nominal date, so it keeps
    the calendar year it ended in.
    """
    if fye is None:
        return end.year
    for year in (end.year - 1, end.year, end.year + 1):
        if abs((safe_date(year, *fye) - end).days) <= FYE_DRIFT_DAYS:
            return year
    return end.year


def months_between(start: date, end: date) -> int:
    return round((end - start).days / 30.4375)


def quarter_from_months_to_fye(months: int) -> int | None:
    """Months from period end to fiscal year end -> fiscal quarter, or None if irregular."""
    return {0: 4, 3: 3, 6: 2, 9: 1}.get(months)


@dataclass
class FiscalPeriod:
    fiscal_year: int
    fiscal_quarter: int  # 4 = annual
    method: str

    @property
    def key(self) -> tuple[int, int]:
        return (self.fiscal_year, self.fiscal_quarter)


def fiscal_period_for(
    report_date: date,
    family: str,
    fye: tuple[int, int] | None,
    annual_anchors: list[date] | None = None,
) -> FiscalPeriod:
    """Fiscal (year, quarter) for a results filing.

    annual_anchors: sorted report dates of the company's actual annual reports. When one exists within a
    year after this report date, the quarter is measured against it (52/53-week and FYE-change proof).
    """
    if family == "annual":
        return FiscalPeriod(fiscal_year_of(report_date, fye), 4, "period_end")

    # 1. real anchor: the next annual report date
    for anchor in annual_anchors or []:
        if anchor >= report_date - timedelta(days=FYE_DRIFT_DAYS):
            gap = (anchor - report_date).days
            if gap <= 330:
                q = quarter_from_months_to_fye(months_between(report_date, anchor))
                if q is not None and q != 4:
                    return FiscalPeriod(fiscal_year_of(anchor, fye), q, "anchor")
            break

    # 2. nominal FYE
    if fye is not None:
        end = nominal_fye_after(report_date, fye)
        q = quarter_from_months_to_fye(months_between(report_date, end))
        if q is not None and q != 4:
            return FiscalPeriod(fiscal_year_of(end, fye), q, "nominal_fye")

    # 3. fallback: calendar quarters
    cal_q = (report_date.month - 1) // 3 + 1
    return FiscalPeriod(report_date.year, cal_q if cal_q < 4 else 3, "fallback")


def period_label(fp: FiscalPeriod, transition: bool = False) -> str:
    label = f"FY{fp.fiscal_year}" if fp.fiscal_quarter == 4 else f"Q{fp.fiscal_quarter} {fp.fiscal_year}"
    return label + ("T" if transition else "")


@dataclass
class _PeriodBuild:
    fiscal_year: int
    fiscal_quarter: int
    transition: bool
    originals: list[dict[str, Any]] = field(default_factory=list)
    amendments: list[dict[str, Any]] = field(default_factory=list)
    method: str = ""


def build_periods_for_company(
    cik: int, filings: list[dict[str, Any]], fiscal_year_end: str | None
) -> list[dict[str, Any]]:
    """`filings`: rows with accession, form, filed_date, report_date, items, primary_doc_url (any order)."""
    fye = parse_fye(fiscal_year_end)
    results = [
        f for f in filings if form_family(f["form"]) and f.get("report_date") is not None and f.get("filed_date")
    ]
    annual_anchors = sorted(
        {
            f["report_date"]
            for f in results
            if form_family(f["form"]) == "annual"
            and not is_amendment(f["form"])
            and base_form(f["form"]) not in TRANSITION_FORMS  # a transition year end is not a fiscal year end
        }
    )

    builds: dict[tuple[int, int, bool], _PeriodBuild] = {}
    for f in results:
        family = form_family(f["form"])
        assert family is not None
        fp = fiscal_period_for(f["report_date"], family, fye, annual_anchors)
        transition = base_form(f["form"]) in TRANSITION_FORMS
        key = (fp.fiscal_year, fp.fiscal_quarter, transition)
        b = builds.setdefault(key, _PeriodBuild(fp.fiscal_year, fp.fiscal_quarter, transition))
        if is_amendment(f["form"]):
            b.amendments.append(f)
        else:
            b.originals.append(f)
            b.method = fp.method

    eightks = sorted(
        (
            f
            for f in filings
            if base_form(f["form"]) == "8-K" and EARNINGS_ITEM in (f.get("items") or []) and f.get("filed_date")
        ),
        key=lambda f: (f["filed_date"], f["accession"]),
    )

    rows: list[dict[str, Any]] = []
    for (fy, fq, transition), b in builds.items():
        candidates = b.originals or b.amendments
        # latest-filed original is the authoritative results filing; earlier same-period originals are rare re-files
        results_filing = sorted(candidates, key=lambda f: (f["filed_date"], f["accession"]))[-1]
        period_end = results_filing["report_date"]
        window = EARNINGS_WINDOW_ANNUAL_DAYS if fq == 4 else EARNINGS_WINDOW_QUARTER_DAYS
        er = next(
            (e for e in eightks if period_end < e["filed_date"] <= period_end + timedelta(days=window)),
            None,
        )
        amendments = sorted(
            {f["accession"] for f in b.amendments}
            | {f["accession"] for f in b.originals if f["accession"] != results_filing["accession"]}
        )
        fp = FiscalPeriod(fy, fq, b.method or "amendment_only")
        rows.append(
            {
                "cik": cik,
                "period_label": period_label(fp, transition),
                "fiscal_year": fy,
                "fiscal_quarter": fq,
                "period_type": "transition" if transition else ("annual" if fq == 4 else "quarter"),
                "period_end": period_end,
                "results_accession": results_filing["accession"],
                "results_form": results_filing["form"],
                "results_filed_date": results_filing["filed_date"],
                "results_primary_doc_url": results_filing.get("primary_doc_url"),
                "earnings_release_accession": er["accession"] if er else None,
                "earnings_release_filed_date": er["filed_date"] if er else None,
                "earnings_release_primary_doc_url": er.get("primary_doc_url") if er else None,
                "amendment_accessions": amendments,
                "label_method": fp.method,
            }
        )
    rows.sort(key=lambda r: (r["period_end"], r["fiscal_quarter"]), reverse=True)
    return rows


def periods_table(rows: list[dict[str, Any]]) -> pa.Table:
    return pa.Table.from_pylist(rows, schema=PERIODS_SCHEMA)


def next_expected_results(periods: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Best-effort 'next expected results' for the company page: the period after the latest one, with the
    filing date estimated from the same period a year earlier (else period end + statutory-ish lag)."""
    if not periods:
        return None
    latest = max(periods, key=lambda p: p["period_end"])
    fq = latest["fiscal_quarter"]
    if fq == 4:
        nfy, nfq = latest["fiscal_year"] + 1, 1
    else:
        nfy, nfq = latest["fiscal_year"], fq + 1
    next_end = latest["period_end"] + timedelta(days=91)
    prior = next(
        (
            p
            for p in periods
            if p["fiscal_year"] == nfy - 1 and p["fiscal_quarter"] == nfq and p.get("results_filed_date")
        ),
        None,
    )
    if prior:
        expected_filed = prior["results_filed_date"] + timedelta(days=364)
        if prior.get("earnings_release_filed_date"):
            expected_er = prior["earnings_release_filed_date"] + timedelta(days=364)
        else:
            expected_er = None
    else:
        expected_filed = next_end + timedelta(days=60 if nfq == 4 else 40)
        expected_er = None
    return {
        "period_label": period_label(FiscalPeriod(nfy, nfq, "projected")),
        "period_end": next_end,
        "expected_results_filed_date": expected_filed,
        "expected_earnings_release_date": expected_er,
    }
