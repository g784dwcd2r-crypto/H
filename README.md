# Disclosure

Find SEC-registered companies, review period-organised filings and as-reported statements, and export to Excel. Statement availability varies by company and period; `/coverage` reports the serving data.

The product is called **Disclosure**; the Python package, the `filings-hub` command and the Render service names keep their original names so nothing deployed has to move.

Disclosure includes the SEC data pipeline, API, research workspace, accounts, scoped preferences and Excel export. The release foundation adds an interactive landing page, per-value evidence, conservative derived financials, measured public coverage, private operations reporting and durable refresh recovery. See [financial methodology](docs/financial-methodology.md), [recovery and upgrades](docs/recovery.md), and [release readiness](docs/release-readiness.md). Global regulator coverage, team workspaces and enterprise controls remain future releases; foreign registrants are included when they file with the SEC.

## Three commands

```bash
cp .env.example .env            # set SEC_USER_AGENT="Your Name you@example.com" (required by the SEC), LAKE_ROOT, DATABASE_URL
uv sync --frozen --extra dev

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

`LAKE_ROOT` can be a local directory or `s3://bucket/prefix` (`pip install -e ".[s3]"`). DuckDB reads and writes the bucket through the same fsspec filesystem the rest of the code uses, configured by the `AWS_*` variables in `.env`; set `AWS_ENDPOINT_URL` for MinIO, R2 or another S3-compatible store. No DuckDB extension is downloaded. The full backfill and the daily refresh are tested end to end against a mock bucket (`tests/test_s3.py`).

Every FSDS table load is reconciled and recorded in `fsds/load_log/`: raw rows in the file, rows loaded, rows DuckDB could not read (with the first examples), values present but unparseable, and the encoding used. Quarters before about 2013 carry Windows-1252 bytes; when UTF-8 rejects a row the loader transcodes the file line by line (valid UTF-8 lines untouched, the rest decoded as Windows-1252) and reads it again, so no row is lost to encoding. A table with more than 0.1 % of its rows rejected is flagged in the backfill's `run_log` failures.

## The rules that matter

