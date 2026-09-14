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

## FSDS: every row and every column is kept (2026-09-14)

The loader used to project a fixed column list and drop `num` rows that carry a `segments` (or
`dimh`) value, on the reasoning that statements only use line totals. That silently left out the
segment, geography and per-investment breakdowns the SEC publishes, and eleven address columns of
`sub`. The rule is now: nothing the SEC publishes is dropped. Typed core columns stay typed, every
other column passes through as text (so a column the SEC adds later lands without a code change),
and `num` gains a `dimensional` flag computed from `segments` / `dimh`. The statements builder
filters on `NOT coalesce(dimensional, false)`, so quarters loaded before the flag existed (which
hold totals only) still build. Loading all rows roughly doubles the `num` tables; the raw zips live
only where the backfill ran, so the reload of all quarters (`filings-hub fsds --all`) runs on the
Mac and `fsds/` is synced up afterwards. Statements need no rebuild.

## FSDS lines the SEC quotes around a tab are re-joined, not rejected (2026-09-14)

The SEC's data-set files are tab-separated and unquoted, so the loader reads them with quoting
off and records any line it cannot place as a reject rather than guess. Four quarters carried
152 such lines, all schedule-of-investments rows of Business Development Companies whose
investment name held a tab: the SEC's writer had wrapped that one value in double quotes. Read
with quoting off, the line had one field too many. The loader now runs a byte-level pass before
any encoding decision: a data line wider than the header whose extra fields are explained by one
double-quoted run is re-joined (tabs as spaces, quotes stripped) and counted as `repaired_rows`
in the load log; anything else still lands in the rejects. `filings-hub fsds <quarter>...` reloads
chosen quarters from the raw zips, which live only where the backfill ran (the raw prefix is not
part of the R2 lake), so the reload runs on the Mac and the four quarters' `fsds/num` partitions
and `fsds/load_log` are synced up afterwards.

## Submissions header: every field on the companies table (2026-09-14)

`parse_company_header` used to keep seventeen fields of the SEC's submissions document and drop the
rest: both full addresses (business and mailing), the owner organisation, LEI, description, investor
website, flags, the insider-transaction markers and the from/to dates on former names. The raw JSON
only lives where the backfill ran, so for anyone reading the lake those fields did not exist. The
header schema now carries every top-level field, addresses flattened as `business_*` / `mailing_*`,
the former-names list verbatim as JSON, and `header_extra`: a JSON object of any top-level key the
parser has no column for, so a field the SEC adds later lands on the next refresh without a code
change. The companies table copies every header column through (`HEADER_PASSTHROUGH`), Postgres
gains them in migration 0018, and `filings` gains `core_type` (the SEC's grouping of a form with its
amendments). Per-filing keys the loader does not store are logged once per process rather than
stored: the filings table is 27M rows, and a new per-filing field is a schema decision. Existing
lake rows read back with the new columns null until the next refresh (headers) or backfill
(filings history).

## A wrong check is worse than no check (2026-09-14)

`income_after_tax` compared pretax income minus tax against whatever bottom-line concept came
first, which fell through to `ProfitLoss`. Citigroup passed 64 % and Morgan Stanley 64 %, not
because their filings are wrong but because the check was: pretax minus tax is income from
CONTINUING operations, and both report discontinued operations after tax below that line, while
their pretax concept's own name (`...MinorityInterestAndIncomeLossFromEquityMethodInvestments`)
says the share of associates' profit is excluded from the subtotal. The check now bridges both
before comparing, and prefers a reported continuing-operations line when the filing has one.

Two checks added on the same principle. `eps_basic` / `eps_diluted` recompute earnings per share
from the company's own weighted-average share count, and refuse to run when preferred dividends
are present without an available-to-common numerator, because the numerator would be a guess.
`net_income_is_equals_cf` and `ending_cash_cf_equals_bs` compare the SAME concept on two
statements, never two concepts that sound alike, so a filing carrying cash-with-restricted-cash on
one statement and cash-without on the other is not reported as a break. Cross-statement results are
stored with `statement = 'XS'`.

## Unless the user says otherwise, keep to the company's presentation (2026-09-14)

