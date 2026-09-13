# Disclosure release foundation

This change makes the existing research workflow concrete and reviewable. It is the first implementation release of the broader product plan, not a claim of worldwide coverage or enterprise readiness.

## Included

- The approved editorial homepage and responsive workspace: live company search, verified historical Apple example, consistent company navigation, explicit empty/error states.
- Source inspection for financial values, source labels, reported/derived/latest-presentation/unavailable status, arithmetic operands and Excel cell comments.
- Conservative quarterly/LTM calculations; unsupported concepts remain unavailable. EPS and share units remain correctly scaled. Unique concepts align across changing labels.
- Comparative/YTD retention in Postgres, including accession-only incremental repair.
- Resumable refresh dates and long-outage catch-up, recovery from staged failures, eventual discovery of new local/S3 data and delivery receipts.
- JSONB preference correctness, administrator-only operations reports, allowlisted telemetry, verified-email alert ownership and pause/update controls.
- Account synchronization and atomic watchlist changes, with an owner guard for account changes during a request.
- A locked Python environment, patched frontend dependencies, backend/database tests, frontend regressions and a repeatable browser acceptance suite.

## Verification

Final local results (2026-09-13): **302 Python tests passed, zero skipped**, including disposable Postgres and moto S3; **92% aggregate coverage**. **10 frontend unit tests**, typecheck, production build and **7 browser scenarios** passed with zero browser runtime exceptions. npm audit reports **zero vulnerabilities**, including development dependencies. Browser scenarios ran against the production build in headless Chrome with synthetic fixtures. Remote CI results are reported on the PR.

See [selected real-company acceptance](real-data-acceptance.md) for independently checked issuer values and the bounds of that sample. See [financial methodology](financial-methodology.md), [recovery](recovery.md), and [design](disclosure-design.md) for implementation contracts.

The browser suite deliberately uses synthetic data in an isolated lake. The homepage historical Apple example has its own verified source; the synthetic company workspace must not be treated as live financial data.

Run from the repository:

```sh
uv lock --check
uv sync --frozen --extra dev
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Postgres integration tests need PostgreSQL 16 binaries on PATH or a disposable TEST_DATABASE_URL. CI provisions that database and moto tests exercise S3 semantics. A missing Postgres installation must not be mistaken for database acceptance when tests skip.

Frontend, from web:

```sh
npm ci
npm run typecheck
npm test
npm run build
npm audit --omit=dev --audit-level=high
npx playwright install chromium
```

For the browser journey, start the synthetic API with `uv run python -m filings_hub.testing.preview_server`, then start the built web server with `FILINGS_API_URL=http://127.0.0.1:8100 FILINGS_API_KEY=preview npm start -- --port 3100` from web. Run `npm run test:browser` there. The preview API binds only to loopback and refuses a non-empty lake without its synthetic marker. CI runs the same journey and retains screenshots/export artifacts.

## Deployment and upgrade gate

1. Finish and verify the existing backfill before any serving-data reload. Keep ingestion under one scheduler; the refresh workflow serializes its own runs, but cannot coordinate an independently launched worker.
2. Reload Postgres with the default full-period loader if an existing installation contains only primary observations. New defaults retain comparisons and YTD; a daily incremental refresh cannot repair all historical rows.
3. Reconcile older failed FSDS/backfill quarters explicitly. New durable checkpoints cannot reconstruct every pre-upgrade partial write. Existing inferred FSDS dates require controlled rebuild to improve historical precision.
4. Configure the actual site URL, stable SESSION_SECRET, service API key, verified ADMIN_EMAILS, SMTP and optional Google OAuth. AUTH_DEV_LINKS must remain false in production. A local test sign-in does not verify real mail delivery or Google OAuth.
5. Validate real browser sign-in/renewal/sign-out, one consented email delivery and unsubscribe/pause, domain/TLS, backups and restore against the chosen deployment. These depend on the deployment's accounts and configuration.
6. Run coverage and wider numerical acceptance after the reload. Test representative insurers, REITs, foreign registrants, amendments and missing data, as well as quarterly/LTM values against independent sources.

No live data was rewritten for this release's acceptance sample. No production deployment or outbound customer email is part of its local verification.

## Remaining product work

The broader plan still includes global regulator sources, licensed transcripts/content, cross-company research, semantic search and cited answers, filing-change comparison, richer industry KPIs, model refresh integrations, team sharing, permissions, SSO, audit history, billing and customer migration. Each needs its own evidence and release gate. Source links are filing/document level unless an exact location is known.

Operational limits remain: lake publication is not one atomic multi-table snapshot; the lightweight account store synchronizes within one process, so multiple API processes should use Postgres; email acceptance and receipt persistence have an at-least-once crash window; stateless sessions do not yet provide per-device revocation. Anonymous browser quotas still need edge/IP abuse controls. Legacy telemetry needs an operator retention/purge policy.
