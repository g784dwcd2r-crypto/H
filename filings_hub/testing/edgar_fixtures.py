"""Synthetic but format-faithful EDGAR data for offline tests and demos.

Companies
---------
320193   Apple-like        FYE 0927 (52/53-week, Saturday closest to Sep 30), AAPL / Nasdaq
1000001  Retailer 53       FYE 0131, 53-week year ended 2024-02-03
1000275  RBC-like          40-F filer, FYE 1031, RY / NYSE
1652044  Two-ticker Co     GOOGL + GOOG
1000002  Old Co            delisted, last 10-K in 2019
19617    JPM-like bank     no gross profit line
1000003  Broken Co         balance sheet does not balance (checks_passed = False)
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, timedelta
from typing import Any

import orjson

APPLE = 320193
RETAILER = 1000001
RBC = 1000275
TWO_TICKER = 1652044
OLD = 1000002
JPM = 19617
BROKEN = 1000003

BILLION = 1_000_000_000
M = 1_000_000


# ----------------------------------------------------------------------------------------------
# Filings (submissions API shape)
# ----------------------------------------------------------------------------------------------
def _acc(cik: int, year: int, seq: int) -> str:
    return f"{cik:010d}-{year % 100:02d}-{seq:06d}"


APPLE_FILINGS: list[dict[str, Any]] = [
    # accession, form, filed, report, items, primary doc
    {
        "acc": _acc(APPLE, 2024, 81),
        "form": "10-K",
        "filed": "2024-11-01",
        "report": "2024-09-28",
        "items": "",
        "doc": "aapl-20240928.htm",
    },
    {
        "acc": _acc(APPLE, 2024, 70),
        "form": "8-K",
        "filed": "2024-10-31",
        "report": "2024-10-31",
        "items": "2.02,9.01",
        "doc": "aapl-20241031.htm",
    },
    {
        "acc": _acc(APPLE, 2024, 75),
        "form": "8-K",
        "filed": "2024-11-15",
        "report": "2024-11-15",
        "items": "2.02,9.01",
        "doc": "aapl-20241115.htm",
    },
    {
        "acc": _acc(APPLE, 2025, 3),
        "form": "10-K/A",
        "filed": "2025-01-15",
        "report": "2024-09-28",
        "items": "",
        "doc": "aapl-20240928a.htm",
    },
    {
        "acc": _acc(APPLE, 2025, 8),
        "form": "8-K",
        "filed": "2025-01-30",
        "report": "2025-01-30",
        "items": "2.02,9.01",
        "doc": "aapl-20250130.htm",
    },
    {
        "acc": _acc(APPLE, 2025, 10),
        "form": "10-Q",
        "filed": "2025-01-31",
        "report": "2024-12-28",
        "items": "",
        "doc": "aapl-20241228.htm",
    },
    {
        "acc": _acc(APPLE, 2025, 40),
        "form": "8-K",
        "filed": "2025-05-01",
        "report": "2025-05-01",
        "items": "2.02,9.01",
        "doc": "aapl-20250501.htm",
    },
    {
        "acc": _acc(APPLE, 2025, 42),
        "form": "10-Q",
        "filed": "2025-05-02",
        "report": "2025-03-29",
        "items": "",
        "doc": "aapl-20250329.htm",
    },
    {
        "acc": _acc(APPLE, 2025, 60),
        "form": "8-K",
        "filed": "2025-07-31",
        "report": "2025-07-31",
        "items": "2.02,9.01",
        "doc": "aapl-20250731.htm",
    },
    {
        "acc": _acc(APPLE, 2025, 62),
        "form": "10-Q",
        "filed": "2025-08-01",
        "report": "2025-06-28",
        "items": "",
        "doc": "aapl-20250628.htm",
    },
    {
        "acc": _acc(APPLE, 2025, 77),
        "form": "8-K",
        "filed": "2025-10-30",
        "report": "2025-10-30",
        "items": "2.02,9.01",
        "doc": "aapl-20251030.htm",
    },
    {
        "acc": _acc(APPLE, 2025, 79),
        "form": "10-K",
        "filed": "2025-10-31",
        "report": "2025-09-27",
        "items": "",
        "doc": "aapl-20250927.htm",
    },
    {
        "acc": _acc(APPLE, 2025, 80),
        "form": "4",
        "filed": "2025-11-03",
        "report": "2025-10-31",
        "items": "",
        "doc": "xslF345X05/wk-form4.xml",
    },
    {
        "acc": _acc(APPLE, 2025, 85),
        "form": "DEF 14A",
        "filed": "2026-01-10",
        "report": "",
        "items": "",
        "doc": "aapl-def14a.htm",
    },
    {
        "acc": _acc(APPLE, 2026, 5),
        "form": "8-K",
        "filed": "2026-01-29",
        "report": "2026-01-29",
        "items": "2.02,9.01",
        "doc": "aapl-20260129.htm",
    },
    {
        "acc": _acc(APPLE, 2026, 7),
        "form": "10-Q",
        "filed": "2026-01-30",
        "report": "2025-12-27",
        "items": "",
        "doc": "aapl-20251227.htm",
    },
    {
        "acc": _acc(APPLE, 2026, 30),
        "form": "8-K",
        "filed": "2026-04-30",
        "report": "2026-04-30",
        "items": "2.02,9.01",
        "doc": "aapl-20260430.htm",
    },
    {
        "acc": _acc(APPLE, 2026, 32),
        "form": "10-Q",
        "filed": "2026-05-01",
        "report": "2026-03-28",
        "items": "",
        "doc": "aapl-20260328.htm",
    },
    {
        "acc": _acc(APPLE, 2026, 50),
        "form": "8-K",
        "filed": "2026-07-30",
        "report": "2026-07-30",
        "items": "2.02,9.01",
        "doc": "aapl-20260730.htm",
    },
    {
        "acc": _acc(APPLE, 2026, 52),
        "form": "10-Q",
        "filed": "2026-07-31",
        "report": "2026-06-27",
        "items": "",
        "doc": "aapl-20260627.htm",
    },
    {
        "acc": _acc(APPLE, 2026, 60),
        "form": "8-K",
        "filed": "2026-09-01",
        "report": "2026-09-01",
        "items": "5.02",
        "doc": "aapl-20260901.htm",
    },
]
APPLE_10K_FY2025 = _acc(APPLE, 2025, 79)
APPLE_10K_FY2024 = _acc(APPLE, 2024, 81)
APPLE_10Q_Q1_2026 = _acc(APPLE, 2026, 7)
APPLE_10Q_Q2_2026 = _acc(APPLE, 2026, 32)
APPLE_10Q_Q3_2026 = _acc(APPLE, 2026, 52)

RETAILER_FILINGS = [
    {
        "acc": _acc(RETAILER, 2024, 1),
        "form": "10-K",
        "filed": "2024-03-20",
        "report": "2024-02-03",
        "items": "",
        "doc": "r-20240203.htm",
    },
    {
        "acc": _acc(RETAILER, 2024, 2),
        "form": "8-K",
        "filed": "2024-02-27",
        "report": "2024-02-27",
        "items": "2.02",
        "doc": "r-8k1.htm",
    },
    {
        "acc": _acc(RETAILER, 2024, 3),
        "form": "10-Q",
        "filed": "2024-06-05",
        "report": "2024-05-04",
        "items": "",
        "doc": "r-20240504.htm",
    },
    {
        "acc": _acc(RETAILER, 2024, 4),
        "form": "10-Q",
        "filed": "2024-09-04",
        "report": "2024-08-03",
        "items": "",
        "doc": "r-20240803.htm",
    },
    {
        "acc": _acc(RETAILER, 2024, 5),
        "form": "10-Q",
        "filed": "2024-12-04",
        "report": "2024-11-02",
        "items": "",
        "doc": "r-20241102.htm",
    },
    {
        "acc": _acc(RETAILER, 2025, 1),
        "form": "10-K",
        "filed": "2025-03-19",
        "report": "2025-02-01",
        "items": "",
        "doc": "r-20250201.htm",
    },
    {
        "acc": _acc(RETAILER, 2025, 2),
        "form": "10-Q",
        "filed": "2025-06-04",
        "report": "2025-05-03",
        "items": "",
        "doc": "r-20250503.htm",
    },
]
RBC_FILINGS = [
    {
        "acc": _acc(RBC, 2024, 1),
        "form": "40-F",
        "filed": "2024-12-04",
        "report": "2024-10-31",
        "items": "",
        "doc": "ry-40f-2024.htm",
    },
    {
        "acc": _acc(RBC, 2025, 1),
        "form": "6-K",
        "filed": "2025-02-27",
        "report": "2025-01-31",
        "items": "",
        "doc": "ry-6k.htm",
    },
    {
        "acc": _acc(RBC, 2025, 2),
        "form": "40-F",
        "filed": "2025-12-03",
        "report": "2025-10-31",
        "items": "",
        "doc": "ry-40f-2025.htm",
    },
]
RBC_40F_FY2025 = _acc(RBC, 2025, 2)
TWO_TICKER_FILINGS = [
    {
        "acc": _acc(TWO_TICKER, 2026, 1),
        "form": "10-K",
        "filed": "2026-02-05",
        "report": "2025-12-31",
        "items": "",
        "doc": "goog-20251231.htm",
    },
]
OLD_FILINGS = [
    {
        "acc": _acc(OLD, 2019, 1),
        "form": "10-K",
        "filed": "2019-03-15",
        "report": "2018-12-31",
        "items": "",
        "doc": "old-10k.htm",
    },
    {
        "acc": _acc(OLD, 2019, 2),
        "form": "15-12G",
        "filed": "2019-06-01",
        "report": "",
        "items": "",
        "doc": "old-15.htm",
    },
]
JPM_FILINGS = [
    {
        "acc": _acc(JPM, 2026, 1),
        "form": "10-K",
        "filed": "2026-02-20",
        "report": "2025-12-31",
        "items": "",
        "doc": "jpm-20251231.htm",
    },
    {
        "acc": _acc(JPM, 2026, 2),
        "form": "8-K",
        "filed": "2026-01-14",
        "report": "2026-01-14",
        "items": "2.02,9.01",
        "doc": "jpm-8k.htm",
    },
]
JPM_10K_FY2025 = _acc(JPM, 2026, 1)
BROKEN_FILINGS = [
    {
        "acc": _acc(BROKEN, 2026, 1),
        "form": "10-K",
        "filed": "2026-03-30",
        "report": "2025-12-31",
        "items": "",
        "doc": "broken-10k.htm",
    },
]
BROKEN_10K = _acc(BROKEN, 2026, 1)

COMPANIES: dict[int, dict[str, Any]] = {
    APPLE: {
        "name": "Apple Inc.",
        "tickers": ["AAPL"],
        "exchanges": ["Nasdaq"],
        "fye": "0927",
        "sic": "3571",
        "sicd": "Electronic Computers",
        "state": "CA",
        "filings": APPLE_FILINGS,
        "category": "Large accelerated filer",
    },
    RETAILER: {
        "name": "Retailer 53 Corp",
        "tickers": ["RTL"],
        "exchanges": ["NYSE"],
        "fye": "0131",
        "sic": "5331",
        "sicd": "Retail-Variety Stores",
        "state": "DE",
        "filings": RETAILER_FILINGS,
        "category": "Large accelerated filer",
    },
    RBC: {
        "name": "Royal Bank of Canada",
        "tickers": ["RY"],
        "exchanges": ["NYSE"],
        "fye": "1031",
        "sic": "6029",
        "sicd": "Commercial Banks, NEC",
        "state": "A6",
        "filings": RBC_FILINGS,
        "category": "Large accelerated filer",
    },
    TWO_TICKER: {
        "name": "Two Ticker Holdings",
        "tickers": ["GOOGL", "GOOG"],
        "exchanges": ["Nasdaq", "Nasdaq"],
        "fye": "1231",
        "sic": "7370",
        "sicd": "Services-Computer Programming",
        "state": "DE",
        "filings": TWO_TICKER_FILINGS,
        "category": "Large accelerated filer",
    },
    OLD: {
        "name": "Old Co Inc",
        "tickers": [],
        "exchanges": [],
        "fye": "1231",
        "sic": "3990",
        "sicd": "Misc Manufacturing",
        "state": "NV",
        "filings": OLD_FILINGS,
        "category": "Non-accelerated filer",
    },
    JPM: {
        "name": "JPMorgan Chase & Co",
        "tickers": ["JPM"],
        "exchanges": ["NYSE"],
        "fye": "1231",
        "sic": "6021",
        "sicd": "National Commercial Banks",
        "state": "DE",
        "filings": JPM_FILINGS,
        "category": "Large accelerated filer",
    },
    BROKEN: {
        "name": "Broken Books Ltd",
        "tickers": ["BRKN"],
        "exchanges": ["OTC"],
        "fye": "1231",
        "sic": "1000",
        "sicd": "Metal Mining",
        "state": "NV",
        "filings": BROKEN_FILINGS,
        "category": "Smaller reporting company",
    },
}


def submissions_doc(cik: int, filings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    c = COMPANIES[cik]
    fl = filings if filings is not None else c["filings"]
    fl = sorted(fl, key=lambda f: f["filed"], reverse=True)  # EDGAR lists newest first
    recent = {
        "accessionNumber": [f["acc"] for f in fl],
        "filingDate": [f["filed"] for f in fl],
        "reportDate": [f["report"] for f in fl],
        "acceptanceDateTime": [f"{f['filed']}T16:30:00.000Z" for f in fl],
        "act": ["34" for _ in fl],
        "form": [f["form"] for f in fl],
        "fileNumber": ["001-36743" for _ in fl],
        "filmNumber": ["251234567" for _ in fl],
        "items": [f["items"] for f in fl],
        "size": [1234567 for _ in fl],
        "isXBRL": [1 if f["form"].split("/")[0] in ("10-K", "10-Q", "40-F", "20-F") else 0 for f in fl],
        "isInlineXBRL": [1 if f["form"].split("/")[0] in ("10-K", "10-Q", "40-F", "20-F") else 0 for f in fl],
        "primaryDocument": [f["doc"] for f in fl],
        "primaryDocDescription": [f["form"] for f in fl],
    }
    return {
        "cik": str(cik),
        "entityType": "operating",
        "sic": c["sic"],
        "sicDescription": c["sicd"],
        "name": c["name"],
        "tickers": c["tickers"],
        "exchanges": c["exchanges"],
        "ein": "942404110",
        "category": c["category"],
        "fiscalYearEnd": c["fye"],
        "stateOfIncorporation": c["state"],
        "stateOfIncorporationDescription": c["state"],
        "addresses": {"business": {"city": "Cupertino", "stateOrCountry": "CA"}},
        "formerNames": [{"name": "APPLE COMPUTER INC", "from": "1997-07-28", "to": "2007-01-04"}]
        if cik == APPLE
        else [],
        "website": "",
        "phone": "",
        "filings": {"recent": recent, "files": []},
    }


def submissions_zip_bytes(split_apple_pages: bool = True) -> bytes:
    """submissions.zip with one overflow page for Apple (tests page merging)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for cik in COMPANIES:
            doc = submissions_doc(cik)
            if cik == APPLE and split_apple_pages:
                recent = doc["filings"]["recent"]
                n = len(recent["accessionNumber"])
                head = {k: v[: n - 3] for k, v in recent.items()}
                tail = {k: v[n - 3 :] for k, v in recent.items()}
                doc["filings"]["recent"] = head
                doc["filings"]["files"] = [{"name": f"CIK{cik:010d}-submissions-001.json", "filingCount": 3}]
                zf.writestr(f"CIK{cik:010d}-submissions-001.json", orjson.dumps(tail))
            zf.writestr(f"CIK{cik:010d}.json", orjson.dumps(doc))
        zf.writestr("placeholder.txt", "")
    return buf.getvalue()


