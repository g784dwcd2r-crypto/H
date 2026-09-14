# Data integrity plan for the core universe

Goal, in one sentence: a user who opens any of the core US companies can trust that every number on
the page is exactly what the company filed with the SEC, nothing missing, nothing changed, nothing
duplicated. We take the company's own accounts as correct (audited); the work is proving our copy.

This follows the points Hicham raised on 14 September, in his order. Each step says what exists,
what we build, and what "done" looks like. Steps 1 to 4 need nothing from anyone and start now.
Steps 5 to 7 need Hicham's list and his review.

## What "complete" means, corrected 2026-09-14

The first version of this plan measured completeness as "do we hold the filing". That is too weak.
Triumph Financial (TFIN) shows why: its quarterly income statement presents three fee lines that
share one base tag, `RevenueFromContractWithCustomerExcludingAssessedTax`, and are told apart only
by a product/service dimension (`DepositAccountMember`, `CreditAndDebitCardMember`,
`FinancialServiceMember`). Our builder took undimensioned rows only, so all three vanished. The
published statement shows noninterest income lines summing to 1,961,000 under a reported total of
21,415,000: a hole of 19,454,000, which is those three lines to the dollar, 91 % of the section.

So completeness is per line, not per filing: **every line the company presented, with the value it
presented, is on the page.** In XBRL the unit of identity is the base tag PLUS its dimensional
context, never the base tag alone.

This also exposes a blind spot in how we validated. The notebook reconciled our statements against
the SEC's companyfacts and reported 100 % agreement. Companyfacts publishes undimensioned facts
only, so a line that exists solely with a dimension is absent from both sides and can never show up
as a difference. Agreement between two sources that share the same blind spot is not evidence. The
only source carrying these lines is the data sets' `num` table with its `segments` column, which we
started storing on 2026-09-14 and which fills on the next reload.

## Rule zero: nothing the SEC publishes is dropped

Every row and every column of every source file is stored. Where a stage needs a subset (the
statements builder uses line totals, not segment breakdowns), the subset is selected at read
time with a flag, never by leaving rows out at load time. Every load records raw, loaded,
repaired and rejected counts, and a reject is a bug to fix, not a number to tolerate.

## The universe

Our lake holds 8,394 listed companies (the same count Hicham quoted): 3,480 on Nasdaq, 2,625 on
NYSE, 1,974 OTC, 22 CBOE, 293 with no exchange recorded. Of the 6,105 NYSE/Nasdaq names, 284 are
blank-check SPACs and 406 have no SIC code.

The work runs over every company in the lake, not a cutoff. Reports are grouped by tier so the
numbers stay readable: listed on NYSE or Nasdaq; other listed (OTC, CBOE); not listed but filing
financial statements; everything else (funds, trusts, insiders, defunct registrants). A gap in the
first tier is a bug; a gap in the last is usually a registrant that never filed financials.

## Step 0. Restore the lines we are dropping (first, it is a live defect)

Not future work: what we publish today is wrong for any company that breaks a statement section out
by dimension. Banks (fee income by product), insurers, REITs and anyone using the product/service or
geography axis are exposed.

1. Reload the data sets so `segments` and the `dimensional` flag exist (`filings-hub fsds --all` on
   the machine holding the raw zips, then sync `fsds/`).
2. Decide presentation per filing. The `pre` table names a tag once per line with no dimension, so
   where a tag has no undimensioned value but does have dimensioned ones, the presented lines are
   the dimensioned set. Where both exist, the undimensioned value is the line and the dimensioned
   ones are its breakdown.
3. Rebuild statements. Keep the company's own label per line; carry axis and member on the row so a
   breakdown can be shown or hidden.
4. Gate on the subtotal check below: TFIN's noninterest income must add up after the rebuild.

Done when: no filing in the core sample presents a subtotal its own displayed lines do not reach,
and TFIN's three fee lines appear with their labels and values.

## Step 1. Coverage, company by company

No sampling. For every core company: filings held vs the SEC submissions feed, XBRL facts held vs
the companyfacts API, statements built per fiscal year, periods, a metrics row. Output: one row per
company with counts and a status, plus a named list of every company that falls short and why.

Expected explanations for a gap, reported as such rather than as failures: foreign private issuers
(20-F / 40-F, IFRS), fresh IPOs, SPACs, companies that went dark.

Done when: coverage percentage per tier is on the notebook scorecard and every gap has a named
reason or an open bug.

## Step 2. Which checks actually applied

Our five arithmetic checks (balance sheet balances, gross profit, operating income, income after
tax, change in cash) only run when every line they need is present. Under US GAAP gross profit is
optional, so many income statements skip it. A company with no applicable check gets no
verification at all, silently.

