# Platform foundations delivery

Baseline: merged main `dacf79d4ac4c2511c80d2445ee563d53ee09a33e` (theme PR17). This release implements the first connected research-platform workflows from `full-platform-plan.md`. It does **not** complete that roadmap or establish AlphaSense parity. `platform-backlog.json` records implemented scope and remaining work at requirement level; no feature is marked production validated.

## Working workflows

| Workflow | Delivered scope | Main boundary |
|---|---|---|
| Find a disclosure | Global public SEC lexical search, exact words, quoted phrases, Boolean groups, company/form/date filters, exact paginated totals | Registered index only; no semantic search, synonyms, AI answers or complete live SEC coverage claim |
| Inspect evidence | Immutable source/content identifiers, original byte hash, preserved extracted text, text-PDF page offsets, source panel | Scanned PDFs, OCR, structured table/cell anchors, images and audio remain separate work |
| Save research | Personal or organization projects, user-authored notes/theses, indexed source references, explicit save, revision-conflict comparison and three starter templates | No real-time coediting, financial payload archive or verified AI interpretation |
| Keep your research portable | Authorized JSON download of saved project notes, revisions, template attribution and currently resolved references | No raw source-document redistribution, automatic importer or unsaved draft inclusion |
| Review source changes | Paginated immutable capture history and bounded before/after extracted-text comparison of the same document, with both-version access checks | Capture time differs from source-publication time; no visual PDF diff, cross-filing alignment or semantic change interpretation |
| Control access | Persisted signed sessions, device hints, expiry, revoke current/other sessions, backend logout, organization roles and audit | No SSO/SCIM, invitations, enterprise group administration or provider entitlements |
| Compare companies | Explicit XBRL concept, fiscal period and statement across up to 12 companies; source, unit, period end and missing/ambiguous state retained | No automatic FX conversion, standardized sector metrics, valuation estimates or ranking |
| Inspect financial history | Versioned financial response/content ID; original/latest comparative views; filing-date cutoff before selection and derivation; before/after value/label/context/source comparison | Date-resolution availability with current issuer/period mapping; not intraday replay or complete amendment reconstruction |
| Refresh a model | Local preview/apply CLI with explicit mappings, numeric guards, unit checks, formula/manual-override protection, source comments and a new output file | Ordinary supported XLSX packages only; no add-in, desktop Excel recalculation certification or arbitrary native-object preservation |
| Publish serving data | All financial serving tables commit/roll back together; coherent financial reads hold a shared publication lock; absent required source tables reject publication | Mutable lake generations and coordinated multi-worker ingestion remain unfinished; large loads can block reads |

The near-white, ink and royal-blue design remains. Research, Projects and Compare are reachable from workspace navigation. The statement toolbar keeps frequent controls visible and moves display details/preference scope into an expandable area. Loading, partial-index, no-match, failed mutation and conflicting-save states have specific explanations.

## Financial correctness changes

A SEC accession is not an issuer identity: joint filings can belong to several CIKs. Statement reads, period/source joins, serving-period quality attribution, quality-table keys and loader deduplication now retain CIK. Regression cases put different values and a failed check behind the same accession and verify neither issuer contaminates the other.

The advanced statement toolbar exposes an optional “Available by” date and a clear active-view notice. The cutoff travels into the export request but never silently becomes an account preference or part of a named export profile. The date cutoff is applied before choosing displayed periods, later comparative sources or any quarterly/LTM operand. Excel records the cutoff with the same source metadata. Versioned response hashes identify returned content; they do not archive the response or certify its accounting accuracy. Current company metadata and current period mapping are explicitly disclosed. Complete amended-filing reconstruction, exact source-precision migration and historical availability timestamps still require work.

Change review compares overlapping periods, distinguishes newly appearing lines from value changes, and retains both evidence records. Unambiguous concept/context matching avoids false changes when a newer filing changes the label-derived internal row key. Unit or reporting-context changes suppress arithmetic deltas. Ambiguous repeated concepts are not silently aligned.

## Read/write consistency

`load_full` and `load_incremental` serialize publishers with one transaction-scoped advisory lock. They validate required source-table inventory and record `serving_publications` inside the same transaction as serving changes. A late load failure leaves all previous data and its publication manifest intact.

Financial reads use a dedicated Postgres connection. They acquire the matching shared session lock before starting a read-only repeatable-read transaction. This ordering matters because PostgreSQL TRUNCATE is not safe for a reader holding a snapshot from before a replacement. Nested grid reads reuse the same reader; comparisons and multi-company workbook refresh share one read scope. Connection cleanup releases the lock on success or error. Direct SQL writers must follow the publication protocol; it is not a general lock against arbitrary database access.

This deliberately favors coherent responses over concurrent availability during a large replacement. Measure lock duration and deploy capacity before an institutional availability claim. Staged immutable lake/serving generations remain in D19. The local DuckDB adapter only serializes its own view access; it does not promise an immutable snapshot of files another process overwrites.