def company_tickers_exchange_json() -> bytes:
    rows = []
    for cik, c in COMPANIES.items():
        for t, ex in zip(c["tickers"], c["exchanges"], strict=True):
            rows.append([cik, c["name"], t, ex])
    return orjson.dumps({"fields": ["cik", "name", "ticker", "exchange"], "data": rows})


def daily_index_text(day: date, filings: list[tuple[int, str, str]]) -> str:
    """master.YYYYMMDD.idx for the given (cik, form, accession) rows."""
    lines = [
        "Description:           Master Index of EDGAR Dissemination Feed by Company Name",
        f"Last Data Received:    {day.strftime('%B %d, %Y')}",
        "Comments:              webmaster@sec.gov",
        "Anonymous FTP:         ftp://ftp.sec.gov/edgar/",
        "",
        "",
        "",
        "CIK|Company Name|Form Type|Date Filed|File Name",
        "-" * 80,
    ]
    for cik, form, acc in filings:
        lines.append(
            f"{cik}|{COMPANIES[cik]['name'].upper()}|{form}|{day.strftime('%Y%m%d')}|edgar/data/{cik}/{acc}.txt"
        )
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------------------------
# Financial numbers (USD, full units). Every identity checked by checks.py holds unless noted.
# ----------------------------------------------------------------------------------------------
def _is(rev, cogs, rd, sga, nonop, tax):
    gp = rev - cogs
    opex = rd + sga
    opinc = gp - opex
    pretax = opinc + nonop
    ni = pretax - tax
    return {
        "RevenueFromContractWithCustomerExcludingAssessedTax": rev,
        "CostOfGoodsAndServicesSold": cogs,
        "GrossProfit": gp,
        "ResearchAndDevelopmentExpense": rd,
        "SellingGeneralAndAdministrativeExpense": sga,
        "OperatingExpenses": opex,
        "OperatingIncomeLoss": opinc,
        "NonoperatingIncomeExpense": nonop,
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": pretax,
        "IncomeTaxExpenseBenefit": tax,
        "NetIncomeLoss": ni,
    }


