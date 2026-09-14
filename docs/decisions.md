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

## A statement line is a concept plus its dimension (2026-09-14)

The builder took undimensioned values only, so a tag a company reported *only* broken out vanished
from the statement entirely. Measured on the reloaded lake: 46,672 presented lines in one quarter,
6.5 % of all lines, across 91 % of filings. On NYSE and Nasdaq, 32 % of filings lost income-statement
or cash-flow lines, Berkshire Hathaway among them.

The rule now: a line takes the **total** where the filing reports one; where it reports only the
breakdown, each member becomes its own line. `statements` gains a `segments` column carrying the
axis=member text, and a line's identity is concept plus segments. Two members under one presented tag
are two ordered lines, not one.

The company's own presentation label is left exactly as it is. The member sits in its own column, so
the display decision (how to render "Fee income" broken into three products) stays with the page and
nothing is renamed in the data. Faithful labels for those lines need the original filing, because the
data sets' `pre` table names the tag once, with one label, and never mentions the members.

Checks compare totals only (`segments = ''`). Without that guard, Erie Indemnity's Class A earnings
per share of 3.23 could be divided by Class B's 2,542 shares. Same failure as the Citigroup one fixed
this morning: a check that does not know what it is comparing.

## Five open problems converge on one thing: read the original filing (2026-09-14)

Verified on the rebuilt lake: 2026q2 carries 694,242 dimensioned statement lines across 5,733
companies. Triumph Financial's April filing is in that quarter and has its fee lines back. But its
July filing does not, because the SEC's data sets lag a quarter or two, so the newest filing for any
company is built the fallback way from company facts, which publishes undimensioned facts only.

That gap cannot be closed with anything we currently download. Nor can four other things:

| Open problem | Why the data sets cannot solve it |
|---|---|
| The newest quarter has no breakdown lines | The data sets have not published it yet |
| Faithful line labels for a broken-out tag | `pre` names the tag once, with one label, and never mentions the members |
| Proving a statement adds up | The calculation tree is dropped from the data sets; our parent guess is positional and unreliable |
| The debt maturity schedule | 2 of 4,802 annual filings tag it; the rest is a table in the notes |
| Holding the source of every number | Hicham's trust rule: if we took the data, we take the source |

All five are answered by the same source: the filing itself. Inline XBRL carries the presentation,
the labels, the dimensions, the calculation tree and the note tables, and fetching it is what
storing the document already requires. So this is one project, not five, and it moves the data sets
from primary source to cross-check — a strengthening, since two independently built sources that
agree is real evidence, unlike the company-facts reconciliation that shared our blind spot.

Meanwhile the gap is already disclosed rather than hidden: provisional periods carry a chip on the
company page and the statements grid, and the Excel export labels them "provisional (built from XBRL
facts; FSDS not yet published)". That stays until filings are read directly.

## Market data is parked until legal advice (2026-09-14)

Hicham asked for end-of-day price and market capitalisation. The data side is nearly solved: shares
outstanding are already in the lake from the filings, including the per-class split that market cap
needs for multi-class companies (Alphabet: Class A 5,824m, Class B 836m, Class C 5,456m, summing to
the reported 12,116m). Only the price is missing, and a price feed is about 20 euros a month with
the whole world included, roughly 21 API calls a month using a bulk endpoint, and pennies of
storage.

None of that is the deciding factor. The deciding factor is whether the vendor's agreement lets us
show their price to a paying subscriber, and that is a question for a lawyer, not for us.

So the whole market-data workstream is parked. No vendor is engaged, no key is obtained, and no
price data enters the lake until section 2 of `legal-questions.md` is answered.

Two things settled on the way, which stand whatever the lawyer says:

- **We buy prices only, never fundamentals.** Vendors compile financial statements by scraping
  announcements, news feeds and investor-relations pages. That is a copy of a copy, and it is the
  same reason we declined a FactSet login: if a vendor's number and the filing disagree, the filing
  is right, and we would have no way to show which is which. Filings we own end to end; prices we
  rent because we cannot add value to a closing price.
