# Filings Hub

Any SEC-registered company → clean, period-organised filing hub → as-reported financial statements → Excel. Refreshed daily.

This repository is **Layer 1** of the plan in [`docs/layer1_execution_plan.md`](docs/layer1_execution_plan.md): the data foundation (Phase 1), the API (Phase 2), the three-screen web app (Phase 3, [`web/`](web/)) and the scale/harden pieces that live in code (Phase 4: metrics, data-quality queue, scheduler worker). No user accounts, no NLP, no non-US filers.

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
* **Which value a line takes.** Whether a line shows an instant or a duration follows the concept (`tag.iord`), not the statement it appears on: opening and closing cash are points in time presented on the cash flow statement. A concept presented twice, as "beginning balances" and "ending balances", is paired to its dates in presentation order, because the SEC's `pre` table carries no dates of its own.
* **Arithmetic checks.** Balance sheet: `Assets = Liabilities + Equity`. Income statement: gross profit, operating income, pre-tax − tax. Cash flow: activities (+ FX) = net change in cash. IFRS concept names are covered. A check only runs when all its operands are present; `checks_passed` is `NULL` when nothing applied, and the failing identities are stored in `statement_checks`.

## Daily refresh

`filings-hub refresh` (scheduled by [`.github/workflows/refresh.yml`](.github/workflows/refresh.yml) at 06:00 ET):

1. fetch yesterday's daily index (catching up to 7 days if runs were missed) → new filings
2. for CIKs with a new 10-K / 10-Q / 20-F / 40-F / 8-K: re-fetch submissions and companyfacts from the per-company API
3. rebuild periods; pick up a newly published FSDS quarter; build provisional statements for the new results filings
4. load the touched rows into Postgres
5. write a `run_log` row; alert (Slack webhook / email) on failure or on a weekday with zero new filings

## API (Phase 2)

`filings-hub api` (uvicorn, `X-API-Key` header, 60 requests/minute per key; interactive docs at `/docs`):

| Endpoint | Returns |
| --- | --- |
| `GET /search?q=` | companies by name, ticker or CIK |
| `GET /companies/{cik\|ticker}` | profile, latest period, next expected results date |
| `GET /companies/{cik}/periods` | the period spine with results filing, earnings release and amendments |
| `GET /companies/{cik}/filings?form=&from=&to=` | other filings with plain-English labels |
| `GET /companies/{cik}/statements?periods=FY2025,Q1 2026` | as-reported lines, periods as columns |
| `GET /companies/{cik}/export.xlsx?periods=` | the workbook |
| `GET /companies/{cik}/facts?concept=&history=true` | XBRL fact history from the lake |
| `GET /metrics` | dashboard feed (Phase 4) |
| `GET /quality/failed` | failed arithmetic checks queue (Phase 4) |
| `GET /health` | backend and last run |

## Web app (Phase 3)

```bash
cd web && npm install && cp .env.example .env.local   # FILINGS_API_URL, FILINGS_API_KEY (server-side only)
npm run dev                                           # http://localhost:3000
```

Three screens, no form codes on the surface: search; company page (name, ticker, next expected results date, one row per period with the results filing, the earnings release, "View statements" and "Download", plus a collapsed "Other filings" list with plain-English labels); statements view (Income Statement / Balance Sheet / Cash Flow tabs, periods as columns, scale selector, Excel download). Deploys to Vercel with `web/` as the project root.

## Scale and harden (Phase 4)

* `filings-hub worker --at 06:00 --tz America/New_York` runs the refresh on a schedule in-process (the GitHub Actions cron is the starter option).
* `GET /metrics` feeds a dashboard: filings/day, refresh runs with durations, checks pass rate by fiscal year, totals.
* `GET /quality/failed` is the data-quality queue: every statement whose arithmetic checks failed, newest first, with the filing link.
* `docker-compose up` starts Postgres, the API, the worker and the web app against a shared lake volume.

Measured against the acceptance targets (fixture lake, DuckDB backend): statements over a 3-year range **p95 22 ms** (target < 300 ms), `export.xlsx` **p95 52 ms** (target < 3 s).

Company search is a `UNION` of one branch per identifier (name, ticker, CIK) rather than a single `OR`, because an `OR` across three columns cannot use an index: benchmarked against a 900k-company table, that is **207 ms → 0.6 ms**. The name branch uses a `pg_trgm` GIN index (migration `0002`, which degrades to a sequential scan if the extension is not permitted) and is capped at 5,000 candidates so a bare industry word cannot make ranking cost more than the scan it replaced.

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

Run the whole checklist as one command against a lake built from real SEC data:

```bash
filings-hub verify                              # pass/fail per criterion; exits non-zero on any failure
filings-hub verify --export-dir ./golden        # also writes one workbook per golden-set company
filings-hub verify --tickers-file mine.txt      # use your own universe instead of the vendored S&P 500
```

| Criterion | How it is checked | Status |
| --- | --- | --- |
| Bulk backfill from empty lake to loaded Postgres in < 4 h | the `run_log` row the backfill writes | needs SEC access |
| Daily refresh 5 consecutive weekdays without intervention | `run_log` refresh rows, weekends skipped, any failed run disqualifies | needs SEC access |
| 20-company golden set checked against the filings | per company: period labels well-formed and unique, an annual period present, every period has a results filing, statements exist with an income statement and balance sheet, arithmetic checks not failing | needs SEC access |
| Every golden-set period has the correct label, results filing and earnings-release 8-K | coverage across the set, with implausible 8-K lags reported | needs SEC access |
| `checks_passed` ≥ 95 % on S&P 500 filings since 2020 | the vendored [S&P 500 list](filings_hub/data/PROVENANCE.md) joined to `periods` | needs SEC access |
| `pytest` green, coverage on `periods.py` and `sync_statements.py` ≥ 80 % | `make cov` | **met**: 133 tests, 97 % / 96 % (91 % overall) |
| README explains backfill, refresh and export in three commands | above | **met** |

The five data criteria are reported as *not evaluated* rather than passed when the lake does not hold
the universe they are about, so a partial lake cannot read as a green light. The harness itself is
tested in both directions: each criterion has pass, fail and abstain cases, and one test builds a lake
at the shape and scale of real data and asserts all five reach PASS through the same SQL.

The golden set covers the characteristics the plan names — a 52/53-week filer, several non-December
year ends, a bank with no gross profit line, two REITs, two insurers, a biotech, dual share classes,
and a 40-F filer reporting under IFRS. It is a CSV of tickers, resolved to CIKs from the loaded data,
so it carries no hard-coded identifiers that could go stale: [`filings_hub/data/golden_set.csv`](filings_hub/data/golden_set.csv).
