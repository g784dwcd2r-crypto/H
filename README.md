# Filings Hub

Any SEC-registered company → clean, period-organised filing hub → as-reported financial statements → Excel. Refreshed daily.

This repository is **Layer 1** of the plan in [`docs/layer1_execution_plan.md`](docs/layer1_execution_plan.md): the data foundation (Phase 1) and the API (Phase 2). No user accounts, no NLP, no non-US filers.

## Three commands

```bash
cp .env.example .env            # set SEC_USER_AGENT="Your Name you@example.com" (required by the SEC), LAKE_ROOT, DATABASE_URL
uv venv && uv pip install -e ".[dev]"

filings-hub backfill            # bulk: submissions.zip + companyfacts.zip + FSDS quarters -> lake -> Postgres (hours)
filings-hub refresh             # daily: yesterday's daily index -> new filings/facts/statements -> Postgres -> run_log
filings-hub export AAPL --periods "FY2025,Q1 2026" --out aapl.xlsx
```

No SEC access at hand? `filings-hub demo` seeds the lake with synthetic, format-faithful EDGAR data and runs the whole pipeline in a second; then `filings-hub export AAPL` and `filings-hub api` work against it.

## How it is built

```
SEC EDGAR ──bulk zips / daily index / per-company API──▶ raw/ (immutable, dated)
                                                            │
        ┌───────────────────────────────────────────────────┴──────────────────────────┐
        ▼                                                                              ▼
 submissions.zip ─▶ filings/ ─▶ periods/ (FY2025, Q1 2026, 8-K 2.02, amendments)   companyfacts.zip ─▶ facts/cik=…
 company_tickers ─▶ companies/, tickers/                                               │ (dedupe: latest filed = current; history kept)
        │                                                                              │
        ▼                                                                              ▼
 FSDS quarterly zips (sub/num/pre/tag) ─▶ fsds/ ─▶ statements/cik=… (as reported: company's own line order + labels)
                                                     ▲   facts fallback for filings FSDS has not covered yet (provisional)
                                                     │   arithmetic checks per statement (checks_passed)
                                                     ▼
                                    Postgres serving tables (companies, tickers, filings, periods, statements, statement_checks, run_log)
                                                     ▼
                                    FastAPI  ──  Excel export (one sheet per statement, periods as columns, Source sheet)
```

Design choices from the plan, as implemented:

1. **Bulk files, not per-company calls.** Backfill downloads `submissions.zip`, `companyfacts.zip` and every FSDS quarter once. The per-company API is used only by the daily refresh, for companies that filed yesterday.
2. **As-reported structure from the SEC's Financial Statement Data Sets.** `pre` gives the statement, line order and the company's own labels; `num` the values; `tag` the attributes. No presentation-linkbase parsing.
3. **Parquet + DuckDB to build, Postgres to serve.** Facts (~100M rows) stay in the lake, partitioned by CIK. Only the serving tables go to Postgres. Without `DATABASE_URL` everything (API, export, tests) runs straight off the lake with DuckDB.
4. **Acceptance tests define "done".** `tests/` cover every checklist item that can be verified offline; the run log and `filings-hub quality` cover the rest.

## Lake layout

```
$LAKE_ROOT/
  raw/edgar/{submissions,companyfacts,company_tickers}/{yyyy-mm-dd}/…   bulk downloads (never re-fetched)
  raw/edgar/fsds/{yyyy}q{n}.zip                                          FSDS quarters (immutable)
  raw/edgar/daily-index/{yyyy}/master.{yyyymmdd}.idx                     daily increments
  raw/edgar/api/{submissions,companyfacts}/{yyyy-mm-dd}/CIK##########.json
  companies/{companies,tickers,headers}.parquet
  filings/year={yyyy}/*.parquet
  periods/periods.parquet
  facts/cik={cik}/part-0.parquet
  fsds/{sub,num,pre,tag}/quarter={yyyy}q{n}/part-0.parquet
  statements/cik={cik}/{fsds_{quarter}_*.parquet | fallback_{accession}.parquet}
  statement_checks/cik={cik}/…
  run_log/*.parquet
```

`LAKE_ROOT` can be a local directory or `s3://bucket/prefix` (`pip install -e ".[s3]"`; DuckDB reads S3 through `httpfs` with the AWS variables in `.env`).

## The rules that matter