- **Building a price feed ourselves is a licensing project, not an engineering one.** The code is a
  file a day. The hard parts are the exchange agreements, which are what the vendor actually sells,
  and corporate-action adjustment, which is where the bugs live. At 20 euros a month the arithmetic
  is not close.

Also noted for the lawyer: the UK retains the EU database right and the US has no equivalent, so
extracting data from someone else's compilation is a bigger risk here than it would be in the US.
That makes the scraping route worse for a UK company, not better.

## Classify by how analysts cover a name, not by what a company sells (2026-09-14)

Commercial schemes classify a company by what it sells. We turn that around. We start from how
analysts actually cover a name, on the sell side and the buy side, make those the groups, and put
companies into them afterwards.

    Industrials > Transportation > Trucking > Brokers
    Industrials > Transportation > Trucking > LTL Carriers
    Industrials > Transportation > Trucking > TL Carriers
    Industrials > Transportation > Trucking > 3PL

Why this is worth something. An LTL carrier and a TL carrier both sell freight movement, so a
scheme based on products puts them together. But they have different cost structures, different
cycles, different questions and different analysts. You cannot work that out from the financials.
Nobody can rebuild it from public data. It is judgement, built up over time, and it is ours.

That also changes the licensing position. GICS is licensed, so we cannot use it. SIC is not a
research map. A classification we write ourselves, we own. That makes it worth something on its own,
and it needs a question in `legal-questions.md`: what do we own here, and what protects it.

**Two changes from Mbarek, both accepted.**

*Depth varies.* Four levels fits Transportation. It will not fit everywhere. Some areas need two,
some need five. So we store a tree with a parent pointer, not four fixed columns. Otherwise every
awkward case means changing the table.

*One main group, plus other memberships.* A diversified transport company belongs in both TL and
brokerage. An analyst needs to tell a focused operator apart from a big company with a small arm. So
a membership records whether it is the main one, and how big the exposure is.

**The tables.**

| Table | Holds |
|---|---|
| `classification` | node id, parent id, level, name, definition sentence, other names for search |
| `company_classification` | cik to node, main or not, exposure, who assigned it and when |
| `companies` | unchanged. SIC stays exactly as the SEC gives it |

The definition sentence matters. It is how someone reviews an assignment later, and it forces "3PL"
to mean one thing instead of covering brokerage, warehousing and anything else logistics-shaped.

This is layer 2, the Disclosure Unifying Layer: held underneath, never shown instead of the
company's own words, and editable as data rather than code. It replaces the old line in the data
plan that said to use SIC as a fallback.

**Transportation first.** Write the groups, write a definition sentence for each, put in a few dozen
companies we know. The obvious test is whether the expected peers come back. The better test: write
down the companies that are hard to place *before* placing them, then see if the structure handles
them. Any scheme handles the easy cases.

**Two warnings.** Do not merge this with the coverage tiers. Tiers measure whether our data is
complete. This helps people navigate. One field doing both does neither well. And we can help assign
companies, but the groups and the hard calls are human, and someone has to keep reviewing them as
companies change.

## Coverage beyond the US is a source problem, one region at a time (2026-09-14)

We are gathering a company list for the US, Canada and Europe, with AUS/NZ later.

Our data is SEC only. So today "Europe" and "Canada" means the 2,020 foreign companies that file
with the SEC (forms 20-F and 40-F), 1,363 of them listed. Real coverage of those countries means a
new source for each one, not a longer list.

The order is not the obvious one:

- **Europe is easiest.** European annual reports are filed as inline XBRL, the same format our
  filing reader already handles. So Europe is a question of getting the files, not of reading them.
- **Canada is harder than it looks.** Filings go through SEDAR+, and Canada never required XBRL
  widely. So it likely means working with documents, not tagged data.
- **AUS/NZ looks like Canada**, not like Europe.

Each needs confirming before we promise dates, but the order is unlikely to change.