## API additions

- `GET /research/search`, `GET /research/documents/{version_id}`, captured-version `/history`, and `GET /research/compare`.
- `GET /v1/companies/{cik}/financials` and `GET /v1/companies/{cik}/financial-changes`.
- `GET /v1/compare` with explicit companies, concept, period and statement.
- `GET /platform/sources` and `GET /platform/publication`.
- Session/device, organization/member/audit and project/note endpoints documented in `account-security.md` and `research-projects.md`.
- Existing statements and Excel endpoints accept optional `as_of=YYYY-MM-DD`.

The service API key remains server-side. Account-bound routes recheck the signed persisted session. Private project reads use no shared response cache. Indexed source pointers re-resolve current public visibility on read; a saved note is not a grant to a restricted document. The grant contract has explicit storage/display/search/AI/export/offline operations and expiry/revocation, but licensed/private content ingestion is not enabled by the existence of that contract.

## Deployment and initial indexing

1. Back up the serving database and account/project state using the existing recovery procedure. Retain the prior application image. This release has not run a production restore drill.
2. Use Postgres for the production research index and account/team writes. A local lake supports SQLite development. A remote lake without Postgres returns an explicit research-index unavailable response; the repository's free root Render blueprint does not provision the new production index.
3. Apply migrations with `uv run filings-hub migrate`. This is schema-only and does not reload the financial corpus. Migrations are transactional and serialized. The paid blueprint's pre-deploy command uses this entry point, following the [Render Blueprint reference](https://render.com/docs/blueprint-spec#predeploycommand).
4. Migrations 0008–0012 add account security, research indexing, publication records, projects, and the corrected co-filer quality key. Existing v1 stateless sessions must sign in again; production SMTP or Google sign-in must actually work before rollout. The new design intentionally cannot keep non-revocable tokens active.
5. Reconcile quality rows from retained lake data after 0012. The migration prevents future collisions but cannot recreate checks discarded by the old serving key. A full reload or a targeted incremental load of affected accessions/CIKs is required. Never point the loader at an incomplete source lake: the new inventory guard rejects it.
6. Run one bounded indexing process for each discovery scope. Start with a chosen company/cohort and inspect inventory/extraction failures before broadening:

   ```sh
   uv run python -m filings_hub.research_ingest --cik 320193 --fetch --filings 25 --documents 100
   ```

   `--fetch` uses the existing configured SEC client and fair-access limits. Without it, only cached bytes are indexed. Continue bounded batches and retry failures explicitly. Search itself never fetches documents. No production indexing scheduler or backfill was activated by this code change.
7. Verify the live deployment's source register, partial-index counts, source reader, account sign-in/revocation, project persistence, coherent financial responses and Excel downloads. Observe actual freshness and load before setting service commitments. Do not enable premium sources until the specific rights, adapter and verification gates in `provider-readiness.md` pass.

Schema additions are retained during application rollback. Older applications cannot validate new v2 sessions, so session behavior and rollback must be coordinated; there is no automatic destructive down-migration. Keep personal research state and indexed immutable source objects during rollback.

## Verification

The release runs the existing Python suite plus production-Postgres/local-backend parity, concurrent reader/publisher and account/project conflict tests. Search tests cover Boolean semantics, long documents, PDF page offsets, incomplete inventories, source restriction and restart. Workbook tests write and reopen files, checking formulas, manual values, source evidence and conflict behavior.

Frontend checks include TypeScript, a production build, unit checks, and production-server browser scenarios for search/source/project continuity, device revocation, failed writes, competing note edits, comparison evidence, keyboard controls and mobile/reduced-motion behavior. Preview/browser acceptance uses an isolated synthetic lake and a mocked SEC transport. It is not a live-data coverage or real customer-model benchmark. Local verification: 436 Python tests passed with zero skips and 92% combined statement/branch coverage; 21 frontend unit tests and 18 browser scenarios passed. TypeScript, the production build, Ruff, schema consistency and the frozen dependency lock passed. The production frontend dependency audit reported no vulnerabilities. GitHub CI results are recorded on the PR. These are scoped software checks, not a financial accuracy percentage or production availability certification.

## What remains

The full 170-requirement roadmap remains active. This release does not supply licensed broker research, expert libraries/calls, paid news/transcripts, market/consensus/private-company data, worldwide regulatory cohorts, semantic search or generative research agents. It also does not implement OCR, full XBRL dimensions/sector packs, complete amendments/history, enterprise SSO/SCIM/connectors, native Office/mobile integrations, transactional monitoring delivery, billing or institutional service assurance.

Some of those require provider rights, deployment credentials, contracted specialists or independent validation. Others are still software implementation work. They are separately identified in the backlog and provider packet; neither category is silently marked complete. The next release should extend the verified contracts and workflows rather than introduce disconnected mock features.
