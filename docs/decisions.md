# Decisions and deferred choices

Short notes on choices made and choices parked, so nobody re-litigates them by accident.

## Parked: business-email-only sign-up

The sign-up form can reject free-mail addresses (Gmail, Outlook, Yahoo and the like) with
"please enter a valid business email address", the way AlphaSense does. The check is built and
tested, and it is **switched off by default** (`SIGNUP_BUSINESS_EMAIL_ONLY=false`) because the
owner's own address is Gmail and is needed for testing.

**Revisit once the domain name is purchased.** Then set `SIGNUP_BUSINESS_EMAIL_ONLY=true` in the
API's environment on Render (the `filings-hub-lake` environment group, or the API service's own
variables) and the form starts refusing free-mail domains. The list of free-mail domains lives in
`filings_hub/accounts.py` (`FREE_MAIL_DOMAINS`).

## Also waiting on the domain and an email relay

- Sign-up and sign-in emails need an SMTP relay (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
  `SMTP_PASSWORD`) and `SITE_URL` pointing at the public site; until then the pages say email is
  not configured and visitors keep their choices in the browser.
- Accounts on the free Render layout need the read-write R2 token on the API (the read-only one
  cannot store users).

## Product name: Disclosure (2026-09-13)

The product is called **Disclosure**. Everything a person sees says so: the site, page titles, sign-in and digest emails, the workbook's creator field. The Python package (`filings_hub`), the `filings-hub` command, the lake prefix and the Render service names stay as they are: renaming them would move live URLs and secrets for no user-visible gain. Revisit when the domain is bought and the services are recreated under it.

## Ownership: three flows, never mixed (2026-09-13)

Ownership data is three different things and the product keeps them apart everywhere: separate tables in the lake, separate sections on the company page, separate alerts, separate API responses and exports. Nothing ever lists a director's Form 4 next to a fund's 13F.

1. **Insiders.** Forms 3, 4 and 5: officers, directors, 10 % holders. The unit is the transaction (who, bought or sold, how many, at what price, open-market or exercise or gift). Daily.
2. **Outside holders.** Form 13F: managers above $100M, quarterly, 45 days late. The unit is the change since the previous quarter (new, added, trimmed, exited). Only the large managers are ever visible; the page says "reported holders", never "owners".
3. **Activists and blocks.** Schedule 13D (13G for passive). The unit is the event, with the letter to the board attached and readable. Rare, high value.

Order of work: the live flow in the current XML formats first (each new filing parsed the day it arrives and shown on the company page and in the morning view); presentation second, once real data flows; backfill last and only as far back as it helps show a change. The information value is movement going forward, not the level at first record.

Europe is per-country and comes later, after a separate brief.

### Insider rows say who the person is and how big the move was

A name alone is not information: someone looking at a company for the first time cannot tell whether John McGovern matters. Every insider row carries, from the Form 4 itself: the role (officer title, director, 10 % holder); the direction and kind of transaction (open-market buy or sale, option exercise, grant, gift, tax withholding: a grant is not a buy and an exercise-and-sell is not conviction); the size relative to the person's holding, from the "owned after" field; whether it was a pre-arranged 10b5-1 plan; and the company context (how many insiders moved the same way in the period, so a cluster of directors buying stands out). The row reads as a sentence: "John McGovern, Chief Financial Officer, sold 40,000 shares (12 % of his holding) at $52.10 under a pre-arranged plan."

Presentation: one **card per person**, not a table row. Full name on top, position in the company underneath, then the move as a sentence (kind, size, price, share of holding, plan flag), a **sparkline of the person's holding over time** built from the "owned after" field of each of their filings (it fills in from the day collection starts and gains depth when insider history is backfilled), and small chips for context ("3 insiders bought this month", "10b5-1 plan", "director"). Cards live in their own Insiders section, newest first, with buys-only and sales-only filters and a link to the filing behind each card.

Clicking a card expands it in place and reveals the documents beneath it: the Form 4 (or 3 or 5) behind the move, opened in the reader, and the person's earlier filings for this company, newest first. The card is the summary; the filings are one click below it, never a separate table. The same pattern holds for outside holders (card per manager, the 13F beneath) and activists (card per event, the 13D and its letter beneath). One table with everything in it is the thing this design exists to avoid.