One thing to do now: the list should carry an ID that works across countries, such as ISIN or LEI.
A ticker does not. We already store LEI where the SEC gives it.

## Three scope calls settled (2026-09-14, evening)

Three questions the step plan had left open were answered directly.

**Exhibits: store everything.** Not only the primary document and not only debt agreements — every
exhibit, every form, all the way back. Same principle as the primary documents, extended: if we
point at a filing as evidence, we hold the whole filing rather than the part we happened to want.
Debt agreements are still fetched first because the debt page needs them, but that is sequencing, not
scope. This supersedes the "attachments deferred, stored later" half of the 2026-09-14 documents
decision; the deferral was a scope question, and the scope is now "all of it".

One thing to size before running it, not a decision but a number: every exhibit across 433,717
filings is several times the ~1.3 TB the primary documents take. Storage is cheap, but the figure
should be produced and budgeted before the download starts rather than found halfway through.

**Ownership history: collect all of it.** The full history for all three flows (insiders,
institutions, beneficial ownership), not a chosen number of years. A person's or a fund's behaviour
over many years is what makes ownership worth having, so we take the lot rather than draw a line and
regret it. The collector already supports this through its separate catch-up cursor; it is a matter
of letting it run against older dates.

**Classification: Hicham is doing the groups.** The method was settled earlier (buckets from how
analysts cover a name, a tree with variable depth, a primary home plus memberships, a definition
sentence per node, Transportation as the pilot). The groups themselves and the hard placements are
Hicham's, and he is working on them now. We can suggest placements from the filings; the boundaries
and the difficult calls wait on him, not on us.

## Step 1 built: measure the flat tolerance before changing it (2026-09-14, evening)

`filings-hub check-tolerance` (in `filings_hub/ingest/check_tolerance.py`) is the first piece of the
data plan built rather than planned. It reads `statement_checks` and reports how close the passing
checks sit to the tolerance line, so we learn whether the flat 0.5 % is hiding real breaks before
committing to the per-line fix (step 9).

Three choices worth recording:

- **The band edges come from the real tolerance constants**, imported from `checks.py`, not copied.
  If the tolerance ever changes, the measurement follows it; it can never quietly drift from the
  thing it measures.
- **Two pass regimes are kept apart.** A check on tiny numbers passes on the 1.0 absolute floor, not
  the relative tolerance, so its relative gap is meaningless. Those are reported separately from the
  passes the 0.5 % actually governs, so the near-miss share is honest.
- **EPS is measured on its own 1 % line**, not folded in with the 0.5 % checks.

It is read-only and tested against controlled rows with known gaps plus the real built lake. The
verdict is a heuristic to guide a human (near-miss share over 1 % of governed passes -> prioritise
step 9), not an automated decision. Still to do: run it against the full lake once the current
rebuild finishes uploading, and read the number.

## Step 2 built: a reused ticker resolves to its current owner (2026-09-14, evening)

Seven symbols were each claimed by two companies, so a lookup could land on a delisted one. Fixed at
build time rather than per query: `mark_current_owner` marks one `is_current` owner per symbol in the
tickers table, ranked by still-filing, then most recent, then most filings, then a stable CIK. A
symbol with a single owner is current even when that owner is defunct — we never drop the history.

Why build-time and not just a smarter query: the tie-break is the same everywhere a symbol becomes a
company (the exact-ticker redirect, search, the CLI, verify). Marking it once keeps each of those a
plain filter (`is_current IS NOT FALSE`, or `ORDER BY (is_current IS TRUE) DESC`) that reads the same
and cannot drift between call sites. The queries use `IS NOT FALSE` / `IS TRUE` so a lake not yet
rebuilt with the column behaves exactly as before rather than breaking.

The redundant `companies WHERE ticker = ?` branch in search was removed: `companies.ticker` is copied
from the company's own `is_primary` tickers row, so the tickers branch already covers it, and keeping
it would have re-surfaced the dead company that the `is_current` filter is there to hide.

