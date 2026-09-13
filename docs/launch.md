# Disclosure launch and demo intake

The public header introduces the founding-member campaign and links to a separate demo enquiry.
These are different actions: requesting a demonstration or asking for a sign-in link never reserves
a founding-member place. Regional login is a preference on Disclosure Global, not a data-hosting or
filing-coverage commitment.

## Founding-member offer

- Campaign: `founding-members-2026`, twenty **individual accounts globally**, across all regions.
- Registration closes at **1 November 2026, 00:00 UTC**, when Disclosure opens.
- Reserved benefits run from **1 November 2026, 00:00 UTC**, inclusive, to **1 May 2027, 00:00 UTC**,
  exclusive: six calendar months from launch, not 180 days or six months after clicking a link.
- An authenticated account explicitly accepts the offer terms to join. Public accounts authenticate
  by redeeming an email link or completing Google sign-in with a verified email. The request cannot
  provide another user ID or allocate on behalf of an organisation.
- The first twenty successful allocation transactions reserve a place. Later verified opt-ins join
  the waitlist before the same deadline. Waiting does not grant access or promise promotion.
- One account retains its original place, region and acceptance timestamp across retries and devices.
  Selecting another region cannot create another allocation. There is no automatic charge, payment
  collection, subscription creation or automatic promotion in this flow.
- The launch entitlement is derived from a durable reservation and the dates above. It is active only
  during that interval. This release has no paid feature gates to lift: the launch plan covers the
  available research workspace. Future billing or paid access controls must consume this entitlement
  rather than treating the underlying `users.plan` field as the complete entitlement decision.
- Optional AI remains subject to the deployment's actual provider availability and configured usage
  limits. This offer does **not** create provider credit, expand quotas or promise unlimited AI.

All dates, allocation counts and availability are returned by the API. The public interface must
show unavailable/error states honestly rather than inventing a remaining-place count. The selected
region is one of `US`, `UK`, `EU`, `AU`, or `ROW` (Rest of the world).

## API contract

The existing service-key gateway protects these API routes. User mutations additionally require a
valid durable `X-Session`; the web gateway owns secure cookies and forwards credentials server-side.
Successful campaign, membership and demo responses use `Cache-Control: private, no-store`.

### `GET /launch/campaign`

Returns `{campaign}` with:

```json
{
  "id": "founding-members-2026",
  "opens_at": "2026-11-01T00:00:00+00:00",
  "registration_closes_at": "2026-11-01T00:00:00+00:00",
  "benefit_starts_at": "2026-11-01T00:00:00+00:00",
  "benefit_ends_at": "2027-05-01T00:00:00+00:00",
  "capacity": 20,
  "allocated": 0,
  "remaining": 20,
  "state": "open",
  "individual_accounts": true,
  "auto_charge": false,
  "ai_allowance": "Optional AI is subject to configured availability and usage limits; unlimited AI is not included."
}
```

The counts above illustrate an empty campaign; actual responses read committed allocation records.
`state` is `open`, `full`, or `closed`. `closed` takes precedence from the registration deadline even
when places remain. Public responses never include member identities or email addresses.

### `GET /me/early-access` and `POST /me/early-access`

Both return `{campaign, membership, entitlement}`. The POST body is:

```json
{"region": "ROW", "accept_terms": true}
```

`membership` is `null` until explicit opt-in. Thereafter it contains `status` (`reserved` or
`waitlisted`), `position` (global joining order), `region`, `joined_at`, `benefit_starts_at` and
`benefit_ends_at`. Waitlisted entries have null benefit dates. Positions are not promises of
waitlist promotion. `entitlement` contains `active`, `phase` (`none`, `upcoming`, `active`, or
`expired`, derived from the server clock), `plan` (`launch` only while active, otherwise
null), `starts_at` and `ends_at` (null without a reservation).

Missing/invalid sessions return 401. Invalid region/terms return 422. New opt-ins at or after the
deadline return 409; retries for an existing membership still return its original record. Suspended
accounts cannot reserve a place. Reservation and account audit are written in the same transaction.

### `POST /demo-requests`

This is public to visitors through the service gateway and does not require an account. Body:

```json
{
  "request_id": "1b5179ab-768e-4ef1-981a-53e7a0d08af1",
  "name": "Alex Analyst",
  "email": "alex@example.test",
  "organisation": "",
  "region": "ROW",
  "workflow": "Compare the latest results with previous periods."
}
```

Name: 1–120 characters; email: valid address up to 254; optional organisation: up to 160; workflow:
10–3,000. Surrounding whitespace is removed, email is lowercased, unsupported fields and control
characters are rejected. Both personal and business email addresses are accepted.

On success, HTTP 201 returns `{received: true, reference: request_id}`. Persisted requests start at
`new`, revision 1. The client supplies one UUID per logical submission and retains it for retries.
Identical retries return the same reference without a second lead or additional rate-limit use;
reuse with changed content returns 409. There is no public endpoint to retrieve a lead or its PII.

Durable submission limits allow at most three new requests per normalised email per hour and five
per authenticated user/anonymous caller identity per hour. The store retains a keyed fingerprint,
not the raw IP address or visitor identifier. Limits survive service restarts and apply across
Postgres workers. Limits return 429 and `Retry-After`; the general API rate limit also applies.
The anonymous gateway visitor cookie is the ordinary caller identity. These limits are basic abuse
controls, not a claim that bots cannot obtain new email addresses and visitor identities.