* **Period labels.** Fiscal year = calendar year in which the fiscal year *ends* (Apple's quarter ending December 2025 is `Q1 2026`). The fiscal quarter is measured against the company's *actual* next 10-K report date when one exists, else the nominal `fiscalYearEnd` from EDGAR, so 52/53-week years and fiscal-year-end changes label correctly. Transition periods get a `T` suffix.
* **Earnings release.** The earliest 8-K with item 2.02 filed within 60 days (quarters) / 90 days (annual) after the period end.
* **Amendments.** `10-K/A`, `10-Q/A` hang off the original period (`amendment_accessions`).
* **Facts dedupe.** Same (concept, unit, period) reported in several filings → the latest filed is `is_current`; all values stay for restatement history (`/companies/{cik}/facts?history=true`).
* **Primary period column.** Each filing contributes one column: the period ending on the filing's balance-sheet date, shortest duration reported for that statement (the quarter on a Q2 income statement, the year-to-date on a Q2 cash flow). Comparative columns are kept in the lake (`is_primary_period = false`).
* **Provisional statements.** Filings the FSDS has not covered yet (it lags up to three months) get statements built from `facts`, using the company's latest FSDS-covered filing of the same kind as a template for line order and labels. They carry `source = 'facts_fallback'`, are shaded in Excel, and are replaced automatically when the FSDS quarter is published.
* **Arithmetic checks.** Balance sheet: `Assets = Liabilities + Equity`. Income statement: gross profit, operating income, pre-tax − tax. Cash flow: activities (+ FX) = net change in cash. IFRS concept names are covered. A check only runs when all its operands are present; `checks_passed` is `NULL` when nothing applied, and the failing identities are stored in `statement_checks`.

## Daily refresh

`filings-hub refresh` (scheduled by [`.github/workflows/refresh.yml`](.github/workflows/refresh.yml) at 06:00 ET):

1. fetch yesterday's daily index (catching up to 7 days if runs were missed) → new filings
2. for CIKs with a new 10-K / 10-Q / 20-F / 40-F / 8-K: re-fetch submissions and companyfacts from the per-company API
3. rebuild periods; pick up a newly published FSDS quarter; build provisional statements for the new results filings
4. load the touched rows into Postgres
5. write a `run_log` row; alert (Slack webhook / email) on failure or on a weekday with zero new filings

## API (Phase 2)

`filings-hub api` (uvicorn, `X-API-Key` header, 60 requests/minute per key):

| Endpoint | Returns |
| --- | --- |
| `GET /search?q=` | companies by name, ticker or CIK |
| `GET /companies/{cik\|ticker}` | profile, latest period, next expected results date |
| `GET /companies/{cik}/periods` | the period spine with results filing, earnings release and amendments |
| `GET /companies/{cik}/filings?form=&from=&to=` | other filings with plain-English labels |
| `GET /companies/{cik}/statements?periods=FY2025,Q1 2026` | as-reported lines, periods as columns |
| `GET /companies/{cik}/export.xlsx?periods=` | the workbook |
| `GET /companies/{cik}/facts?concept=&history=true` | XBRL fact history from the lake |
| `GET /health` | backend and last run |

## Quality

```bash
filings-hub quality                      # checks_passed rate by year / form (optionally --tickers-file sp500.txt --since 2020)
filings-hub golden AAPL,MSFT,JPM,XOM,RY  # Friday spot check: latest period, filing, 8-K, statement source, checks
```

## Development

```bash
make test        # pytest (spins up a throwaway Postgres for the loader test when initdb is available)
make lint        # ruff check + format --check
make cov         # coverage report
pre-commit install
```

## Phase 1 definition of done

| Item | Status |
| --- | --- |
| Bulk backfill runs end-to-end from empty lake to loaded Postgres | implemented (`filings-hub backfill`); wall-clock < 4 h to be measured on the first real run |
| Daily refresh 5 consecutive weekdays without intervention | workflow + run log + alerts in place; needs 5 real days |
| 20-company golden set checked by a human | `filings-hub golden` prints the sheet; human check pending |
| `checks_passed` ≥ 95 % on S&P 500 filings since 2020 | `filings-hub quality --tickers-file --since 2020` |
| Every golden-set period has correct label, results filing and 8-K | covered by tests on the fixture universe; real-data pass pending |
| `pytest` green, coverage on `periods.py` and `sync_statements.py` ≥ 80 % | 79 tests, 97 % / 96 % |
| README explains backfill, refresh and export in three commands | above |