def _bs(cash, assets_current, assets, liab_current, liab, equity):
    return {
        "CashAndCashEquivalentsAtCarryingValue": cash,
        "AssetsCurrent": assets_current,
        "Assets": assets,
        "LiabilitiesCurrent": liab_current,
        "Liabilities": liab,
        "StockholdersEquity": equity,
        "LiabilitiesAndStockholdersEquity": liab + equity,
    }


CASH_CONCEPT = "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
# Concepts reported as a point in time even when presented on a duration statement.
INSTANT_CONCEPTS = frozenset({CASH_CONCEPT, "CashAndCashEquivalentsAtCarryingValue"})

# Opening and closing cash per period. In real SEC data these are *instants* (tag.iord = 'I',
# num.qtrs = 0) presented on the cash flow statement, on two lines carrying the same concept --
# "beginning balances" and "ending balances". APPLE_CASH[key] = (opening, closing).
APPLE_CASH: dict[tuple, tuple[float, float]] = {}


def _cf(ops, inv, repurchase, dividends, opening, closing):
    """Duration lines of the cash flow statement.

    Opening and closing cash come from the balance sheet, so the three statements agree and the cash
    chains from one period to the next; "other financing activities" absorbs the difference, which keeps
    operating + investing + financing exactly equal to the change in cash.
    """
    change = closing - opening
    fin = change - ops - inv
    other_fin = fin + repurchase + dividends
    return {
        "NetCashProvidedByUsedInOperatingActivities": ops,
        "NetCashProvidedByUsedInInvestingActivities": inv,
        "PaymentsForRepurchaseOfCommonStock": repurchase,
        "PaymentsOfDividends": dividends,
        "ProceedsFromPaymentsForOtherFinancingActivities": other_fin,
        "NetCashProvidedByUsedInFinancingActivities": fin,
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect": change,
    }


# Apple-like periods: (start, end) exact dates.
P_FY2024 = ("2023-10-01", "2024-09-28")
P_FY2025 = ("2024-09-29", "2025-09-27")
P_Q1_2025 = ("2024-09-29", "2024-12-28")
P_Q1_2026 = ("2025-09-28", "2025-12-27")
P_Q2_2026 = ("2025-12-28", "2026-03-28")
P_H1_2026 = ("2025-09-28", "2026-03-28")
P_Q2_2025 = ("2024-12-29", "2025-03-29")
P_H1_2025 = ("2024-09-29", "2025-03-29")