Migration `0020` adds the column; the serving load carries it. Requires a universe rebuild to take
effect, which every backfill and daily refresh already does.

## Step 3 built: the subtotal grouping is labelled a guess, not hidden or overclaimed (2026-09-14, evening)

The columns that say which line rolls into which total (`parent_concept`, `is_subtotal`) are a
positional guess: the SEC summary data sets drop the filing's calculation tree, so we assume each
line rolls into the next subtotal below it. Two things were true and both mattered.

- **There was no check to switch off.** A positional `subtotal_equals_children` was never wired in
  (it would have flagged 98.3 % of filings); the guessed columns only feed display. So the work was
  not "stop running the check" but "stop presenting the guess as fact".
- **The guess reaches a person in two places only:** the grid payload the export/API emits, and the
  Excel workbook. The web does not read these columns. So both exposure points now carry a plain note
  that the grouping is inferred from presentation order, not the filing's own arithmetic, and is
  provisional. `LINE_GROUPING_BASIS` in `grid.py` ships in the payload beside `availability_basis`;
  the Excel methodology note says the same, whatever the subtotals mode.

Deliberately not done: no new stored column and no migration. Every parent guess is positional today,
so a per-row provenance marker buys nothing until step 8 mixes real calculation-tree parents in with
guesses; adding it now would be schema churn for a uniform state. A guard comment on `assign_parents`
records that it must never back a pass/fail check until the tree is read from the filing (step 8),
which is when a subtotal check becomes meaningful.

## Step 4 built: coverage and applicability, company by company (2026-09-14, evening)

`filings-hub coverage-audit` (`coverage_audit.py`) answers "what should we hold, and where does it
differ from what we do". It is the fourth and last of the start-now fixes, and the one that finds the
weaknesses we have not noticed yet, so it earns being built before the filing-download work.

Choices worth recording:

- **Tiered, because a gap means different things by tier.** NYSE/Nasdaq, other listed, filing but
  unlisted, everything else. A gap in the first tier is a bug; a gap in the last is usually a shell
  that never filed accounts. The report never calls an expected-absence a failure: a company that
  filed no financial report is not counted as missing statements.
- **The headline is companies getting zero checks.** A company whose filings never trip an arithmetic
  check is unverified and nothing said so before. The count is on the report, per tier and in total.
- **Gaps carry a reason or a flag.** Foreign filer (20-F / 40-F), gone dark, blank-check / SPAC, or
  "unexplained — investigate". The unexplained ones in the top two tiers are the actionable list.
- **Aggregated in SQL, not row-by-row in Python**, so it scales to the whole ~900k-company universe;
  only the bounded sample of unexplained gaps is pulled out. It reads through `Duck` directly with
  typed empty stand-ins for absent tables, rather than `Database`, so it never drags in the serving
  views (periods_serving and the rest) it does not need.

Read-only and internal: it gates what we publish and tells us where to look, never shown to a user.
Still to do: run it on the full lake and work the gap list.

## Step 1 result: the flat tolerance is fine; step 9 deferred (2026-09-14, evening)

`check-tolerance` ran on the full local lake: 2,047,964 checks. Of the 1,502,846 standard passes the
0.5 % tolerance governs, 99.48 % are exact and 711 (0.05 %) are near misses. That is the answer step 1
existed to get: the flat tolerance is not waving real breaks through, so **step 9 (a per-line
tolerance from the filing's own `decimals`) is deferred** — low value now, and it needs the filing
download (step 6) to have the `decimals` anyway.

EPS near misses are higher (1.90 % of the 87,271 EPS passes governed by the 1 % rule), but EPS is
printed to the cent, so a 1 % band on a low share price is a couple of cents of ordinary rounding.
Noted, not acted on.

The signal worth chasing is elsewhere: ~8-9 % of checks *fail* (130,402 standard, 58,838 EPS), and
most standard fails are more than 10x past the line — genuine non-reconciliation, not tolerance. That
is coverage-audit (step 4) and calculation-tree (step 8) territory, not step 1's.