Receiving a demo enquiry stores it for operator review. It does not send a message, create a calendar
booking, or reserve one of the twenty places. The success page must not say that a meeting is booked.

## Operator demo management

`GET /platform-admin/launch-memberships?q=&status=&limit=25&offset=0` also gives the operator a
read-only founding-group roster, with `{campaign, items, total, limit, offset}`. Rows include the
account ID, email/name when available, global position, region, reserved/waitlisted state, joining
timestamp and benefit dates. Search covers name, email and account ID; the optional status is
`reserved` or `waitlisted`. There is no manual allocation override or editable place count.

- `GET /platform-admin/demo-requests?q=&status=&limit=25&offset=0` returns
  `{items, total, limit, offset}`. Search covers name, email, organisation and reference. Status is
  optional; page size is 1–100. Operator-visible rows exclude internal deduplication/caller hashes.
- `POST /platform-admin/demo-requests/{id}/status` changes the status to `new`, `contacted`,
  `scheduled` or `completed`. Corrections are allowed in either direction, with review and audit.
- The mutation body includes `status`, `expected_revision`, a meaningful `reason` of 8–500
  characters, and `confirmation: "demo.status:{id}"`. It returns `{request: updated}`. A stale
  revision returns 409 instead of silently overwriting another operator's work.
- Existing operator separation, exact origin, JSON requirement, CSRF, mandatory initial password
  change and fresh five-minute reauthentication apply. An ordinary user or organisation owner
  cannot read leads or change their status. Each status change and audit commit together; audit
  metadata records the reason/status transition, not the lead's name, email or workflow text.

## Email sign-in continuation

`POST /auth/magic-link` and `POST /auth/signup` accept optional `next` and `region` fields. The
actual emailed callback URL contains those values, so a link opened in another browser/device
retains the early-access destination and region. Supplying only region defaults the destination to
`/`; omitting both retains the existing callback URL. No reservation is made during authentication.

The backend validates local relative destinations and rejects external/protocol-relative URLs,
backslashes, control characters, encoded unsafe variants, and normalised `/api` or `/auth` routes.
Invalid context returns 422 before a token is stored. The frontend callback must independently
validate the context before redirecting. Google continuation remains tied to its validated OAuth
state in the web gateway.

## Storage, deployment and verification

Migration `0017_launch.sql` adds `launch_memberships` and `demo_requests` using the existing
`SecurityStore` transaction adapter. Regenerate `schema.sql` with `make schema` whenever migrations
change. Existing migration setup applies the new tables during normal deployment account setup.

Production allocation **requires Postgres**. A campaign advisory transaction lock serializes every
allocation across processes; unique campaign/account and campaign/position constraints prevent
duplicates, and reserved positions are constrained to 1–20. Demo deduplication and rate-limit checks
also share a database transaction across workers. No live deployment database is changed by the
implementation or its tests.

The local lake adapter uses one shared root lock and atomic state replacement and is supported for
**one API process only**. It is useful for previews/tests; a shared lake with multiple API workers
does not provide the production concurrency guarantee. The same limitation already applies to
account/session and project writes. Do not run the public founding-member campaign that way.

`tests/test_launch.py` exercises both lake and disposable Postgres: independent-connection races
for the last place, concurrent same-account claims across regions, durable demo limits, failed-audit
rollback, verified opt-in, private membership access, offer dates/expiry, operator separation and
reviewed revisions, and email-link continuation. Account/security/admin/migration regressions run
alongside it. Browser acceptance covers the public journeys and actual operator inbox integration.
The explicitly marked synthetic preview servers freeze only campaign time at 13 September 2026 so
browser acceptance can reserve before launch even when CI runs later; auth/session time remains
real. Production uses the actual clock.

## Public web experience

The public header applies to the landing page, platform, solutions, coverage, security, resources,
company, demo, early-access and privacy pages. Research, companies, statements, watchlists, projects
and account settings retain the working navigation. The existing wordmark and final identity fonts
and colours are unchanged.

Platform and Solutions use two-column destination menus with an illustrative product example.
Resources and Company have smaller content sets. All destinations have actual page content and
working section anchors. Menus open by click/tap, close on Escape or outside focus/click, and return
focus to their trigger. Mobile uses accordions inside a viewport-bounded panel. Transitions respect
reduced-motion preferences.

The launch bar reads actual campaign state, supports local dismissal, and refreshes when the window
regains focus or a membership is reserved. It uses no invented remaining count when the service is
unavailable. The early-access page shows the confirmed count and requires an explicit offer checkbox.
The demo/contact form retains text and its request UUID across failed delivery so a retry can recover
an already persisted enquiry. Throttled responses retain the upstream `Retry-After` header.

Login regions are remembered in the non-sensitive `fh_region` cookie for one year with SameSite=Lax
and Secure on HTTPS. Google continuation is held in a separate ten-minute HttpOnly cookie, scoped to
its callback path and bound to random OAuth state. A callback cannot override that saved destination
or region. Email sign-in retries also retain destination and region.

`npm run test:browser` includes public navigation and launch journeys; `npm run test:admin` includes
persisted enquiries, reviewed status changes and the read-only founding roster. Google callback
routing is covered with mocked provider responses; these tests do not establish that a deployment's
live Google credentials, SMTP delivery or paid AI provider have been configured successfully.

Public pages do not sit behind the workspace loading boundary: their initial HTML remains readable
without JavaScript. Workspace sections retain their existing loading experience, including the
separate research skeleton. Browser acceptance checks this across public and sign-in pages.