APPLE_IS = {
    P_FY2024: _is(391_035 * M, 210_352 * M, 31_370 * M, 26_097 * M, 269 * M, 29_749 * M),
    # FY2024 as restated in the FY2025 10-K (+1m revenue)
    ("restated", *P_FY2024): _is(391_036 * M, 210_352 * M, 31_370 * M, 26_097 * M, 269 * M, 29_749 * M),
    P_FY2025: _is(416_161 * M, 220_000 * M, 34_000 * M, 27_000 * M, -300 * M, 22_000 * M),
    P_Q1_2025: _is(124_300 * M, 66_025 * M, 8_268 * M, 7_175 * M, -248 * M, 6_254 * M),
    P_Q1_2026: _is(140_000 * M, 75_000 * M, 8_500 * M, 7_500 * M, 0, 8_000 * M),
    P_Q2_2026: _is(100_000 * M, 55_000 * M, 8_600 * M, 7_400 * M, 100 * M, 5_000 * M),
    P_H1_2026: _is(240_000 * M, 130_000 * M, 17_100 * M, 14_900 * M, 100 * M, 13_000 * M),
    P_Q2_2025: _is(95_359 * M, 50_492 * M, 8_550 * M, 6_728 * M, -279 * M, 4_530 * M),
    P_H1_2025: _is(219_659 * M, 116_517 * M, 16_818 * M, 13_903 * M, -527 * M, 10_784 * M),
}
APPLE_EPS = {
    P_FY2025: (7.50, 7.46),
    P_FY2024: (6.11, 6.08),
    P_Q1_2026: (2.75, 2.73),
    P_Q1_2025: (2.41, 2.40),
    P_Q2_2026: (1.90, 1.89),
    P_H1_2026: (4.65, 4.62),
    P_Q2_2025: (1.65, 1.65),
    P_H1_2025: (4.06, 4.05),
}
APPLE_BS = {
    "2024-09-28": _bs(29_943 * M, 152_987 * M, 364_980 * M, 176_392 * M, 308_030 * M, 56_950 * M),
    "2025-09-27": _bs(30_000 * M, 150_000 * M, 360_000 * M, 170_000 * M, 290_000 * M, 70_000 * M),
    "2025-12-27": _bs(32_000 * M, 155_000 * M, 370_000 * M, 172_000 * M, 295_000 * M, 75_000 * M),
    "2026-03-28": _bs(33_000 * M, 156_000 * M, 372_000 * M, 173_000 * M, 296_000 * M, 76_000 * M),
    "2026-06-27": _bs(34_000 * M, 157_000 * M, 374_000 * M, 174_000 * M, 297_000 * M, 77_000 * M),
    "2023-09-30": _bs(30_737 * M, 143_566 * M, 352_583 * M, 145_308 * M, 290_437 * M, 62_146 * M),
    "2024-12-28": _bs(30_299 * M, 133_240 * M, 344_085 * M, 144_365 * M, 277_327 * M, 66_758 * M),
    "2025-03-29": _bs(28_162 * M, 129_000 * M, 331_233 * M, 143_000 * M, 264_437 * M, 66_796 * M),
}
# operating, investing, buybacks, dividends -- the rest of financing is plugged from the balance sheet
_CF_INPUTS = {
    P_FY2024: (118_254 * M, 2_935 * M, 94_949 * M, 15_234 * M),
    P_FY2025: (120_000 * M, 5_000 * M, 95_000 * M, 15_000 * M),
    P_Q1_2025: (29_935 * M, -1_445 * M, 23_600 * M, 3_860 * M),
    P_Q1_2026: (30_000 * M, -2_000 * M, 24_000 * M, 4_000 * M),
    P_H1_2026: (60_000 * M, -3_000 * M, 48_000 * M, 8_000 * M),
    P_H1_2025: (53_912 * M, 1_500 * M, 47_000 * M, 7_700 * M),
}


def _cash_at(day: str) -> float:
    return APPLE_BS[day]["CashAndCashEquivalentsAtCarryingValue"]


def _opening_day(period_start: str) -> str:
    return (date.fromisoformat(period_start) - timedelta(days=1)).isoformat()


APPLE_CF = {}
for _key, _args in _CF_INPUTS.items():
    _open, _close = _cash_at(_opening_day(_key[-2])), _cash_at(_key[-1])
    APPLE_CF[_key] = _cf(*_args, _open, _close)
    APPLE_CASH[_key] = (_open, _close)

JPM_IS_FY2025 = {
    "InterestAndDividendIncomeOperating": 180 * BILLION,
    "InterestExpense": 90 * BILLION,
    "InterestIncomeExpenseNet": 90 * BILLION,
    "ProvisionForLoanLeaseAndOtherLosses": 9 * BILLION,
    "InterestIncomeExpenseAfterProvisionForLoanLoss": 81 * BILLION,
    "NoninterestIncome": 70 * BILLION,
    "NoninterestExpense": 92 * BILLION,
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": 59 * BILLION,
    "IncomeTaxExpenseBenefit": 12 * BILLION,
    "NetIncomeLoss": 47 * BILLION,
}
JPM_BS_2025 = {
    "Assets": 4_000 * BILLION,
    "Liabilities": 3_650 * BILLION,
    "StockholdersEquity": 350 * BILLION,
    "LiabilitiesAndStockholdersEquity": 4_000 * BILLION,
}
RBC_IS_FY2025 = {"Revenue": 60 * BILLION, "ProfitLoss": 17 * BILLION}  # ifrs-full
RBC_BS_2025 = {
    "Assets": 2_100 * BILLION,
    "Liabilities": 1_970 * BILLION,
    "Equity": 130 * BILLION,
    "EquityAndLiabilities": 2_100 * BILLION,
}
BROKEN_BS_2025 = {
    "Assets": 100 * M,
    "Liabilities": 60 * M,
    "StockholdersEquity": 30 * M,
    "LiabilitiesAndStockholdersEquity": 90 * M,
}  # off by 10m
BROKEN_IS_2025 = {
    "Revenues": 50 * M,
    "CostOfRevenue": 20 * M,
    "GrossProfit": 30 * M,
    "NetIncomeLoss": 5 * M,
}


# ----------------------------------------------------------------------------------------------
# companyfacts
# ----------------------------------------------------------------------------------------------
def _fact(
    start: str | None,
    end: str,
    val: float,
    accn: str,
    fy: int,
    fp: str,
    form: str,
    filed: str,
    frame: str | None = None,
) -> dict[str, Any]:
    e: dict[str, Any] = {
        "end": end,
        "val": val,
        "accn": accn,
        "fy": fy,
        "fp": fp,
        "form": form,
        "filed": filed,
    }
    if start:
        e["start"] = start
    if frame:
        e["frame"] = frame
    return e