## The remote lake is read per company, never listed (2026-09-13)

The first real lake on R2 (27M filings, 125M facts, statements for 46k companies) exposed the layout's cost: listing a folder costs about a second per thousand objects, the statements folder alone is millions of objects, and the API listed it at startup, every ten minutes and on every request. Startup never finished and the live site showed no data.

Rule: on object storage the API never lists a per-company table as a whole. Existence is one request; per-company tables are read from the company's own partition; the small whole-universe tables are copied locally; `filings` (by year) is read through row-group statistics, so the loaders write it sorted by company in 50k-row groups and `filings-hub compact` fixes a lake built before that. Whole-lake summaries answer from local tables only and say so. DuckDB gets a memory cap on small instances. Measured against the live lake: startup about two minutes (copying 45MB of small tables), search 0.3s, a company page 4–8s cold, statements 2–5s, repeat reads under 0.1s.

Not fixed yet, in order of value: the daily refresh on GitHub Actions still globs the statements folder (hours over R2) and needs the same treatment; a company's statements are 70 small files (one per quarter) and a per-company compaction to one file would cut a cold read to under a second; the API's read-only token means fetched documents cannot be kept between restarts.

## Next 15.5.25 stalls navigations that were not prefetched (2026-09-13)

Measured against a production build: a link navigation with no prefetched
cache entry (keyboard Enter on a focused link, a script click, touch, or a
click before the hover prefetch lands) does nothing 20–30% of the time. The
RSC request completes and the page chunk loads, but React never commits the
transition and the URL never changes; there is no error. Hovering first,
which prefetches, never fails. This is vercel/next.js#98305; the router path
that deadlocks no longer exists in Next 16.

It is what makes `ci / web` flaky (the usability pagination step and the
ownership mobile step both navigate by keyboard), and it affects real
keyboard and touch users. Decision: upgrade the web app to Next 16 in its own
PR rather than retry or loosen the browser tests. Until then a red `ci / web`
that names one of those steps is this bug, not the change under test.

Done the same day: the web app runs Next 16.3.5 on React 19.3 (`middleware.ts`
became `proxy.ts`, as the framework now requires; `next lint` no longer exists).
Against a production build, thirty scripted clicks with no prefetch stalled zero
times where 15.5.25 stalled about one in four, and every browser suite passed.

## The API opens its port before it reads a single filings footer (2026-09-13)

The first deploy of the per-company layout still never came up. Two reasons, both measured
against the live lake from a sandbox: binding a multi-file table reads the footer of every
file (about a second each over object storage), and start-up bound `filings` (126 files)
plus the four raw FSDS tables (278 files) before the port opened. Then the warm-up counted
`filings WHERE cik = 0`, which on an uncompacted lake reads every row group, while holding
the one serving lock, so `/health` waited behind it and the platform never saw the service
healthy.

Rules: the serving API binds neither `filings` nor the FSDS tables at start-up. `warm()`
binds `filings` on its own DuckDB connection (connections share the catalog and the parquet
metadata cache) and counts it, which is answered from footers alone; until it finishes the
table reads as empty. The FSDS tables are ingestion's and are never bound when serving.
`/health` never waits on the lake: it gives the serving lock a second and otherwise reports
`busy`. Ingestion keeps binding everything up front.

The other cost was per file, not per table: DuckDB asks fsspec for a file's size and
modification time about seven times per file it reads, and with no listing cache each was a
HEAD request (0.2s through the sandbox proxy; a company's seventy statement files took 84s).
The DuckDB filesystem now keeps directory listings for a minute, which answers those lookups
from the listing the glob already fetched: the same seventy files read in 7.8s cold and 1s
warm, and the 126-file filings table binds and counts in 18s. `Storage` writes and deletes drop
the listing they touch, so a process still sees its own writes at once; another process's new
partition is seen within a minute. Per-company statement compaction (one file per company
instead of one per filing) remains the next step for the company page.
