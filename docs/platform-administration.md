# Platform administration

This release adds a dedicated `/admin` operational console. It does not deploy the console, create
a production administrator, connect paid providers or start an ingestion scheduler. Operator
credentials are separate from ordinary users and organization roles.

## Explicit bootstrap and recovery

The service is disabled by default. No administrator or password is installed by migrations or API
startup. The dedicated bootstrap username is `disclosure`. Passwords are read with `getpass`; do not
put them in command arguments, source files, URLs, shell history or shared screenshots.

For an isolated local development store, enable these settings on the API and set the same origin
on the web gateway. Use an empty or local Postgres `DATABASE_URL`, a local `LAKE_ROOT`, and loopback
API/web listeners. Never point this flow at a live lake or production accounts.

```sh
export PLATFORM_ADMIN_ENABLED=true
export PLATFORM_ADMIN_ENVIRONMENT=development
export PLATFORM_ADMIN_ORIGIN=http://localhost:3201
export PLATFORM_ADMIN_LOCAL_BOOTSTRAP=true
uv run python -m filings_hub.platform_admin bootstrap --username disclosure --local-bootstrap
```

The requested initial `1234` is accepted **only** by that explicitly enabled local flow. All initial
credentials, including strong ones, require replacement on first sign-in. Before replacement, the
session can inspect its own state, change its password or sign out; it cannot read account lists,
research health, audit records or any other management resource. A replacement must be 16–256
characters, contain at least eight distinct characters, differ from the current password, and avoid
the small built-in set of obvious defaults. A password manager generated credential is preferred.
The console never supplies a default password to the browser.

For a production configuration, `PLATFORM_ADMIN_ENVIRONMENT=production` requires an exact HTTPS
origin, Postgres and a service API key of at least 32 characters. Local bootstrap must be false.
Production rejects a persisted, unchanged local-bootstrap credential as well as attempts to enable
the weak bootstrap flow. Provision secrets through the deployment's secret manager and run the same
CLI **without** `--local-bootstrap`, supplying a strong initial credential. No production command was
run as part of this release. Use the same `PLATFORM_ADMIN_ORIGIN` on the API and trusted web gateway.

Recovery is an explicit server-side operation:

```sh
uv run python -m filings_hub.platform_admin recover --username disclosure
```

Recovery requires access to the configured account store and a strong replacement credential. It
revokes every prior administrator session, resets authentication lockout, forces a further password
change at sign-in and records an audit event. It cannot recover an account that does not exist.
Protect CLI/deployment access: it is the out-of-band administrative trust boundary. There is no
public recovery link or administrator creation endpoint.

## Authentication and request protection

Passwords use unique 16-byte salts and scrypt (`N=2^17`, `r=8`, `p=1`) with versioned hashes. This
follows the current [OWASP password-storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).
The API stores a hash of each random opaque session token, never the bearer token. Sessions have
an absolute 30-minute default expiry, configurable from 5 to 60 minutes. Every request checks the
persisted session; a signed ordinary-user token, asserted email, role header or tenant membership
cannot substitute for operator authentication.

The trusted Next.js gateway keeps the opaque token in a strict, HttpOnly cookie. HTTPS uses the
`__Host-disclosure_admin` cookie with `Secure`, no domain and path `/`. Explicit loopback development
uses `disclosure_admin_dev`. Tokens are removed from gateway JSON responses. Incoming service-key,
operator-session, user-session and role headers are not forwarded as authority. The service key
remains server-side; the admin API does not accept it in query strings.

Mutations require the exact configured Origin, JSON and a session-bound CSRF token. Login requires
the Origin check before credentials are processed. Responses disallow caching; the admin page
disallows framing and sets a no-referrer policy. These implement specific controls from the
[OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html),
not a claim that the application has undergone independent security certification.

Failed password attempts persist across restarts and API processes. Five failures lock the operator
for a minute; further failures increase the delay up to 15 minutes. Incorrect usernames share the
operator's lockout and password verification cost. Recovery can clear lockout. This deliberately
limits guessing but can allow an attacker with gateway access to cause a temporary authentication
denial; deployment-level abuse controls and network access policy remain important operating work.

Password changes revoke every earlier administrator session. Reauthentication rotates the current
session and grants a five-minute window for privileged writes. The UI asks for the password during
each reviewed change; the API independently checks the window, exact action/target confirmation,
reason and saved revision. Logout revokes the backend record before clearing the cookie. A failed
logout retains the browser state; an already invalid backend session may be cleared safely.

