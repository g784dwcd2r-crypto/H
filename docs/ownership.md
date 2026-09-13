# Ownership: people, reported positions and major disclosures

Disclosure separates three US SEC ownership flows. These observations are not a complete shareholder register, a real-time trading feed or an estimate of all outstanding ownership. Historical backfill and country-specific European disclosure systems remain future work.

| View | Sources | What is shown |
| --- | --- | --- |
| Insider activity | Forms 3, 4, 5 and amendments | Person, stated role, transaction code and date, exact reported quantities, footnotes, source filings and a compatible balance series when available |
| Institutional positions | 13F-HR and amendments | Reporting manager, security class, quarter-end position and conservative comparisons with the immediately preceding reported quarter |
| Beneficial ownership | Structured Schedule 13D/G and amendments, including SC aliases | Reporting people, disclosed stake, stated filing category, purpose and optional exhibits; no automatic activist classification |

Each flow has its own cards, filters, CSV export, watchlist section and optional email subscription. Cards expand in place to observations and source documents. Source pages serve stored facts and escaped source text, with links to the SEC originals. Company identity is checked against the structured issuer or a verified security mapping; a 13F manager's CIK is never used as the security issuer's CIK.

## Interpretation rules

- Form 3 is an initial holding disclosure, not a purchase. A grant or option exercise is not classified as an open-market purchase. A filing-level 10b5-1 flag is presented as indicated, not as proof about every row.
- Insider balances belong to a security class, derivative status and direct/indirect ownership bucket. Charts require compatible observations. The percentage change denominator is the preceding balance of the same reported bucket, only when defensible. Footnotes, amendments and uncertain sources suppress unsupported comparisons.
- 13F values in current XML are dollars; older supported XML uses the applicable older scale. Reported positions are delayed, omit short positions and may be subject to confidential treatment. Missing or incompatible baselines are explicit. Absence is described as “no longer reported,” never a confirmed sale or exit.
- A structured CUSIP and subject issuer from a 13D/G disclosure can establish a mapping; operators can also register a documented exact mapping. No fuzzy company-name mapping is performed. Conflicts are rejected. Unmatched 13F positions remain in storage and coverage counts until mapped.
- 13G can reflect institutional, passive or exempt reporting categories. 13D alone does not prove activism. Board letters are linked only when an actual exhibit is present. Reporting-person percentages are not summed into a group stake.
- Legacy non-XML ownership filings and 13F notices are recorded as unsupported, never converted into zero positions. Parser failures remain visible and retryable. A missing company view does not establish that there are no owners or transactions.

## Operator workflow

The worker uses the existing `SEC_USER_AGENT`, SEC rate limiter, `LAKE_ROOT` and `DATABASE_URL`. A remote lake requires Postgres. Configure one scheduler for ownership discovery, separately from financial statement refresh. Running a single discovery worker avoids cursor races; storage ingestion is idempotent and SQL publication is atomic.

```sh
# Start with yesterday, then resume the durable discovery cursor and filing queue.
# Schedule this command regularly after the SEC daily master index is available.
filings-hub ownership sync --max-days 7 --max-filings 100

# Inspect backlog, failures, unsupported sources and unmatched security positions.
filings-hub ownership coverage
filings-hub ownership coverage --cik 320193

# An explicit start date creates a separate resumable catch-up cursor.
filings-hub ownership sync --since 2026-09-10 --max-days 7 --max-filings 100

# Replay one completed index without moving the forward cursor.
filings-hub ownership sync --date 2026-09-10

# Retry a known accession or load one deliberately chosen comparison baseline.
filings-hub ownership filing 320193 0001140361-26-036226 4 2026-09-10

# Register a reviewed mapping with an actual SEC source URL that evidences the relationship.
filings-hub ownership map-security CUSIP ISSUER_CIK 'Security class' SEC_SOURCE_URL

# SMTP must be configured; these commands send real emails only to separately opted-in accounts.
filings-hub ownership sync --send-alerts
filings-hub ownership notify
```

Discovery queues every eligible row before advancing a date, then processes a bounded filing batch. Cached documents or a full batch are not date-completion signals. Failed filings are retained for retry and do not discard other filings. A weekday with no available index stays pending; after verifying a holiday or missing publication, an operator can explicitly record `ownership skip-date YYYY-MM-DD 'Specific verified reason'`. The record remains auditable. Do not skip a transient SEC outage.

Current implementation uses daily master indexes, not intraday streaming. A first run starts yesterday and does not launch a historical backfill. Run enough bounded batches to drain the queue and monitor coverage before describing the data as current. There is no production activation in this PR.

## Persistence and delivery

Migration `0016_ownership.sql` creates separate filing, insider, institution, event, security-mapping and ingest-state tables. Local development uses the existing SQLite research index; remote serving uses Postgres. Immutable source bytes are addressed by hash under `ownership/raw`; normalized objects are separated by flow. Revised source versions retain provenance. Cofiled company/person paths resolve to one logical accession while preserving alternate source references. Stored source hashes are verified; incomplete writes are repaired before publication. Read endpoints never fetch SEC documents or trigger ingestion.

Ownership email preferences are explicit `ownership_flows` values: `insiders`, `institutions`, `events`. Existing accounts remain results-only until they opt in. Delivery scans individual filing events from the subscription start date, rather than only the latest person card. Receipts are separate by account and flow. Bounded scans rotate and revisit earlier dates to catch delayed filings or newly mapped positions. SMTP delivery and receipt storage cannot be atomic: a crash after successful delivery but before receipt publication may duplicate a message.

No synthetic data enters production. Browser previews use invented people and holdings, visibly labelled synthetic, in an isolated marked lake. Parser tests separately retain small real SEC XML examples with source URLs and SHA-256 hashes. No AI inference or paid provider calls are required for ownership parsing.

## HTTP contracts

- `GET /companies/{cik}/ownership/{insiders|institutions|events}`: one flow, bounded pagination, date filters and insider purchase/sale filters.
- `GET /companies/{cik}/ownership/{flow}/export.csv`: one flow, exact quantities, source links and spreadsheet-formula escaping.
- `GET /companies/{cik}/ownership/documents/{document_id}`: issuer-scoped stored source, structured rows and bounded raw text.
- `GET /ownership/recent?ciks=...&flow=...&since=...`: separate watchlist ownership groups.
- `GET /ownership/coverage`: observed ingestion and identifier-matching coverage.
- `POST /subscriptions`: existing verified-account subscription with optional `ownership_flows`; delivery cannot be redirected to an arbitrary email address.

## Source references

- SEC [Form 3](https://www.sec.gov/files/form3.pdf) and [Form 4](https://www.sec.gov/files/form4.pdf).
- SEC [Form 13F frequently asked questions](https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/frequently-asked-questions-about-form-13f).
- SEC [modernization of beneficial ownership reporting](https://www.sec.gov/files/rules/final/2023/33-11253.pdf).
- Versioned schema references and captured filings: `tests/fixtures/ownership/README.md` and `real-sources.json`.