def _apple_facts() -> dict[str, Any]:
    us: dict[str, dict[str, Any]] = {}

    def add(concept: str, unit: str, entry: dict[str, Any], label: str | None = None) -> None:
        body = us.setdefault(concept, {"label": label or concept, "description": "", "units": {}})
        body["units"].setdefault(unit, []).append(entry)

    filings = {
        APPLE_10K_FY2024: (2024, "FY", "10-K", "2024-11-01"),
        APPLE_10K_FY2025: (2025, "FY", "10-K", "2025-10-31"),
        _acc(APPLE, 2025, 10): (2025, "Q1", "10-Q", "2025-01-31"),
        APPLE_10Q_Q1_2026: (2026, "Q1", "10-Q", "2026-01-30"),
        _acc(APPLE, 2025, 42): (2025, "Q2", "10-Q", "2025-05-02"),
        APPLE_10Q_Q2_2026: (2026, "Q2", "10-Q", "2026-05-01"),
    }
    # income statement durations per filing: which period keys each filing reports
    reported = {
        APPLE_10K_FY2024: [P_FY2024],
        APPLE_10K_FY2025: [P_FY2025, ("restated", *P_FY2024)],
        _acc(APPLE, 2025, 10): [P_Q1_2025],
        APPLE_10Q_Q1_2026: [P_Q1_2026, P_Q1_2025],
        _acc(APPLE, 2025, 42): [P_Q2_2025, P_H1_2025],
        APPLE_10Q_Q2_2026: [P_Q2_2026, P_H1_2026, P_Q2_2025, P_H1_2025],
    }
    for accn, keys in reported.items():
        fy, fp, form, filed = filings[accn]
        for key in keys:
            start, end = key[-2], key[-1]
            for concept, val in APPLE_IS[key].items():
                add(concept, "USD", _fact(start, end, val, accn, fy, fp, form, filed))
            eps_key = key if key in APPLE_EPS else (key[1], key[2])
            basic, diluted = APPLE_EPS[eps_key]
            add(
                "EarningsPerShareBasic",
                "USD/shares",
                _fact(start, end, basic, accn, fy, fp, form, filed),
                "Earnings per share, basic",
            )
            add(
                "EarningsPerShareDiluted",
                "USD/shares",
                _fact(start, end, diluted, accn, fy, fp, form, filed),
                "Earnings per share, diluted",
            )
            if key in APPLE_CF:
                for concept, val in APPLE_CF[key].items():
                    add(concept, "USD", _fact(start, end, val, accn, fy, fp, form, filed))
                opening, closing = APPLE_CASH[key]
                prior = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
                for when, val in ((prior, opening), (end, closing)):
                    add(CASH_CONCEPT, "USD", _fact(None, when, val, accn, fy, fp, form, filed))
    bs_reported = {
        APPLE_10K_FY2024: ["2024-09-28"],
        APPLE_10K_FY2025: ["2025-09-27", "2024-09-28"],
        _acc(APPLE, 2025, 10): ["2024-12-28", "2024-09-28"],
        APPLE_10Q_Q1_2026: ["2025-12-27", "2025-09-27"],
        _acc(APPLE, 2025, 42): ["2025-03-29", "2024-09-28"],
        APPLE_10Q_Q2_2026: ["2026-03-28", "2025-09-27"],
    }
    for accn, ends in bs_reported.items():
        fy, fp, form, filed = filings[accn]
        for end in ends:
            for concept, val in APPLE_BS[end].items():
                add(concept, "USD", _fact(None, end, val, accn, fy, fp, form, filed))
    dei = {
        "EntityCommonStockSharesOutstanding": {
            "label": "Entity Common Stock, Shares Outstanding",
            "description": "",
            "units": {
                "shares": [
                    _fact(
                        None,
                        "2025-10-17",
                        14_800_000_000,
                        APPLE_10K_FY2025,
                        2025,
                        "FY",
                        "10-K",
                        "2025-10-31",
                    )
                ]
            },
        }
    }
    return {"cik": APPLE, "entityName": "Apple Inc.", "facts": {"dei": dei, "us-gaap": us}}


def _simple_facts(
    cik: int,
    name: str,
    accn: str,
    fy: int,
    form: str,
    filed: str,
    start: str,
    end: str,
    is_items: dict[str, float],
    bs_items: dict[str, float],
    taxonomy: str = "us-gaap",
) -> dict[str, Any]:
    tx: dict[str, Any] = {}
    for c, v in is_items.items():
        tx[c] = {
            "label": c,
            "description": "",
            "units": {"USD": [_fact(start, end, v, accn, fy, "FY", form, filed)]},
        }
    for c, v in bs_items.items():
        tx[c] = {
            "label": c,
            "description": "",
            "units": {"USD": [_fact(None, end, v, accn, fy, "FY", form, filed)]},
        }
    return {"cik": cik, "entityName": name, "facts": {taxonomy: tx}}


def companyfacts_docs() -> dict[int, dict[str, Any]]:
    return {
        APPLE: _apple_facts(),
        JPM: _simple_facts(
            JPM,
            "JPMorgan Chase & Co",
            JPM_10K_FY2025,
            2025,
            "10-K",
            "2026-02-20",
            "2025-01-01",
            "2025-12-31",
            JPM_IS_FY2025,
            JPM_BS_2025,
        ),
        RBC: _simple_facts(
            RBC,
            "Royal Bank of Canada",
            RBC_40F_FY2025,
            2025,
            "40-F",
            "2025-12-03",
            "2024-11-01",
            "2025-10-31",
            RBC_IS_FY2025,
            RBC_BS_2025,
            taxonomy="ifrs-full",
        ),
        BROKEN: _simple_facts(
            BROKEN,
            "Broken Books Ltd",
            BROKEN_10K,
            2025,
            "10-K",
            "2026-03-30",
            "2025-01-01",
            "2025-12-31",
            BROKEN_IS_2025,
            BROKEN_BS_2025,
        ),
    }


def companyfacts_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for cik, doc in companyfacts_docs().items():
            zf.writestr(f"CIK{cik:010d}.json", orjson.dumps(doc))
    return buf.getvalue()


# ----------------------------------------------------------------------------------------------
# FSDS (sub / num / pre / tag)
# ----------------------------------------------------------------------------------------------
SUB_COLS = [
    "adsh",
    "cik",
    "name",
    "sic",
    "countryba",
    "stprba",
    "cityba",
    "zipba",
    "bas1",
    "bas2",
    "baph",
    "countryma",
    "stprma",
    "cityma",
    "zipma",
    "mas1",
    "mas2",
    "countryinc",
    "stprinc",
    "ein",
    "former",
    "changed",
    "afs",
    "wksi",
    "fye",
    "form",
    "period",
    "fy",
    "fp",
    "filed",
    "prevrpt",
    "detail",
    "instance",
    "nciks",
    "aciks",
]
NUM_COLS = ["adsh", "tag", "version", "coreg", "ddate", "qtrs", "uom", "value", "footnote"]
PRE_COLS = [
    "adsh",
    "report",
    "line",
    "stmt",
    "inpth",
    "rfile",
    "tag",
    "version",
    "plabel",
    "negating",
]
TAG_COLS = ["tag", "version", "custom", "abstract", "datatype", "iord", "crdr", "tlabel", "doc"]
V = "us-gaap/2025"
VI = "ifrs-full/2025"

