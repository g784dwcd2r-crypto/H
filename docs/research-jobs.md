# Durable research indexing operations

This release adds an explicitly operated job queue over the existing public SEC index. It does not start a scheduler, change a live lake, or establish production SEC completeness. Use PostgreSQL for production; a local SQLite index is the durable development fallback. Apply migrations 0013–0014 with the existing schema-only `filings-hub migrate` command.

## Bounded operating sequence

Set `LAKE_ROOT`, `DATABASE_URL` and a valid `SEC_USER_AGENT` in the operator's environment, pointing to the intended isolated or approved storage. The commands below are examples, not a production rollout:

```sh
uv run python -m filings_hub.research_jobs enqueue --kind discovery --cik 320193 --idempotency-key apple-discovery-20260913 --fetch --max-batches 20 --batch-size 10
uv run python -m filings_hub.research_jobs work
uv run python -m filings_hub.research_jobs status
uv run python -m filings_hub.research_jobs enqueue --kind index --cik 320193 --idempotency-key apple-index-20260913 --fetch --max-batches 20 --batch-size 10
uv run python -m filings_hub.research_jobs work
uv run python -m filings_hub.research_jobs prepare --batch-size 10
```

Each `work` invocation claims at most one job and performs one bounded batch. Invoke it again explicitly to advance the queue; enqueue does not execute work. The queue caps each job at 100 batches of 25 items. Without `--fetch`, missing raw sources stay pending. The SEC client uses two requests per second, one ordinary retry and no throttle retry. No search or question request fetches remote documents.

Discovery walks filings already known to the serving database and reads their full related-document inventories. Each newly enqueued discovery job has a separate durable cursor and reconciles that serving cohort from the beginning. Repeated registration and content hashes make replay idempotent. This is **not** an intraday SEC event feed: the upstream filing ingestion still has to discover new accessions. Cached filing indexes are reused; detecting a changed remote index/body that is already cached still requires explicit source-cache reconciliation. Do not interpret completion as proof of every document on SEC EDGAR.

## Recovery and write authority

Jobs progress through `queued`, `running`, `retry_wait`, `paused`, `quarantined`, `completed`, or `cancelled`. A global database fence permits one corpus writer. Claims carry an expiring token; PostgreSQL row locks or SQLite write transactions serialize claims. Every index and raw-cache mutation rechecks that token while holding its fence lock. Cancellation cannot undo already committed writes, but an old worker returning from a network call cannot commit new bytes after cancellation.

A crashed worker's expired lease becomes eligible for retry with bounded backoff. Three unsuccessful attempts quarantine the job. Reaching the batch budget pauses it. Explicit retry retains discovery progress and registered unsupported/failed inventory while renewing the attempt/batch budget:

```sh
uv run python -m filings_hub.research_jobs retry --job JOB_ID --revision CURRENT_REVISION
uv run python -m filings_hub.research_jobs cancel --job JOB_ID --revision CURRENT_REVISION
```

Revision mismatch rejects a stale operator action. `ResearchJobs.get/list` are internal operator interfaces: they contain worker authority and idempotency fields. Browser/admin adapters must allowlist public fields. The separate admin adapter follows this rule and writes an intent audit before mutating the job.

Text preparation creates immutable projections and code-point spans from retained source bytes. Hash mismatch, unavailable raw bytes and extraction errors are recorded per version/extractor, skipped on normal subsequent batches, and remain visible in health counts. One bad capture cannot indefinitely starve later versions. Restore the correct original bytes, then explicitly retry a bounded batch:

```sh
uv run python -m filings_hub.research_jobs prepare --batch-size 10 --retry-preparation-failures
```

The preparation and optional embedding commands are separately bounded, idempotent helpers; they are **not** distributed leased jobs in this release. Do not run multiple preparation/embedding operators against the same corpus. Embedding requests can incur charges and must be explicitly approved/configured before `embed --batch-size 10` is used. No bulk embedding job was run against the funded xAI account.

Back up the index database, account/project database and immutable `research/versions/` objects as a coordinated set. Local/PostgreSQL tests exercise lease expiry, reopening, retry/quarantine, concurrent claims, cancellation during fetch and restored-byte preparation. They do not substitute for a production database/object-store restore drill. A rollback must retain these additive tables and source objects; there is no destructive down-migration.

## Completeness and readiness

`ResearchJobs.health()` reports counts by job state, oldest queued time, last completed time and the existing registered-index coverage. Coverage preserves indexed/failed/pending/unsupported documents, failed/pending inventories, last discovery/index times and an explicit partial flag. `ResearchCorpus.health()` adds prepared documents, spans, embedded spans, preparation failures and preparation pending counts. These timestamps measure local pipeline activity; no measured publication-to-index latency or SLA is claimed.

`GET /research/capabilities` keeps questions unavailable when the provider or usable corpus for its retrieval mode is absent. Individual questions additionally check the exact selected scope, model preparation, current source access and historical cutoff. Company-wide questions fail explicitly while their registered inventory is partial; selecting particular prepared documents is a narrower supported workflow.
