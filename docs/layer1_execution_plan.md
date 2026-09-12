# Filings Hub — Layer 1 execution plan (US only)

Goal of layer 1: any SEC-registered company → clean period-organised filing hub → as-reported statements → Excel. Refreshed daily. Nothing else.

---

## 0. Four improvements to the original strategy

1. **Use EDGAR's bulk files, not per-company API calls.**
   The SEC publishes nightly zips of *everything*:
   - `https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip` (all filing indexes, ~1.5 GB)
   - `https://www.sec.gov/Archives/edgar/daily-index/bulkdata/companyfacts.zip` (all XBRL facts, ~1 GB)
   One download replaces ~10,000 API calls. The per-company API is then only for same-day freshness.

2. **Get the as-reported statement structure from the SEC's Financial Statement Data Sets.**
   `https://www.sec.gov/dera/data/financial-statement-data-sets` — quarterly zips with four tables:
   `sub` (filings), `num` (values), `tag` (concept labels), **`pre` (presentation: which statement each line is on, and in what order)**.
   This is the "no template imposed" skeleton, already built by the SEC. No need to parse presentation linkbases yourself in phase 1.

3. **Two-tier storage: Parquet + DuckDB for building, Postgres only for serving.**
   Facts are ~100M rows. Loading that into Postgres on day one is slow and expensive. Keep the lake as Parquet on S3, transform with DuckDB, and load only the serving tables (companies, filings, periods, statements) into Postgres. Facts stay in Parquet and are queried by DuckDB behind the API.

4. **Define "done" per phase with acceptance tests, not features.**
   Each phase below ends with a checklist that must be green before the next starts.

---

## 1. Phase 1 — Data foundation (weeks 1–3). Must be 100% before anything else.

### 1.1 Repo and environment (day 1)
- [ ] Repo `filings-hub`, Python 3.12, `uv` or `poetry`, `ruff`, `pytest`, pre-commit.
- [ ] `.env` with `SEC_USER_AGENT="Name email"`, `S3_BUCKET`, `DATABASE_URL`.
- [ ] Structure:
  ```
  filings-hub/
    ingest/
      edgar_client.py      rate-limited HTTP (10 req/s), retries, User-Agent
      bulk.py              download + unpack submissions.zip, companyfacts.zip, FSDS zips
      sync_universe.py     company_tickers.json → companies
      sync_filings.py      submissions → filings (+ daily-index for increments)
      sync_facts.py        companyfacts → facts parquet
      sync_statements.py   FSDS pre/num/tag → statements
      periods.py           period_label logic (Q1 2026 / FY 2025), 8-K 2.02 matching
    lake/                  parquet layout + DuckDB views
    db/                    schema.sql, migrations/, load.py
    export/                excel.py
    api/                   (phase 2)
    web/                   (phase 3)
    tests/
    notebooks/
  ```

### 1.2 Raw layer — never re-hit the SEC for the same bytes (days 2–3)
- [ ] `bulk.py` downloads the three bulk sources to `s3://bucket/raw/edgar/{source}/{yyyy-mm-dd}/` and unpacks.
- [ ] Every per-company API response also lands in `raw/` with a date. Rebuilds never need the SEC.
- [ ] Idempotent: re-running a day is a no-op.

### 1.3 Universe (day 3)
- [ ] `companies` table: `cik`, `ticker` (may be several → keep a `tickers` child table), `name`, `sic`, `state_of_incorporation`, `fiscal_year_end`, `exchange`, `is_active`.
- [ ] Source: `company_tickers_exchange.json` + `submissions` header fields.
- [ ] Test: Apple, RBC (foreign 40-F filer), a company with two tickers, a delisted company.

### 1.4 Filings (days 4–6)
- [ ] `filings` parquet/table: `accession`, `cik`, `form`, `filed_date`, `report_date`, `acceptance_datetime`, `primary_doc`, `primary_doc_url`, `items`, `size`, `is_xbrl`, `is_inline_xbrl`.
- [ ] Load from `submissions.zip` (bulk) once; then increments from `https://www.sec.gov/Archives/edgar/daily-index/` each day.
- [ ] `periods.py`:
  - period_label from `form` + `report_date`: 10-K → `FY{year}`, 10-Q → `Q{n} {year}` using the company's fiscal year end (not calendar quarters — Apple's Q1 ends in December).
  - attach the earnings-release 8-K (`items` contains `2.02`) filed within 60 days after `report_date`.
  - handle amendments (10-K/A, 10-Q/A) as children of the original period.
- [ ] `periods` table: `cik`, `period_label`, `period_end`, `results_accession`, `earnings_release_accession`, `amendment_accessions`.
- [ ] Tests: Apple FY labels correct for its September year-end; a company with a 52/53-week year; a period with two 8-Ks (pick the earliest 2.02).

### 1.5 Facts (days 7–9)
- [ ] `facts` parquet partitioned by `cik`: `taxonomy`, `concept`, `unit`, `period_start`, `period_end`, `value`, `accession`, `fy`, `fp`, `form`, `filed`, `frame`.
- [ ] Load from `companyfacts.zip`. Increment by re-fetching `companyfacts` for any CIK that had a new 10-K/10-Q in the daily index.
- [ ] Dedupe rule: same (cik, concept, unit, period_start, period_end) reported in several filings → keep the **latest filed** as "current value", keep all in a history view (restatements matter to analysts).
- [ ] Derived `duration_days`; flag quarter (80–100 days), half-year, nine-month, annual, instant.
- [ ] Tests: Apple revenue for a known quarter matches the 10-Q; a restated number shows both values in history.