Hicham's rule, and it governs every display decision below it: **a statement page reproduces what
the company printed.** If a line was presented as one line, it is one line. If it was presented as
three, it is three. We never merge, never split, never invent a total the company did not report.

The corollary: anything we compute is a separate view, visibly ours. Our own table may show total
revenue with a control that opens the parts underneath; that is analysis, not reproduction, and the
reader can tell which is which. Breakdowns open in a side panel rather than being folded into the
statement.

Why this is the right rule for an integrity product: it makes every disagreement checkable. If our
page and the filing differ, we are wrong. There is no judgement call to defend.

What it demands of the pipeline: to reproduce a presentation we must know it. The data sets' `pre`
table names a tag once per statement line with no dimension attached, so where a company printed
several lines that share one tag and differ only by dimension, `pre` alone may not tell us how many
lines there were or which value belongs to which. Whether it does is an open question being
measured; if it does not, faithful reproduction requires reading the original filing rather than
the summary files.

## Segments: the company's words on the page, a type tag underneath (2026-09-14)

Hicham settled the segment-naming question, and not the way it was framed. The page keeps the
company's own wording, because an analyst takes those words into a call with management and a
made-up division name is useless there. What gets standardised is not the name but the **kind** of
segmentation, held internally per company per axis. Four kinds cover roughly 90 % of cases:

1. geography
2. product
3. sub-company
4. customer

So a company carries tags like `Apple: geography` and `Apple: product`, because Apple reports revenue
by region and separately discloses unit sales by product. The platform can then offer segmentation
views without ever renaming what the company said.

Why this is much cheaper than the alternative: mapping member names would have meant reviewing
roughly 14,000 invented names (5,373 on the business-segments axis, 8,790 on product/service).
Classifying the kind of segmentation is per company per axis, and the SEC's axis names already give
three of the four almost free: `Geographical` is geography, `ProductOrService` is product,
`LegalEntity` and `ConsolidatedEntities` are sub-company. The work is the `BusinessSegments` axis
(158,080 facts, 5,373 members in one quarter), whose meaning varies by company: for Apple it is
geography, for others it is product or division.

Edge cases outside the four kinds are deferred. Hicham's instruction: we will meet them, there are
not many, do not design for them now.

## The equity statement waits; five disclosures come first (2026-09-14)

Hicham: the statement of changes in equity is a real statement but "nowhere close to importance" as
the balance sheet, income statement and cash flow. It should exist eventually. Ahead of it, in his
order, the disclosures analysts actually reach for:

1. Segmentation
2. Debt schedule
3. Preferred equity and other hybrids
4. Acquisitions
5. KPIs

This reorders the plan after the three core statements are correct: the next work is these five, not
the fourth statement.

## Pre-2009 history: map a company's own dictionary backwards (2026-09-14)

No XBRL tags exist before about 2009, only HTML tables with English labels. Generic parsing means
guessing across thousands of label variations, which is the thing we spent 2026-09-14 removing.

The approach instead: a company's statement barely changes year to year, so for any company that
filed with tags in 2009 or later we already know its own wording. Apply that company's dictionary
backwards to its own older filings. No cross-company guessing; a company is matched only to itself.
`_template_for` in `sync_statements.py` already does this for filings the data sets do not cover, so
this extends existing machinery rather than inventing new.

It only works for companies still filing after 2009. Hicham: fine, nobody analyses Blockbuster or
Toys R Us. Dead filers become a separate later project, a "companies no longer with us" explorer.

Scope: listed companies, annual reports, 2001 onwards (pre-2001 is plain text rather than tables,
and stops being worth it). Roughly 75,000 documents, under a day to fetch, and a few weeks of work
overall, most of it verification rather than parsing. Remaining hard parts: reading the "in
thousands / in millions" header correctly, bracketed negatives, and companies that changed layout
mid-period.

Values derived this way are read from a table, not filed as tags. They must be labelled as derived
wherever they appear, so a reader always knows which numbers are reproductions and which are
readings. Sequenced last, after the three core statements and the five disclosures.

## Data quality is an internal check, not a user-facing feature (2026-09-14)