## Permission matrix

| Identity | Operations and private-data boundaries |
|---|---|
| Anonymous or ordinary account | No control-plane access |
| Organization owner/admin | Existing organization privileges only; no platform elevation |
| `ADMIN_EMAILS` allowlisted ordinary account | Existing read-only operations/analytics routes; no control-plane privilege |
| Bootstrap operator before password change | Own session status, password change, logout only |
| Operator with completed password setup | Read operational metadata, paginated management lists, source readiness and privileged audit |
| Operator with recent reauthentication and exact review | Suspend/resume accounts, revoke account sessions, change organization memberships, change documented registration controls; job retry/cancel when integrated |
| Server-side recovery operator | Reset the dedicated credential and revoke all administrator sessions through the CLI |

The console deliberately does not expose private project names, note/thesis bodies, preferences,
research exports or provider document text. Account email/name/company, status, plan label, dates,
active-session metadata and organization membership are operational information available only to
the platform operator. Plan labels are read-only: the console does not fabricate billing or paid
entitlements. It does not impersonate customers or turn the operator into a member of every tenant.

## Working operations and consistency

- **Accounts:** searchable, paginated list; account/session/membership detail; suspension/restoration
  and session revocation. Suspension is enforced by ordinary session creation and verification,
  revokes active sessions, and survives API restarts. Restoring an account does not resurrect old
  revoked sessions. Operations already authorized before revocation can finish.
- **Organizations:** searchable, paginated list and membership detail; add an existing account,
  change a role or remove membership. The same organization advisory lock as ordinary membership
  updates protects these writes. The last owner cannot be removed, even by concurrent operators.
  A selected role or explicit JSON null is required; omitted roles and invalid types are rejected
  without changing membership or audit history.
  Version fingerprints detect changes made through the ordinary organization API too. No invitations
  or external messages are sent.
- **Configuration:** persisted new-account registration and business-email controls affect actual
  account creation through magic-link and Google paths. Existing users can still sign in unless
  suspended. Changes do not retroactively cancel an account creation already authorized in flight.
  Mail/OAuth presence and session duration are shown as deployment settings; secrets are not exposed
  or editable. The console cannot grant provider contracts, turn on licensed content or claim that
  a configured email provider has passed live delivery verification.
- **Research:** registered index counts, last observed discovery, extraction failures, unsupported
  documents, pending records and incomplete inventories. “Observed recently” uses an explicit
  24-hour operational threshold; it is not a freshness SLA. Missing index/deployment components show
  unavailable or unknown rather than zeros that imply successful ingestion.
- **Audit:** searchable, paginated privileged changes, authentication and recovery events with
  actor/action/target/time and non-secret change metadata. A required operational reason accompanies
  management changes. No API edits or deletes audit rows. The database administrator can still alter
  database contents; this is not an independently tamper-proof or legal-retention archive.

Postgres administrative mutations acquire a platform lock and the relevant user/organization lock,
then check authorization, compare the revision and write both state and audit within one transaction.
A failed audit write rolls back the associated account, session or membership change. Concurrent
saves have one winner and a visible 409 conflict. Local lake development uses the existing atomic
single-process security state; production/multiple writers require Postgres. Lists use bounded SQL
pagination in Postgres. Local lake lists scan the small development account inventory; production
throughput, pooling, retention and large-tenant roster pagination require capacity work.

## Job-engine integration boundary

The console consumes `filings_hub.research_jobs.ResearchJobs`; it does not implement a second queue
or worker. If that separately delivered module/schema is absent, job controls clearly show
unavailable. When present, the adapter exposes health, paginated jobs, ID/status search and reviewed
retry/cancel. Internal worker lease tokens, worker IDs and idempotency keys are excluded from browser
responses and audit. No job is enqueued and no scheduler is activated merely by opening the console.

Because the job engine owns a separate transaction, an auditable intent is committed **before**
calling its revision-checked mutation, and a confirmed/rejected outcome follows it. If the process
or completion audit fails between those transactions, the command remains visibly pending for
reconciliation. The console does not claim rollback of an already committed job action or blindly
replay it. Inspect the current job revision and the recorded command before deciding what to do.
This is a deliberate boundary, not a distributed exactly-once execution guarantee.

