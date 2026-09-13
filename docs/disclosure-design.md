# Disclosure design and browser acceptance

## Product direction

The public homepage implements the approved editorial reference: warm white, near-black text, broad serif headings, thin rules, direct company search, and a compact financial workspace. Blue identifies selection and source evidence. Research pages share this language with denser tables and controls. System fonts remove a third-party font request and keep the layout usable offline.

The homepage is real HTML, not a screenshot. The example's three tabs and financial cells work, and each selected observation links to the original source. Apple is identified by a neutral letter monogram, not an unofficial recreated brand logo.

## Historical example provenance

The five annual metrics for fiscal 2024 and 2023 were checked against page 1 of Apple's FY2024 results:

- Original: https://www.apple.com/newsroom/pdfs/fy2024-q4/FY24_Q4_Consolidated_Financial_Statements.pdf
- Twelve-month periods ending September 28, 2024 and September 30, 2023.
- USD millions: total net sales 391,035 / 383,285; total cost of sales 210,352 / 214,137; gross margin 180,683 / 169,148; operating income 123,216 / 114,301; net income 93,736 / 96,995.
- The example is explicitly historical. Its source link uses the verified PDF page. It makes no claim to represent the latest available company data.
- The example financials link opens the live company workspace. Exporting is done through the actual workspace's export dialog.

## Interaction rules

- Search accepts company names, tickers and CIKs. Abort obsolete suggestion requests; a failed API request is distinct from zero matches. Arrow keys select results, Enter opens, Escape dismisses, and `/` focuses search.
- Financial cells show a dash for unavailable values and `0` for zero. Every non-heading cell can be inspected, including unavailable cells.
- Evidence uses per-observation metadata: status, reason, formula, original label, exact dates, reported inputs, source unit clarification and supporting filing links. It never invents a page anchor.
- The source panel stays beside the table on desktop. On compact displays it opens as a closable panel above the bottom edge, preserving the table's location.
- Per-share observations and share counts are unscaled, matching Excel. A defensive concept check protects per-share facts from older APIs that label EPS as `USD`.
- Preferences update only after persistence succeeds. Same-key writes are serialized; failures retain the prior saved setting and show an error. Export follows the current table's scale and negative formatting.
- Signed-out watchlists use browser storage. Signed-in watchlists use freshly fetched account state. Failure to load the account must not import or overwrite it with the browser's list.
- Email alerts use the authenticated account's verified email. A user explicitly enables, updates or pauses alerts. Alert companies are a disclosed snapshot of the followed list until updated.
- Coverage states remain factual. International interest forms collect demand without promising delivery dates or priority.

## Responsive and accessible behavior

The mobile homepage places search ahead of the simplified financial example. Wide research tables scroll inside their containers. Semantic landmarks, headings, labels, skip navigation, visible keyboard focus and reduced-motion support are included. A 390px viewport DOM inspection found no page overflow on the homepage. Main account and source interactions must also pass the browser test suite after API changes.

## Validation

```sh
cd web
npm ci
npm test
npm run typecheck
npm run build
npm audit
npm run test:browser
```

`npm test` covers unit scaling, zero/missing distinctions, colon-containing preference scopes and failed persistence. The maintained browser smoke test supplies end-to-end coverage with the local fixture service. A successful build and unit suite do not establish financial accuracy outside the independent financial benchmark.

Next.js is pinned to patched maintenance release 15.5.25 and React/React DOM to 19.1.9. Explicit PostCSS 8.5.28 and sharp 0.35.4 overrides close remaining transitive advisories; review whether each override remains necessary on the next framework update. The install audit was clean when these versions were selected. The relevant Next.js security release is https://nextjs.org/blog/august-2026-security-release .

## Gateway rate identity

The web app's shared service API key authenticates the gateway; it is not the request-rate identity. `lib/server-api.ts` is protected by `server-only` and is the only module that reads or sends this key. `lib/api.ts` contains browser-safe shared types and formatting only.

Middleware issues the `fh_visitor` cookie with a random UUID, a 30-day expiry, an HMAC and HttpOnly/SameSite=Lax settings (Secure on HTTPS/production). It overwrites caller-supplied identity headers and forwards a newly issued cookie into the first server render. The transport independently verifies that cookie and constructs an allowlist of outbound headers. Export downloads use this transport too.

After validating the API key, the backend rate limiter uses the verified session's user ID, or a visitor ID asserted by a header-authenticated gateway. It falls back to the direct peer IP for direct API calls, missing/malformed visitor identities and development without a key. Arbitrary session strings and X-Forwarded-For values cannot choose a rate bucket. Different signed sessions for the same user share a budget. Expired buckets are reclaimed.

The API key is a trusted gateway/service credential: do not publish it to browsers or distribute it as an untrusted public-client key. Anonymous visitors can obtain new identities by clearing cookies; the application limiter is therefore not a substitute for edge/IP abuse protection. Limits remain process-local, so deployments with multiple API workers should use a shared limiter before promising a global quota.

Regression coverage is in `tests/test_api_rate_identity.py` and `web/tests/gateway-identity.test.cjs`, including service-key-first validation, separate browsers, shared signed-user budgets, invalid tokens, direct-client fallback, cookie integrity and middleware header replacement.