Hicham: the arithmetic checks are ours, not the reader's. What matters to a user is that the filings
are there and that everything is easy to understand. So `statement_checks` stays an engineering and
operations signal: it gates what we publish and tells us where to look, and it does not appear on the
page as badges, scores or warnings.

Related, same conversation: foreign-domiciled filers (20-F, 40-F) are not "international filers" and
are not a scope question. They file under US regulation, they are listed in the US, an investor can
buy them, so they are in. The lake already holds 2,020 such companies, 1,363 listed, 1,208 on
NYSE/Nasdaq, from 2009 onward. Whether their statements build as cleanly as domestic ones is an
internal coverage measurement, not a question for him.

## Two layers: the display layer and the Disclosure Unifying Layer (2026-09-14)

Hicham's framing, and it generalises every naming decision made today into one architecture.

**Layer 1, display.** Never touch or tamper with how a company presents its financials or its KPIs.
This is the principle already recorded above, now stated as a layer rather than a rule about
statements: it governs line items, segment names and KPI names alike.

**Layer 2, the Disclosure Unifying Layer.** A mapping held underneath, never shown in place of the
company's words, that says which different names mean the same thing. It exists for compute and
query, not for display.

The worked example: a restaurant grows two ways, more revenue per existing restaurant and more
restaurants. The first is called Comps or Same Store Sales in the US, and Like for Like in the UK and
Europe. A user asking "what are the like-for-likes of restaurants in the UK versus the US" is asking
one question across three words. Layer 2 is what makes that answerable; layer 1 is what keeps each
company's page honest.

This is the same shape as the segmentation decision (company wording on the page, segmentation kind
tagged underneath) and the concept dictionary (tag plus dimension as the key). They are all layer 2.

**KPIs: leave as they are for now.** 59,755 company-invented tags in one quarter, in nearly every
filing. The work is not mapping names, it is understanding definitions, and that is its own data
engineering task. Deferred deliberately, not forgotten. It becomes load-bearing when we expand
beyond the US, because that is when the same concept starts carrying different words by country.

## Debt: its own page, and maturities resolved to real years (2026-09-14)

**Its own page.** Hicham wants debt structure as a page in its own right, not a line on a statement.

**Buckets become years.** Filings express maturities two ways: relative ("due within one year",
"year two") or absolute ("2027"). Both mean the same thing and we resolve both to the actual year.
For a filing with period end 2025-12-31, "within 12 months" is 2026, "year two" is 2027, "year
three" is 2028.

Two reasons, both his: an analyst thinks in years, not offsets; and a time series only works on
absolute years. Debt due in 2028, tracked across successive filings, rising is bad and falling is
good. That comparison is impossible if each filing's "year three" means a different year.

Consistent with the two layers: the company's own wording stays on the page, the resolved year is
the layer-2 value that makes query and time series work.

**The trap to get right.** The resolution is relative to the filing's own fiscal year end, not the
calendar. A June year end means "year two" is fiscal 2027, spanning mid-2026 to mid-2027, and
labelling it 2027 without saying "fiscal" would be wrong. Same class of mistake as reading a table
as thousands when it is millions: silent, and it makes the number useless.

## Store the filing documents; index the attachments, store them later (2026-09-14)

Hicham settled the exhibit question on trust rather than cost. The primary documents get stored now,
for all 433,717 filings we take numbers from, because the whole product rests on being able to show
the source of a number. A link to sec.gov is not evidence we control: links rot, the SEC
restructures, filings are occasionally withdrawn, and their availability is not ours to guarantee. If
we claim a number is what the company filed, we must hold the thing the company filed.

It is also the cheap half: roughly 1.3 TB, about 20 dollars a month, and about twelve hours of
fetching at the SEC's rate limit.

Attachments are deferred but indexed. Links to a filing's primary document are free today, because
the submissions data carries the filename and we already store the URL on every filing row. Knowing
what attachments exist requires one small request per filing, no download; doing that for the 433,717
gives a complete inventory in a few hours and stores nothing. The content follows when the compute
layer needs it, starting with the debt agreements.

Deferring costs no rework: the reader already looks in our storage first and falls back to fetching
live from the SEC, so filling the store later changes no code, it only makes pages faster. Filings
are immutable, so there is no window to miss.