* **Period labels.** Fiscal year = calendar year in which the fiscal year *ends* (Apple's quarter ending December 2025 is `Q1 2026`). The fiscal quarter is measured against the company's *actual* next 10-K report date when one exists, else the nominal `fiscalYearEnd` from EDGAR, so 52/53-week years and fiscal-year-end changes label correctly. Transition periods get a `T` suffix.
* **Earnings release.** The earliest 8-K with item 2.02 filed within 60 days (quarters) / 90 days (annual) after the period end.
* **Amendments.** `10-K/A`, `10-Q/A` hang off the original period (`amendment_accessions`).
* **Facts dedupe.** Same (concept, unit, period) reported in several filings → the latest filed is `is_current`; all values stay for restatement history (`/companies/{cik}/facts?history=true`).
* **Primary period column.** Each filing contributes one column: the period ending on the filing's balance-sheet date, shortest duration reported for that statement (the quarter on a Q2 income statement, the year-to-date on a Q2 cash flow). Comparative columns are kept in the lake (`is_primary_period = false`).
* **Provisional statements.** Filings the FSDS has not covered yet (it lags up to three months) get statements built from `facts`, using the company's latest FSDS-covered filing of the same kind as a template for line order and labels. They carry `source = 'facts_fallback'`, are shaded in Excel, and are replaced automatically when the FSDS quarter is published.
* **Which value a line takes.** Whether a line shows an instant or a duration follows the concept (`tag.iord`), not the statement it appears on: opening and closing cash are points in time presented on the cash flow statement. A concept presented twice, as "beginning balances" and "ending balances", is paired to its dates in presentation order, because the SEC's `pre` table carries no dates of its own.
* **SEC throttling.** The SEC edge answers `403` for about ten minutes once it decides the traffic is an automated burst; a bulk download right before the next request is enough to trigger it. The client treats `403`/`429` as "wait, then retry" on their own schedule (30 s doubling to 10 min, 8 rounds, `EDGAR_THROTTLE_RETRIES` / `EDGAR_THROTTLE_MAX_WAIT_SECONDS`), separate from the short backoff for server errors, so a backfill rides out a block instead of failing. Re-running a failed backfill is safe: raw files already in the lake are never downloaded again. A `403` whose body is S3's `AccessDenied` is different: the object is simply not there (the bulk files vanish while the SEC's nightly rebuild runs, and `companyfacts.zip` has had multi-day outages). That is not retried; the backfill then fetches every reporting company from the per-company `companyfacts` API instead (`facts[api]` in the run log's steps) and the raw responses are kept under `raw/edgar/api/`.
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
| `GET /companies/{cik}/documents · /filings/{acc}/document · /search?q= · /peers, GET /filings/recent, POST /subscriptions · /requests
GET /companies/{cik}/facts?concept=&history=true` | XBRL fact history from the lake |
| `GET /coverage` | public measured coverage and methodology limits |
| `GET /metrics` | administrator dashboard; requires a verified admin session |
| `GET /quality/failed` | administrator arithmetic-check queue |
| `GET /health` | backend and last run |

## Stage 1 hub features

* **Search that reads minds.** Suggestions as you type; an exact ticker or CIK (or a single match) opens the company page directly. Recently opened and followed companies sit under the search box.
* **The first three questions, above the fold.** Latest period, next expected results, and the latest annual report, quarterly report, earnings release and proxy, each one click away.
* **Documents, not just filings.** Each filing's exhibits with plain names (Earnings release, Investor presentation, Financial supplement, Subsidiaries…), from the filing's EDGAR index page, fetched once and kept (`documents/`). `filings-hub documents --tickers AAPL,MSFT` prefetches; the refresh fetches them for new results filings and 8-Ks.
* **Reader.** Filings open inside the hub: sanitised HTML in a sandboxed frame with a table of contents (Parts, Items, statement titles) and a link back to sec.gov.
* **Search inside a company's filings.** "Where did they last mention buybacks": phrase search with context across the results filings and earnings releases, newest first (`/companies/{cik}/search?q=`).
* **Numbers in the period table.** Revenue, net income and diluted EPS per period, read off the as-reported statements; `company_metrics/` holds each company's latest annual numbers (`filings-hub metrics` rebuilds it).
* **Watchlist and alerts.** Follow companies in the browser or your account and see recent filings. Signed-in accounts can enable, update or pause alerts to their verified email via `GET/POST/DELETE /subscriptions`. The alert company list is a saved snapshot; update it after changing followed companies. Delivery uses `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `SITE_URL` and durable receipts. Subscriptions and coverage requests require a writable lake.
* **Peers.** Same industry code, biggest first.
* **Keys.** `/` focuses search, `w` opens the watchlist, `1`–`3` switch statements, `m`/`t`/`u` change the scale.
* **International as a promise.** UK, Europe and rest-of-world tabs take coverage requests.

## Accounts and preferences (the spine of "the user decides")

Sign in with an email link (`SMTP_*`) or Google (`GOOGLE_CLIENT_ID`/`SECRET`, redirect URI `{SITE_URL}/auth/google/callback`). Sessions are signed tokens (`SESSION_SECRET`) in an httpOnly cookie. The user store follows the serving data: Postgres when `DATABASE_URL` is set (migration `0006`), JSON documents in the lake otherwise, so the API needs a writable lake on the free layout.

Preferences are one record per `(scope, scope_key, key)` with a `source` (explicit, inferred, preset), resolved **statement → company → sector → global → default**; every resolution names the scope that answered, and the UI shows it ("set for this company", "everywhere"). Signed-out visitors keep the same choices in their browser. `/settings` lists everything with reset, export and import as JSON. API: `GET /me`, `GET/PUT/DELETE /me/prefs`, `GET /me/prefs/resolve?cik=&statement=`, `POST /me/prefs/export|import|reset`.

Every control on the site is the same component (`PrefControl`): the value, a selector for where the choice applies (statement, company, industry, everywhere, whichever the context has), and a tag saying where it is currently set from.

* **Statements toolbar.** Scale (all four scopes; per-share never scaled), period view, column order, negative style, latest-filed comparatives, number of periods. Period views: *as filed* (each filing's own column), *quarterly* (Q4 = fiscal year less the nine months, cash flow quarters are differences of the year-to-date columns; opening balances follow), *annual*, *LTM* (year to date + prior fiscal year − prior year to date). Derived columns are marked and shaded; a Q4 that cannot be derived stays empty rather than wrong; unsupported derived per-share amounts, weighted averages and unvalidated concepts remain unavailable with explicit reasons. *Restated* takes a column's numbers from the newest later filing that presents the period (as-filed and annual views; the column names the filing). Grid API: `GET /companies/{cik}/statements?period_mode=&restated=&column_order=`.
* **Export dialog.** Layout (sheet per statement or one sheet), orientation (periods across or down), subtotals as values or as formulas (a formula only where the reported children add up to the reported total), what to include (Source sheet, checks column, concept names, filing rows), number scale, negative style, statements, and a file name pattern (`{ticker} {cik} {name} {mode} {date} {periods}`). "Remember these settings" stores them as `export_config` for the company, the industry or everywhere; named profiles live in the `export` scope. `GET /companies/{cik}/export.xlsx?layout=&orientation=&subtotals=&include=&scale=&negative_style=&filename=&statements=` plus the grid parameters.
* **Headline cards.** Four swappable numbers on the company page from a wider metric set (gross profit, operating income, net interest income, provisions, deposits, capex, buybacks…), starting from an industry preset (banks: net interest income, provision, net income, assets), remembered as `headline_cards` at any scope. Follow is kept on the account when signed in (`watchlist`, global). Browser and account lists stay separate; account reads do not reuse a cache across sign-ins.
* **Proposals.** Three strikes: the same explicit choice on three companies (period view, scale, column order, restated, periods shown, negative style, export settings) while the global value says otherwise is proposed once as the default everywhere. Dismissed twice it never returns; accepted it becomes a global preference with `source=inferred`, which `/settings` shows as "suggested, you accepted". `GET/POST /me/proposals`.
* **Private analytics.** `ADMIN_EMAILS` is a comma-separated allowlist of verified accounts. `/metrics`, `/metrics/prefs` and `/quality/failed` require an administrator session as well as the service API key; an empty allowlist denies access. Telemetry stores only known option enums/counts and event names. Watchlists, arbitrary preference keys, export filenames/profile names and UI props are excluded. Legacy records are filtered again before aggregation; existing raw legacy records require an operator retention/purge policy.

## Web app (Phase 3)

```bash
cd web && npm ci && cp .env.example .env.local   # FILINGS_API_URL, FILINGS_API_KEY (server-side only)
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

## Deploy

Two layouts, same code. Both keep the lake in S3-compatible object storage (Cloudflare R2 is the cheap default: 10 GB free, no egress fees).

**Free** ([`render.yaml`](render.yaml)): GitHub Actions runs the daily refresh, two Render free web services serve the API and the site straight from the lake with DuckDB. Nothing is billed. Free services sleep after 15 idle minutes (first request afterwards ~30 s) and queries read Parquet from R2 rather than Postgres, so they are slower than the benchmark numbers above.

**Full** ([`deploy/render.full.yaml`](deploy/render.full.yaml)): Render Postgres for serving, an always-on worker for the refresh, paid plans. `cp deploy/render.full.yaml render.yaml` to upgrade, then load Postgres from the machine holding the lake (`DATABASE_URL="<external connection string>" filings-hub load`).

Order of operations for the free layout:

1. **Object storage.** In Cloudflare: R2 → create a bucket → *Manage R2 API Tokens* → token with *Object Read & Write* on that bucket. It shows the access key pair and the endpoint `https://<account-id>.r2.cloudflarestorage.com`. (Plain AWS S3 works the same with an IAM key and the endpoint left empty.)
2. **Push the lake.** After a local backfill, copy it up once with the AWS CLI (`brew install awscli`, `aws configure` with that key pair, region `auto`): `aws s3 sync ./data s3://BUCKET/filings-hub --exclude "raw/*" --endpoint-url https://<account-id>.r2.cloudflarestorage.com`. `raw/` can stay local; nothing downstream needs it once the lake is built.
3. **GitHub secrets** (repository → Settings → Secrets and variables → Actions): `SEC_USER_AGENT`, `LAKE_ROOT` (`s3://BUCKET/filings-hub`), `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` (`auto` for R2), `AWS_ENDPOINT_URL`, optionally `SLACK_WEBHOOK_URL`. The `daily-refresh` workflow then runs every weekday at 06:00 New York; *Run workflow* on the Actions tab runs it on demand.
4. **Blueprint.** Render dashboard → *New* → *Blueprint* → this repository. It asks for the same lake values; `API_KEY` and the site's link to the API are generated.
5. **Check.** `https://filings-hub-api.onrender.com/health` reports `backend: duckdb` and the last run. Open the web service URL, search a ticker, download a workbook.

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
