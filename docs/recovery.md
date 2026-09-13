# Refresh recovery and serving freshness

Daily index files under `raw/edgar/daily-index/` are download caches, not proof that ingestion
finished. The refresh writes `refresh_state/dates/YYYY-MM-DD.json` as pending before fetching and
keeps the affected CIKs in that record. It marks the date complete only after company refresh,
documents, periods, statements, metrics, the configured database load, and digest delivery succeed.
A per-company failure now gives the run status `failed` and a nonzero CLI exit status.

Each automatic run processes at most seven dates. A durable catch-up start preserves the remaining
backlog across runs, including an outage longer than seven days; age never discards known pending
work. Retries rotate by their last attempt, reserving room for unprocessed dates so holiday 404s do
not starve new filings. A retry may update zero new filing rows and still finish successfully.
An absent weekday source index stays pending even when newer dates succeed, so a delayed publication
is retried automatically. Empty weekdays continue to alert and should be checked for a delayed
publication or a holiday. The code does not infer SEC holidays; holiday weekdays may remain pending
and be rechecked. Weekends with no index can complete.

## Upgrading an existing lake

Keep the existing raw and transformed data. On the first updated refresh, cached index dates that
have no completion record are treated as unproven work and replayed in bounded batches. The replay
is limited to companies touched by those indices; unrelated company
history and FSDS statement outputs are retained. Legacy dates with unknown email-delivery history
recover data without sending historic digests. Fresh dates and their subsequent retries retain
normal notification behavior.

Run only one ingestion writer per lake. Let a running backfill/refresh finish before deploying this
code or starting a repair against the same lake. Check its run log and coverage before resuming the
normal schedule. These recovery records do not provide a distributed lock or atomic publication of
an entire lake, and the existing partition replacement routines retain their publication limitations.

To replay a specific old date, including one outside the automatic catch-up window:

```sh
filings-hub refresh --date 2026-09-10
```

For a historical gap containing dates with no cached index, set an explicit repair start:

```sh
filings-hub refresh --since 2026-08-01
```

The start persists in `refresh_state/catchup.json`; subsequent ordinary refresh runs continue the
remaining backlog in batches. `--date` and `--since` are mutually exclusive. Without a saved start
or an explicit date, initialization starts after the last completed date, or yesterday for a lake
with no completion history. A pre-upgrade raw cache cannot prove how far back missing, uncached
dates need repair, so choose `--since` after inspecting the old run logs. A new earlier start expands
an existing repair range; it does not discard already pending work.

This uses the configured lake, SEC identity, database and notifications. To rebuild only the lake,
use `--no-load-db`; such a successful run does not establish database parity. `--no-alert` disables
operator failure alerts, not subscriber digests. A replay using a new-code completion record will
skip already receipted deliveries. A legacy raw date without a record suppresses historic digests.

Check the newest `run_log` record for `status`, `failures`, `error`, `index_dates` and `db_loaded`.
Do not delete pending state to make a failure disappear; resolve its underlying cause and rerun.
Loss of the raw file for a pending date falls back to fetching that date again.

When Postgres loading is enabled, both refresh and backfill publish their finalized run record after
writing it to the lake. Health and coverage can therefore show the just-finished run without waiting
for a subsequent load. Publication is idempotent by `run_id`, and upstream failures are published too.
If that final database write fails, the lake retains a failed record with the publication error and
the command reports failure; it does not silently claim that the serving log is current.

## Account write concurrency

Lake-backed account stores share a reentrant lock per lake root within the API process. Preference
read/modify/write operations, first account creation and one-time token consumption hold that lock
for the complete operation. Separate API processes do not share the lock: use Postgres for multiple
workers/replicas writing account data.

Watchlist changes use an atomic company toggle/remove operation, rather than replacing a list that
was previously read in the browser. The lake implementation uses the same lock; Postgres mutates the
current JSONB row in a single `INSERT ... ON CONFLICT` statement, including the 200-company limit.
Concurrent first sign-ins for one email return the same account and preserve its existing profile.

## Interrupted statements and FSDS quarters

`refresh_state/fsds/YYYYqN.json` records a pending quarter before its download. Retries force reload
and rebuild for that pending quarter, because a cached ZIP or one existing partition does not prove
completion. Its record is completed after the downstream metrics/database/digest work succeeds.
New quarterly publications remain eligible for the normal refresh.

For a touched daily-index accession, refresh rebuilds only its provisional fallback statement and
check outputs. This repairs a failure between statement publication and check publication without
removing FSDS-derived statements or unrelated fallback history.

Pre-upgrade FSDS ZIPs without pending records are not automatically rebuilt. Use the existing
backfill/recovery workflow to reconcile older quarters when coverage verification identifies an
incomplete load. The refresh repair is not a substitute for the real-data acceptance benchmark.

## Digest receipts and limits

Successful email delivery writes a receipt under
`digest_deliveries/<subscriber-id>/<batch-hash>.json`, with its accession list and timestamp.
Replay filters delivered accessions per subscriber even when the catch-up batch contains different
dates. False returns and exceptions from the sender retain pending refresh work; other recipients'
successful deliveries are not resent on retry.

The delivery semantics are **at least once**, not exactly once. SMTP/provider acceptance and the
receipt write are separate operations. A process crash or storage failure after sending but before
the receipt is durable can duplicate that email. Concurrent writers can also race. Exactly-once
delivery would require provider-supported idempotency and a transactional outbox/claim workflow.

## API startup during a backfill

DuckDB-backed queries recheck missing datasets at most every 30 seconds, including local lakes, and
replace typed empty stand-ins as data arrives. Remote whole-universe table copies retain their
600-second resync interval; newly appearing tables are discovered by the shorter missing-table
probe. Object ETags identify changed cached content when available. No API restart is required.
Remote directory listings are also invalidated at the regular resync interval, even when all views
already exist or local table caching is disabled, so partitions from a separate writer become visible.

Existing partition-backed views continue reading their underlying files. This is eventual freshness,
not a guarantee that every multi-table query sees one consistent ingestion snapshot. Postgres still
requires its serving loader to finish; view discovery only applies to the lake-backed DuckDB mode.

## Regression evidence

The targeted suite injects failures at filing upsert, company facts, documents, period rebuild,
fallback statements, metrics, database loading and digests. It also tests missing raw downloads,
legacy cached-date recovery, interrupted FSDS download/load/build, statement-without-checks repair,
digest replay and partial delivery failures, and local plus moto S3 discovery after empty startup.

```sh
python -m pytest tests/test_refresh.py tests/test_digest.py tests/test_reader.py \
  tests/test_database_recovery.py tests/test_s3.py
```