# Apple as-reported presentation: (stmt, report, line, tag, label, negating, abstract)
APPLE_PRE: list[tuple[str, int, int, str, str, int, int]] = [
    ("IS", 2, 1, "IncomeStatementAbstract", "CONSOLIDATED STATEMENTS OF OPERATIONS", 0, 1),
    ("IS", 2, 2, "RevenueFromContractWithCustomerExcludingAssessedTax", "Total net sales", 0, 0),
    ("IS", 2, 3, "CostOfGoodsAndServicesSold", "Total cost of sales", 0, 0),
    ("IS", 2, 4, "GrossProfit", "Gross margin", 0, 0),
    ("IS", 2, 5, "OperatingExpensesAbstract", "Operating expenses:", 0, 1),
    ("IS", 2, 6, "ResearchAndDevelopmentExpense", "Research and development", 0, 0),
    (
        "IS",
        2,
        7,
        "SellingGeneralAndAdministrativeExpense",
        "Selling, general and administrative",
        0,
        0,
    ),
    ("IS", 2, 8, "OperatingExpenses", "Total operating expenses", 0, 0),
    ("IS", 2, 9, "OperatingIncomeLoss", "Operating income", 0, 0),
    ("IS", 2, 10, "NonoperatingIncomeExpense", "Other income/(expense), net", 0, 0),
    (
        "IS",
        2,
        11,
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "Income before provision for income taxes",
        0,
        0,
    ),
    ("IS", 2, 12, "IncomeTaxExpenseBenefit", "Provision for income taxes", 0, 0),
    ("IS", 2, 13, "NetIncomeLoss", "Net income", 0, 0),
    ("IS", 2, 14, "EarningsPerShareBasic", "Basic (in dollars per share)", 0, 0),
    ("IS", 2, 15, "EarningsPerShareDiluted", "Diluted (in dollars per share)", 0, 0),
    ("BS", 4, 1, "StatementOfFinancialPositionAbstract", "CONSOLIDATED BALANCE SHEETS", 0, 1),
    ("BS", 4, 2, "CashAndCashEquivalentsAtCarryingValue", "Cash and cash equivalents", 0, 0),
    ("BS", 4, 3, "AssetsCurrent", "Total current assets", 0, 0),
    ("BS", 4, 4, "Assets", "Total assets", 0, 0),
    ("BS", 4, 5, "LiabilitiesCurrent", "Total current liabilities", 0, 0),
    ("BS", 4, 6, "Liabilities", "Total liabilities", 0, 0),
    ("BS", 4, 7, "StockholdersEquity", "Total shareholders' equity", 0, 0),
    (
        "BS",
        4,
        8,
        "LiabilitiesAndStockholdersEquity",
        "Total liabilities and shareholders' equity",
        0,
        0,
    ),
    ("CF", 7, 1, "StatementOfCashFlowsAbstract", "CONSOLIDATED STATEMENTS OF CASH FLOWS", 0, 1),
    # The opening and closing cash lines carry the SAME concept and differ only by label, exactly as
    # real filings present them, and both are instants (tag.iord = 'I', num.qtrs = 0).
    ("CF", 7, 2, CASH_CONCEPT, "Cash, cash equivalents and restricted cash, beginning balances", 0, 0),
    ("CF", 7, 3, "NetCashProvidedByUsedInOperatingActivities", "Cash generated by operating activities", 0, 0),
    (
        "CF",
        7,
        4,
        "NetCashProvidedByUsedInInvestingActivities",
        "Cash generated by/(used in) investing activities",
        0,
        0,
    ),
    ("CF", 7, 5, "PaymentsForRepurchaseOfCommonStock", "Repurchases of common stock", 1, 0),
    ("CF", 7, 6, "PaymentsOfDividends", "Payments for dividends and dividend equivalents", 1, 0),
    ("CF", 7, 7, "ProceedsFromPaymentsForOtherFinancingActivities", "Other", 0, 0),
    ("CF", 7, 8, "NetCashProvidedByUsedInFinancingActivities", "Cash used in financing activities", 0, 0),
    (
        "CF",
        7,
        9,
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "Increase/(Decrease) in cash, cash equivalents and restricted cash",
        0,
        0,
    ),
    ("CF", 7, 10, CASH_CONCEPT, "Cash, cash equivalents and restricted cash, ending balances", 0, 0),
]
APPLE_TAGS = {t[3]: (t[6], "duration" if t[0] in ("IS", "CF") else "instant") for t in APPLE_PRE}


def _dedupe_num(rows: list[str]) -> list[str]:
    """`num` is keyed by (adsh, tag, version, coreg, ddate, qtrs), so the SEC can publish only one value
    per key. A period's opening balance and the previous period's closing balance are the same fact, so
    generating both would produce a row real data cannot contain."""
    seen: set[tuple[str, ...]] = set()
    out = []
    for row in rows:
        key = tuple(row.split("\t")[:6])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _fsds_row(cols: list[str], **kw: Any) -> str:
    return "\t".join("" if kw.get(c) is None else str(kw.get(c)) for c in cols)


def _sub(adsh: str, cik: int, form: str, period: str, fy: int, fp: str, filed: str, fye: str) -> str:
    c = COMPANIES[cik]
    return _fsds_row(
        SUB_COLS,
        adsh=adsh,
        cik=cik,
        name=c["name"].upper(),
        sic=c["sic"],
        countryba="US",
        stprba="CA",
        cityba="CUPERTINO",
        countryinc="US",
        stprinc=c["state"],
        ein="942404110",
        afs="1-LAF",
        wksi=1,
        fye=fye,
        form=form,
        period=period.replace("-", ""),
        fy=fy,
        fp=fp,
        filed=filed.replace("-", ""),
        prevrpt=0,
        detail=1,
        instance=f"{adsh}.xml",
        nciks=1,
    )


def _ddate(d: str) -> str:
    """FSDS rounds period ends to the nearest month end."""
    from filings_hub.ingest.sync_statements import month_end_round

    return month_end_round(date.fromisoformat(d)).strftime("%Y%m%d")