## API and rollout

All backend routes below are under `/platform-admin`; the web gateway is `/api/platform-admin`.

| Routes | Contract |
|---|---|
| `POST /login` | `{username,password}`; issues restricted/full operator session state |
| `GET /session`, `POST /logout` | Current operator state; durable revocation |
| `POST /password` | `{current_password,new_password}`; revokes earlier operator sessions |
| `POST /reauthenticate` | `{password}`; rotates session and grants five-minute reviewed-write window |
| `GET /overview`, `/research`, `/jobs`, `/sources` | Observed operational metadata and explicit unavailable states |
| `GET /users`, `/organizations`, `/audit` | `q`, `limit` (1–100), `offset`; `{items,total,limit,offset}` |
| `GET /users/{id}`, `/organizations/{id}` | Operational detail, session/membership metadata and saved revisions |
| `POST /users/{id}/status` | `{status,expected_revision,reason,confirmation:"account.status:{id}"}` |
| `POST /users/{id}/revoke-sessions` | `{expected_revision,reason,confirmation:"sessions.revoke:{id}"}` |
| `POST /organizations/{org}/members/{id}` | `{role,expected_version,reason,confirmation:"membership.change:{org}:{id}"}`; null role removes, `absent` adds |
| `GET /configuration`, `POST /configuration` | Read settings; update boolean registration controls with `expected_revision`, reason and `configuration.change:registration` confirmation |
| `POST /jobs/{id}/retry`, `/cancel` | Expected job revision, reason and `job.retry:{id}` / `job.cancel:{id}` confirmation; requires integrated engine |

Apply migration `0015_platform_admin.sql` through the normal migration command before rollout. It
adds operator/session/audit/account-control/settings/job-command tables; it creates no credentials.
Migrations 0013–0014 are reserved for the independent research release and are not prerequisites for
ordinary admin accounts/roles/configuration. Use an application image containing matching migrations.
Retain these tables and the security lake state during rollback; dropping them can remove suspension
and revocation records. Restore/recovery must revoke historical administrator sessions before access
resumes. No production restore drill or deployment was performed for this change.

## Verification and remaining limitations

Integration with merged PR19 passed the full 466-test Python suite with disposable PostgreSQL
enabled (zero skips; 91% suite coverage), followed by the focused 31-case administrator suite after
the independent review fix added lake/Postgres malformed-membership regressions. All 30 web unit
tests, the production Next.js build, all four user browser suites and all six admin browser scenarios
passed. An isolated, untracked combined snapshot also passed the real research-job
adapter test on SQLite and PostgreSQL: cancel fenced the old worker claim, retry queued the job and
both changes produced requested/confirmed audit records. That integration evidence does not add the
separately delivered job engine to this PR. All fixtures were synthetic; no production rollout or
live-provider test is implied.

The targeted Python suite covers local and disposable Postgres operation, forced password change,
durable lockout, expiry, forged ordinary/operator identities, allowlisted-email separation, cross-tenant
access, suspended-session enforcement, exact review/CSRF/origin gates, rollback, conflicting saves,
last-owner concurrency, pagination, private-content exclusion and job-command uncertainty. Gateway
tests exercise token stripping, cookie flags, identity allowlists and failed logout behavior. Browser
acceptance uses the synthetic `filings_hub.testing.admin_preview_server` and proves the path from
bootstrap to strong change, a real suspension, rejected ordinary access, audit, failed/successful
logout and subsequent sign-in. It does not use live accounts or backfills.

MFA is **not implemented** in this release and is explicitly shown as not configured. A future
integration should use a dedicated operator IdP/OIDC audience with verified issuer/signature/audience,
an enforced MFA authentication-context claim, explicit mapping to provisioned operators, recent
authentication for sensitive actions and immediate deprovisioning. It must not trust caller-selected
identity headers or silently promote existing `ADMIN_EMAILS` accounts. Passkeys/TOTP with encrypted
secret recovery is an alternative separate security release. Neither path is claimed to work today.

Other remaining work includes multiple named operators and fine-grained platform roles, independent
penetration testing, tamper-resistant audit export, retention/erasure policy, bulk user support flows,
production recovery drills and measured multi-host capacity. This is a working control-plane slice,
not completion of D17/D19/D20 or certification for unrestricted institutional production use.
