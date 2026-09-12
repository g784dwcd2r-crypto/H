"""Canonical paths inside the lake. Every module goes through here so the layout lives in one place.

Layout (relative to LAKE_ROOT):

  raw/edgar/submissions/{yyyy-mm-dd}/submissions.zip        bulk filing indexes
  raw/edgar/companyfacts/{yyyy-mm-dd}/companyfacts.zip      bulk XBRL facts
  raw/edgar/fsds/{yyyy}q{n}.zip                             Financial Statement Data Sets (immutable)
  raw/edgar/company_tickers/{yyyy-mm-dd}/company_tickers_exchange.json
  raw/edgar/daily-index/{yyyy}/master.{yyyymmdd}.idx
  raw/edgar/api/submissions/{yyyy-mm-dd}/CIK##########.json  per-company API responses
  raw/edgar/api/companyfacts/{yyyy-mm-dd}/CIK##########.json

  companies/companies.parquet
  companies/tickers.parquet
  filings/year={yyyy}/*.parquet                              partitioned by filed year
  periods/periods.parquet
  facts/cik={cik}/*.parquet                                  partitioned by CIK
  fsds/{sub,num,pre,tag}/quarter={yyyy}q{n}/*.parquet
  statements/cik={cik}/*.parquet
  statement_checks/cik={cik}/*.parquet
  run_log/*.parquet
"""

from __future__ import annotations

from datetime import date

RAW = "raw/edgar"


def raw_submissions_zip(day: date) -> str:
    return f"{RAW}/submissions/{day.isoformat()}/submissions.zip"


def raw_companyfacts_zip(day: date) -> str:
    return f"{RAW}/companyfacts/{day.isoformat()}/companyfacts.zip"


def raw_fsds_zip(quarter: str) -> str:
    return f"{RAW}/fsds/{quarter}.zip"


def raw_company_tickers(day: date) -> str:
    return f"{RAW}/company_tickers/{day.isoformat()}/company_tickers_exchange.json"


def raw_daily_index(day: date) -> str:
    return f"{RAW}/daily-index/{day.year}/master.{day.strftime('%Y%m%d')}.idx"


def raw_api_submissions(day: date, cik: int) -> str:
    return f"{RAW}/api/submissions/{day.isoformat()}/CIK{cik:010d}.json"


def raw_api_companyfacts(day: date, cik: int) -> str:
    return f"{RAW}/api/companyfacts/{day.isoformat()}/CIK{cik:010d}.json"


COMPANIES = "companies/companies.parquet"
TICKERS = "companies/tickers.parquet"
FILINGS = "filings"
PERIODS = "periods/periods.parquet"
FACTS = "facts"
FSDS = "fsds"
STATEMENTS = "statements"
STATEMENT_CHECKS = "statement_checks"
RUN_LOG = "run_log"


def filings_year_dir(year: int) -> str:
    return f"{FILINGS}/year={year}"


def facts_cik_dir(cik: int) -> str:
    return f"{FACTS}/cik={cik}"


def statements_cik_dir(cik: int) -> str:
    return f"{STATEMENTS}/cik={cik}"


def statement_checks_cik_dir(cik: int) -> str:
    return f"{STATEMENT_CHECKS}/cik={cik}"


def fsds_table_dir(table: str, quarter: str) -> str:
    return f"{FSDS}/{table}/quarter={quarter}"