def _apple_num(adsh: str, is_keys: list, bs_ends: list[str], cf_keys: list) -> list[str]:
    rows = []
    for key in is_keys:
        start, end = key[-2], key[-1]
        qtrs = (
            4
            if "FY" in str(key) or (date.fromisoformat(end) - date.fromisoformat(start)).days > 300
            else max(1, round((date.fromisoformat(end) - date.fromisoformat(start)).days / 91))
        )
        for concept, val in APPLE_IS[key].items():
            rows.append(
                _fsds_row(
                    NUM_COLS,
                    adsh=adsh,
                    tag=concept,
                    version=V,
                    ddate=_ddate(end),
                    qtrs=qtrs,
                    uom="USD",
                    value=val,
                )
            )
        eps_key = key if key in APPLE_EPS else (key[1], key[2])
        b, d = APPLE_EPS[eps_key]
        rows.append(
            _fsds_row(
                NUM_COLS,
                adsh=adsh,
                tag="EarningsPerShareBasic",
                version=V,
                ddate=_ddate(end),
                qtrs=qtrs,
                uom="USD/shares",
                value=b,
            )
        )
        rows.append(
            _fsds_row(
                NUM_COLS,
                adsh=adsh,
                tag="EarningsPerShareDiluted",
                version=V,
                ddate=_ddate(end),
                qtrs=qtrs,
                uom="USD/shares",
                value=d,
            )
        )
    for end in bs_ends:
        for concept, val in APPLE_BS[end].items():
            rows.append(
                _fsds_row(
                    NUM_COLS,
                    adsh=adsh,
                    tag=concept,
                    version=V,
                    ddate=_ddate(end),
                    qtrs=0,
                    uom="USD",
                    value=val,
                )
            )
    for key in cf_keys:
        start, end = key
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
        qtrs = 4 if days > 300 else max(1, round(days / 91))
        for concept, val in APPLE_CF[key].items():
            rows.append(
                _fsds_row(
                    NUM_COLS, adsh=adsh, tag=concept, version=V, ddate=_ddate(end), qtrs=qtrs, uom="USD", value=val
                )
            )
        # opening and closing cash are instants: qtrs = 0, dated the day before the period starts and
        # the day the period ends
        opening, closing = APPLE_CASH[key]
        prior = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
        for when, val in ((prior, opening), (end, closing)):
            rows.append(
                _fsds_row(
                    NUM_COLS, adsh=adsh, tag=CASH_CONCEPT, version=V, ddate=_ddate(when), qtrs=0, uom="USD", value=val
                )
            )
    # a co-registrant row that must be ignored
    rows.append(
        _fsds_row(
            NUM_COLS,
            adsh=adsh,
            tag="Assets",
            version=V,
            coreg="SubCo",
            ddate=_ddate(bs_ends[0]),
            qtrs=0,
            uom="USD",
            value=1,
        )
    )
    return rows


def _apple_pre(adsh: str) -> list[str]:
    return [
        _fsds_row(
            PRE_COLS,
            adsh=adsh,
            report=r,
            line=ln,
            stmt=s,
            inpth=0,
            rfile="H",
            tag=tag,
            version=V,
            plabel=label,
            negating=neg,
        )
        for s, r, ln, tag, label, neg, _ in APPLE_PRE
    ]


def _tags_for(pre_defs: list[tuple], version: str = V) -> list[str]:
    seen = set()
    rows = []
    for s, _r, _l, tag, label, _neg, abstract in pre_defs:
        if tag in seen:
            continue
        seen.add(tag)
        iord = "I" if (s == "BS" or tag in INSTANT_CONCEPTS) else "D"
        datatype = "" if abstract else ("perShare" if "PerShare" in tag else "monetary")
        rows.append(
            _fsds_row(
                TAG_COLS,
                tag=tag,
                version=version,
                custom=0,
                abstract=abstract,
                datatype=datatype,
                iord=iord,
                crdr="C" if "Liabilit" in tag or "Equity" in tag or "Revenue" in tag else "D",
                tlabel=label,
                doc="",
            )
        )
    return rows


JPM_PRE = [
    ("IS", 2, 1, "IncomeStatementAbstract", "Consolidated statements of income", 0, 1),
    ("IS", 2, 2, "InterestAndDividendIncomeOperating", "Interest income", 0, 0),
    ("IS", 2, 3, "InterestExpense", "Interest expense", 0, 0),
    ("IS", 2, 4, "InterestIncomeExpenseNet", "Net interest income", 0, 0),
    ("IS", 2, 5, "ProvisionForLoanLeaseAndOtherLosses", "Provision for credit losses", 0, 0),
    (
        "IS",
        2,
        6,
        "InterestIncomeExpenseAfterProvisionForLoanLoss",
        "Net interest income after provision for credit losses",
        0,
        0,
    ),
    ("IS", 2, 7, "NoninterestIncome", "Total noninterest revenue", 0, 0),
    ("IS", 2, 8, "NoninterestExpense", "Total noninterest expense", 0, 0),
    (
        "IS",
        2,
        9,
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "Income before income tax expense",
        0,
        0,
    ),
    ("IS", 2, 10, "IncomeTaxExpenseBenefit", "Income tax expense", 0, 0),
    ("IS", 2, 11, "NetIncomeLoss", "Net income", 0, 0),
    ("BS", 4, 1, "Assets", "Total assets", 0, 0),
    ("BS", 4, 2, "Liabilities", "Total liabilities", 0, 0),
    ("BS", 4, 3, "StockholdersEquity", "Total stockholders' equity", 0, 0),
    (
        "BS",
        4,
        4,
        "LiabilitiesAndStockholdersEquity",
        "Total liabilities and stockholders' equity",
        0,
        0,
    ),
]
RBC_PRE = [
    ("IS", 2, 1, "Revenue", "Total revenue", 0, 0),
    ("IS", 2, 2, "ProfitLoss", "Net income", 0, 0),
    ("BS", 4, 1, "Assets", "Total assets", 0, 0),
    ("BS", 4, 2, "Liabilities", "Total liabilities", 0, 0),
    ("BS", 4, 3, "Equity", "Total equity", 0, 0),
    ("BS", 4, 4, "EquityAndLiabilities", "Total liabilities and equity", 0, 0),
]
BROKEN_PRE = [
    ("IS", 2, 1, "Revenues", "Revenues", 0, 0),
    ("IS", 2, 2, "CostOfRevenue", "Cost of revenue", 0, 0),
    ("IS", 2, 3, "GrossProfit", "Gross profit", 0, 0),
    ("IS", 2, 4, "NetIncomeLoss", "Net loss", 0, 0),
    ("BS", 4, 1, "Assets", "Total assets", 0, 0),
    ("BS", 4, 2, "Liabilities", "Total liabilities", 0, 0),
    ("BS", 4, 3, "StockholdersEquity", "Total equity", 0, 0),
    ("BS", 4, 4, "LiabilitiesAndStockholdersEquity", "Total liabilities and equity", 0, 0),
]


def _simple_num(
    adsh: str, end: str, is_items: dict[str, float], bs_items: dict[str, float], version: str = V
) -> list[str]:
    rows = [
        _fsds_row(
            NUM_COLS,
            adsh=adsh,
            tag=c,
            version=version,
            ddate=_ddate(end),
            qtrs=4,
            uom="USD",
            value=v,
        )
        for c, v in is_items.items()
    ]
    rows += [
        _fsds_row(
            NUM_COLS,
            adsh=adsh,
            tag=c,
            version=version,
            ddate=_ddate(end),
            qtrs=0,
            uom="USD",
            value=v,
        )
        for c, v in bs_items.items()
    ]
    return rows


def _simple_pre(adsh: str, pre_defs: list[tuple], version: str = V) -> list[str]:
    return [
        _fsds_row(
            PRE_COLS,
            adsh=adsh,
            report=r,
            line=ln,
            stmt=s,
            inpth=0,
            rfile="H",
            tag=tag,
            version=version,
            plabel=label,
            negating=neg,
        )
        for s, r, ln, tag, label, neg, _ in pre_defs
    ]