Build: per company and fiscal year, which checks ran, which passed, which never applied. Count the
companies with zero applicable checks. Report the gross-profit applicability rate against Hicham's
70 to 80 percent estimate.

Done when: the number of core companies with no applicable check is known and on the scorecard.

## Step 3. More checks

**First, the detector.** `subtotal_equals_children`: every subtotal equals the sum of the lines that
roll into it. The statements table already records each line's parent, so this runs today and it is
the check that catches a missing line, a duplicated line and a sign error at once. It would have
found TFIN immediately. Everything else in this step is secondary to it.

**Then the rest.**

Added to `filings_hub/ingest/checks.py`, stored in `statement_checks` like the existing ones, so
they run on every future filing too.

1. Net income agrees across statements: IS = CF (first line), comparing the same concept on both.
   Done 2026-09-14, with the ending-cash tie between CF and BS.
2. Retained earnings roll forward: opening + net income - dividends - buybacks charged to retained
   earnings +/- other movements on the equity statement = closing.
3. Earnings per share: net income available to common / weighted average shares = reported EPS,
   basic and diluted, within rounding.
4. Periods chain: Q1 + Q2 + Q3 + Q4 = fiscal year for flow items; nine months + Q4 = year.
5. Cross-filing agreement: this year's annual figures equal the prior-year column of next year's
   report. A difference is a restatement, recorded, not a failure (feeds step 5).

Done when: each check has tests, runs on the core universe, and its pass / fail / not-applicable
counts are on the scorecard with a named list of failures.

## Step 4. Late filers and companies that went dark

From the filings table: a gap of more than 15 months between annual reports, or more than 5 months
between quarterly reports, is flagged with the dates. Catch-up filings (two years filed in one go)
are recognised from filing dates.

Done when: the flagged list exists and the company page can show a notice.

## Step 5. Restatements

We already keep every original filing and the statements grid has an "as filed" versus "restated"
toggle. Missing: telling the user. Build, from check 5 above: a `restated_by` marker on the affected
periods, an info line on the company page ("2022 and earlier are pre-restatement, restated in the
2025 annual report"), and later the effect on earnings, line by line, from the two copies we hold.

Done when: the notice shows for a known restated company and the numbers behind it are queryable.

## Step 6. The dictionary (the big one)

Two companies call the same thing by different names. We hold about 190 concepts in short lists
that sort lines into statements and pick revenue, cost, tax and cash flow lines. That is a seed.

**The unit is the tag plus its dimension.** A dictionary keyed on the base tag alone would collapse
TFIN's deposit fees, card income and general fee income into one number. Each entry is therefore
(base tag, axis, member).

**Measure before theorising.** Both halves of a dimension can be standard: TFIN's three members are
all `us-gaap:`, defined by the taxonomy, not invented. Custom members cluster on the business
segment axis, where the member is a division name. Once the reload lands, the first output of this
step is a table: per axis, how many distinct members, what share are standard, and how many
companies use each. That number decides how much human mapping is actually required, and it may
well support the view that the edge cases fall into a handful of types.

Build, in three layers:

1. **From the filings.** Every XBRL filing ships its own calculation tree in which the company
   declares what each line adds into (e.g. its custom "claims authorized on vehicle service
   agreements" rolls into cost of revenue). The SEC flat data sets drop this tree, our lake does not
   have it yet. Pull it for the core companies and store concept -> parent per filing. Measure how
   many custom lines it explains.
2. **From the taxonomy.** The FASB US GAAP taxonomy publishes standard parent-child relationships
   for its own concepts. Load them for the standard lines.
3. **Human layer.** What remains, plus the grouping above "tree" ("flora", "nature"): a mapping table
   of standard line -> group -> section, reviewed with Hicham. The table is data, not code, so it can
   be edited without a release.

Done when: for the core universe, the share of statement lines mapped to a standard line and group is
on the scorecard, and the unmapped lines are listed by frequency for review.

## Step 7. Sector and KPIs

SEC SIC codes are not GICS, and GICS is licensed. Use the sector in Hicham's list; fall back to SIC.
Business-specific KPIs and divisional segments are a later phase, after the dictionary.

## Reporting

`notebooks/data_validation.ipynb` becomes the core-universe report: one section per step above,
each with counts, charts, the named exception list and a plain-English interpretation. It is re-run
after every refresh.

## Order of work

| Step | Needs | Starts |
|---|---|---|
| Universe table (proxy) | nothing | now |
| 1 Coverage | universe | now |
| 2 Check applicability | universe | now |
| 3 Five new checks | nothing | now |
| 4 Late filers | nothing | now |
| 5 Restatement notice | check 5 | after step 3 |
| 6 Dictionary layers 1 and 2 | universe | after step 1 |
| 6 Dictionary layer 3 | Hicham's review | when ready |
| 7 Sector | Hicham's list | when ready |