### 1.6 Statements — the as-reported skeleton (days 10–13)
- [ ] Download FSDS quarterly zips (2009 → now). Load `sub`, `num`, `pre`, `tag` to Parquet.
- [ ] `statements` table, one row per line item per filing:
  `accession`, `cik`, `statement` (IS / BS / CF / EQ / CI / notes), `line_order`, `concept`, `label` (as the company wrote it), `value`, `unit`, `period_start`, `period_end`, `is_subtotal` (from `pre.negating` / tag hierarchy), `parent_concept`.
- [ ] Join `pre` (structure) × `num` (values) × `tag` (standard labels) per `adsh`.
- [ ] For filings not yet in FSDS (the current quarter — FSDS lags by up to 3 months): fall back to `facts` grouped by statement using the concept's balance/period type, ordered by taxonomy default order. Mark `source = "facts_fallback"` so the UI can show it as provisional.
- [ ] Arithmetic checks per statement: balance sheet balances; IS subtotals sum. Store `checks_passed` boolean.
- [ ] Tests: Apple FY2025 income statement has the same line order as the 10-K; a bank (JPM) has no "gross profit" line; checks pass on 95%+ of large-cap filings.

### 1.7 Excel export (day 14)
- [ ] `export/excel.py`: input (cik, list of period_labels) → workbook: one sheet per statement, columns = periods (newest right), rows = as-reported lines in `line_order`, company label as row header, concept in a hidden column, units and scale in the header, a `Source` sheet listing accession + filing URL per column.
- [ ] Numbers as numbers (not text), negatives as negatives, no formulas in phase 1.
- [ ] Tests: opens cleanly in Excel and Google Sheets; column totals match statements table.

### 1.8 Daily refresh (day 15)
- [ ] One scheduler entry (GitHub Actions cron to start, move to Railway/Fly later): 06:00 ET.
  1. fetch yesterday's daily index → new filings
  2. for CIKs with new 10-K/10-Q/8-K: refresh filings, periods, facts
  3. rebuild statements for those accessions (FSDS fallback path)
  4. load serving tables to Postgres
  5. write a `run_log` row: counts, failures, duration
- [ ] Alert (email/Slack) on failure or zero new filings on a weekday.

### 1.9 Phase 1 definition of done
All of these green, or phase 1 is not done:
- [ ] Bulk backfill runs end-to-end from empty S3 to loaded Postgres in < 4 hours.
- [ ] Daily refresh has run 5 consecutive weekdays without manual intervention.
- [ ] 20-company golden set (Apple, Microsoft, JPM, Exxon, a REIT, an insurer, a biotech with no revenue, RBC as a 40-F filer, a small cap, a company with amendments…) has statements + Excel that a human checked against the filing.
- [ ] `checks_passed` ≥ 95% on S&P 500 filings since 2020.
- [ ] Every period for the golden set has the correct label, results filing and earnings-release 8-K.
- [ ] `pytest` green, coverage on `periods.py` and `sync_statements.py` ≥ 80%.
- [ ] README explains how to run backfill, refresh and export in three commands.

---

## 2. Phase 2 — API (week 4)
- FastAPI over Postgres (serving tables) + DuckDB (facts parquet).
- Endpoints:
  - `GET /search?q=` → companies
  - `GET /companies/{cik}` → profile + latest period
  - `GET /companies/{cik}/periods` → the period spine with attached filings
  - `GET /companies/{cik}/filings?form=&from=&to=` → secondary "other filings" list
  - `GET /companies/{cik}/statements?periods=` → as-reported lines
  - `GET /companies/{cik}/export.xlsx?periods=` → file
- Auth: API key header (single tenant for now). Rate limit 60/min.
- Done when: p95 < 300 ms for statements on a 3-year range; export < 3 s.

## 3. Phase 3 — Web app (weeks 5–6)
- Next.js on Vercel. Three screens only:
  1. Search.
  2. Company page: header (name, ticker, next expected results date), period rows (results filing, earnings release, "view statements", "download"), collapsed "Other filings" section with plain-English labels.
  3. Statements view: IS / BS / CF tabs, periods as columns, download button.
- No form codes on the surface. No ownership, no proxies, no transcripts.
- Done when: five analysts can find a company, open the latest quarter and download Excel without instructions.

## 4. Phase 4 — Scale and harden (weeks 7–8)
- Whole EDGAR universe (backfill already covers it; this is about serving load and monitoring).
- Metrics dashboard: filings/day, facts/day, checks pass rate, refresh duration.
- Data-quality queue: statements with `checks_passed = false` listed for review.
- Move scheduler off GitHub Actions to a proper worker.

---

## 5. What is explicitly NOT in layer 1
- User accounts, saved preferences, custom groupings (layer 2)
- Auto-updating the user's own model (layer 2)
- Natural-language questions over numbers (layer 3)
- Presentations, transcripts, ownership data
- Canada, UK, Europe (same architecture, different ingest modules; start after phase 3)

---

## 6. Weekly rhythm
- Monday: pick the checklist items for the week.
- Daily: refresh job log reviewed in 2 minutes.
- Friday: golden-set spot check (one company, one period, eyeball vs the filing).