def fsds_quarters() -> dict[str, dict[str, str]]:
    """Two published quarters. 2026q2 (Apple's Q2 10-Q) is deliberately absent -> fallback path."""
    q4 = {
        "sub": [
            _sub(APPLE_10K_FY2025, APPLE, "10-K", "2025-09-30", 2025, "FY", "2025-10-31", "0930"),
            _sub(RBC_40F_FY2025, RBC, "40-F", "2025-10-31", 2025, "FY", "2025-12-03", "1031"),
        ],
        "num": _apple_num(
            APPLE_10K_FY2025,
            [P_FY2025, ("restated", *P_FY2024)],
            ["2025-09-27", "2024-09-28"],
            [P_FY2025, P_FY2024],
        )
        + _simple_num(RBC_40F_FY2025, "2025-10-31", RBC_IS_FY2025, RBC_BS_2025, VI),
        "pre": _apple_pre(APPLE_10K_FY2025) + _simple_pre(RBC_40F_FY2025, RBC_PRE, VI),
        "tag": _tags_for(APPLE_PRE) + _tags_for(RBC_PRE, VI),  # distinct (tag, version) per quarter
    }
    q1 = {
        "sub": [
            _sub(APPLE_10Q_Q1_2026, APPLE, "10-Q", "2025-12-31", 2026, "Q1", "2026-01-30", "0930"),
            _sub(JPM_10K_FY2025, JPM, "10-K", "2025-12-31", 2025, "FY", "2026-02-20", "1231"),
            _sub(BROKEN_10K, BROKEN, "10-K", "2025-12-31", 2025, "FY", "2026-03-30", "1231"),
        ],
        "num": _apple_num(
            APPLE_10Q_Q1_2026,
            [P_Q1_2026, P_Q1_2025],
            ["2025-12-27", "2025-09-27"],
            [P_Q1_2026, P_Q1_2025],
        )
        + _simple_num(JPM_10K_FY2025, "2025-12-31", JPM_IS_FY2025, JPM_BS_2025)
        + _simple_num(BROKEN_10K, "2025-12-31", BROKEN_IS_2025, BROKEN_BS_2025),
        "pre": _apple_pre(APPLE_10Q_Q1_2026)
        + _simple_pre(JPM_10K_FY2025, JPM_PRE)
        + _simple_pre(BROKEN_10K, BROKEN_PRE),
        "tag": _tags_for(APPLE_PRE + JPM_PRE + BROKEN_PRE),
    }
    out = {}
    for name, tables in (("2025q4", q4), ("2026q1", q1)):
        tables["num"] = _dedupe_num(tables["num"])
        cols = {"sub": SUB_COLS, "num": NUM_COLS, "pre": PRE_COLS, "tag": TAG_COLS}
        out[name] = {t: "\t".join(cols[t]) + "\n" + "\n".join(rows) + "\n" for t, rows in tables.items()}
    return out


def fsds_zip_bytes(quarter: str) -> bytes:
    tables = fsds_quarters()[quarter]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for t, text in tables.items():
            zf.writestr(f"{t}.txt", text)
        zf.writestr("readme.htm", "<html>FSDS</html>")
    return buf.getvalue()


# ----------------------------------------------------------------------------------------------
# Seed a lake's raw/ area so the whole backfill runs offline
# ----------------------------------------------------------------------------------------------
def seed_raw(storage, day: date | None = None) -> date:
    from filings_hub.lake import layout

    day = day or date(2026, 9, 11)
    storage.write_bytes(layout.raw_submissions_zip(day), submissions_zip_bytes())
    storage.write_bytes(layout.raw_companyfacts_zip(day), companyfacts_zip_bytes())
    storage.write_bytes(layout.raw_company_tickers(day), company_tickers_exchange_json())
    for q in fsds_quarters():
        storage.write_bytes(layout.raw_fsds_zip(q), fsds_zip_bytes(q))
    return day


# ----------------------------------------------------------------------------------------------
# "The next day": Apple files FY2026 results (used by the refresh tests)
# ----------------------------------------------------------------------------------------------
P_FY2026 = ("2025-09-28", "2026-09-26")
APPLE_8K_FY2026 = _acc(APPLE, 2026, 70)
APPLE_10K_FY2026 = _acc(APPLE, 2026, 72)
APPLE_FY2026_FILINGS = [
    {
        "acc": APPLE_8K_FY2026,
        "form": "8-K",
        "filed": "2026-10-30",
        "report": "2026-10-30",
        "items": "2.02,9.01",
        "doc": "aapl-20261030.htm",
    },
    {
        "acc": APPLE_10K_FY2026,
        "form": "10-K",
        "filed": "2026-11-02",
        "report": "2026-09-26",
        "items": "",
        "doc": "aapl-20260926.htm",
    },
]
APPLE_IS[P_FY2026] = _is(450_000 * M, 235_000 * M, 36_000 * M, 28_000 * M, 500 * M, 24_000 * M)
APPLE_EPS[P_FY2026] = (8.40, 8.35)
APPLE_BS["2026-09-26"] = _bs(35_000 * M, 158_000 * M, 380_000 * M, 175_000 * M, 300_000 * M, 80_000 * M)
_open_fy2026, _close_fy2026 = _cash_at(_opening_day(P_FY2026[0])), _cash_at(P_FY2026[1])
APPLE_CF[P_FY2026] = _cf(125_000 * M, 4_000 * M, 96_000 * M, 16_000 * M, _open_fy2026, _close_fy2026)
APPLE_CASH[P_FY2026] = (_open_fy2026, _close_fy2026)


def apple_companyfacts_with_fy2026() -> dict[str, Any]:
    doc = _apple_facts()
    us = doc["facts"]["us-gaap"]
    fy, fp, form, filed = 2026, "FY", "10-K", "2026-11-02"
    start, end = P_FY2026

    def add(concept: str, unit: str, entry: dict[str, Any]) -> None:
        us.setdefault(concept, {"label": concept, "description": "", "units": {}})["units"].setdefault(unit, []).append(
            entry
        )

    for concept, val in APPLE_IS[P_FY2026].items():
        add(concept, "USD", _fact(start, end, val, APPLE_10K_FY2026, fy, fp, form, filed))
    b, d = APPLE_EPS[P_FY2026]
    add(
        "EarningsPerShareBasic",
        "USD/shares",
        _fact(start, end, b, APPLE_10K_FY2026, fy, fp, form, filed),
    )
    add(
        "EarningsPerShareDiluted",
        "USD/shares",
        _fact(start, end, d, APPLE_10K_FY2026, fy, fp, form, filed),
    )
    for concept, val in APPLE_CF[P_FY2026].items():
        add(concept, "USD", _fact(start, end, val, APPLE_10K_FY2026, fy, fp, form, filed))
    for end_ in ("2026-09-26", "2025-09-27"):
        for concept, val in APPLE_BS[end_].items():
            add(concept, "USD", _fact(None, end_, val, APPLE_10K_FY2026, fy, fp, form, filed))
    return doc
