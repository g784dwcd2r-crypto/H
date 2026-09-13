# Account security and tenant foundation

This release adds persisted sign-in sessions, server-side revocation, organizations, explicit
memberships and security audit records. It is not SSO, SCIM, an invitation service, or a complete
enterprise entitlement implementation. Personal preferences and watchlists stay personal.

## Upgrade and session contract

Apply migration `0008_account_security.sql` before serving the new API. Postgres account-store
initialization applies versioned migrations as before. Keep a stable, secret `SESSION_SECRET` and
the normal production sign-in configuration. The API now issues `v2` tokens containing a random
session ID, user ID, absolute expiry and signature. It also requires a matching durable, unexpired,
unrevoked record on every authenticated request. Tokens are never stored in session lists or audit
records. A missing/unavailable backing record cannot fall back to signature-only authorization.

Old stateless `v1` browser sessions cannot be revoked retroactively because they have no registered
record. They are therefore rejected after this upgrade: users sign in once again. Anonymous public
browsing is retained. `SessionSigner`'s standalone no-store mode is retained for isolated signature
consumers and unit tests; `create_app` always supplies the durable store.

Each magic-link or Google sign-in creates a separate session. The optional `device_label` is a
display hint (maximum 120 printable characters), not a verified hardware identity. Otherwise the
sign-in request's User-Agent is used. The browser gateway must forward the browser's hint instead
of labeling every device with its own server User-Agent. IP addresses are not retained here.

Expiry is absolute, not sliding. Last-seen writes are coalesced to five minutes. Revocation applies
to subsequent authorization checks, including other API instances on Postgres. It does not cancel
an operation that already passed authorization. Revoking organization membership removes tenant
access, not the personal account or its other organizations.

| Endpoint | Behavior |
|---|---|
| `GET /me/sessions` | Active sessions, `current_session_id`, per-row `current` |
| `DELETE /me/sessions/{id}` | Revoke only the caller's session; another account's ID returns 404 |
| `DELETE /me/sessions/current` | Revoke the token used for this request |
| `POST /me/sessions/revoke-others` | Revoke other active sessions and return their count |
| `POST /auth/logout` | Revoke the current session in the backing store |
| `GET /me/security-audit?limit=100` | The caller's personal security events, newest first |

Session rows expose `id`, `created_at`, `expires_at`, `last_seen_at`, `device_label` and `current`.
Expired/revoked rows are excluded from the active list but retained for audit/reconciliation.
After a successful current-session revocation, the browser clears its cookie. A server error must
not be presented as successful global sign-out. A repeated request with the revoked token gets 401;
revoking an already revoked own session from another active session is idempotent.

## Organization policy

Any authenticated user can create an organization and becomes its first owner. Organizations are
listed only through current membership, never through an asserted tenant header or guessed ID.
Unknown and inaccessible organizations return the same 404. Membership is checked on every call.

| Role | Rights in this foundation |
|---|---|
| Member | Read organization and its membership roster |
| Admin | Member rights, organization audit, add/remove/change ordinary members |
| Owner | Admin rights, manage administrators and owners |

Admins cannot promote themselves or someone else to admin/owner, or alter an existing admin/owner.
At least one owner must remain. Transfer ownership by promoting another member before removing or
demoting the original owner. Concurrent removals are serialized, so two owners cannot both remove
themselves and leave an ownerless organization. A global operations administrator does not bypass
tenant membership. Roles are restricted to `owner`, `admin`, and `member`.

| Endpoint | Behavior |
|---|---|
| `GET /organizations` | `{organizations:[{id,name,created_at,role}]}` for current memberships |
| `POST /organizations` | `{name}` creates organization and owner atomically; returns `{organization}` |
| `GET /organizations/{id}` | `{organization}` including caller's current role |
| `GET /organizations/{id}/members` | `{members:[{id,organization_id,user_id,role,created_at,...}]}` |
| `POST /organizations/{id}/members` | `{user_id,role}`; existing account only, default role member |
| `PATCH /organizations/{id}/members/{user_id}` | `{role}` subject to role and last-owner checks |
| `DELETE /organizations/{id}/members/{user_id}` | Remove membership subject to the same policy |
| `GET /organizations/{id}/audit?limit=100` | Owner/admin-only security events |

This first API accepts a known existing account ID. It does not search or expose users by email,
send invitations or contact anyone. Invitation acceptance and organization provisioning controls
are separate work. Audit mutations include actor, organization, action, target, time and relevant
role changes; they exclude tokens, document content and sensitive personal profile fields.

## Stores, transactions and operating limits

Production uses Postgres. Each security operation has a dedicated connection/transaction, separate
from the legacy shared account connection. Mutations acquire a user- or organization-scoped advisory
lock; policy checks, updates and audit events commit together. Failed authorization and failed
writes roll back. Foreign keys constrain sessions and memberships to existing users/organizations.

The lake adapter stores one `account_security/state.json` document under the existing shared
per-lake process lock. Local commits use a flushed temporary file and atomic rename; a write failure
does not publish the changed state. Remote development storage writes one object. This adapter is
only for one API process; it is not a multi-host account system, and it is not a production latency
or durability claim. Use Postgres for multiple workers. Snapshot/restore must include the security
state together with accounts. Restoring an older security backup can resurrect previously revoked
records; rotate `SESSION_SECRET` after such a restore to invalidate every pre-restore token.

Expired sessions and security audit are retained until an operator-defined retention/purge policy
is implemented. The lake JSON state and unpaginated small membership roster are intentionally a
development foundation. Postgres connection pooling and large-organization pagination are later
capacity work; no measured production throughput is claimed here.

## Verification

`tests/test_account_security.py` exercises both stores: expiry boundaries, tampered/unregistered
tokens, legacy-token rejection, restart persistence, account-isolated revocation, revoke-others,
session-store failure, anonymous browsing, magic-link registration, cross-organization reads/writes,
role escalation, removed membership, audit isolation and concurrent last-owner protection.

Run with PostgreSQL 16 binaries on PATH (or disposable `TEST_DATABASE_URL`):

```sh
python -m pytest tests/test_account_security.py tests/test_accounts.py tests/test_account_concurrency.py tests/test_api_rate_identity.py tests/test_watchlist_api.py
```

These are source and disposable-database checks. Real production mail, OAuth, deployment restore,
multi-host operations, penetration testing and enterprise assurance require separate acceptance.
