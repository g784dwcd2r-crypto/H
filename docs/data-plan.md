# The data plan

One plan, in order, covering everything settled with Hicham up to 2026-09-14. It supersedes nothing
— `integrity-plan.md` keeps the detail of the integrity work and `decisions.md` keeps the reasoning
behind each choice — but this is the running order, and it is the document to read first.

## The goal, and why it is the only goal

A person opens a company and every number on the page is exactly what that company filed: nothing
missing, nothing renamed, nothing invented, and the filing itself one click away underneath. We do
not audit the company; their accounts are audited already. We prove *our copy* is faithful.

Everything below is in service of that. A feature that cannot be trusted is worth less than no
feature, because the first wrong number a user catches costs every number that was right.

## The two principles everything hangs off

**1. Display: never touch the company's own presentation.** Their line labels, their statement order,
their segment names, their KPI names. Unless the user asks for something else, they see what the
company published.

**2. The Disclosure Unifying Layer: map underneath, never in place of.** A second layer that knows
"Comps", "Same Store Sales" and "Like for Like" are one thing, that a tag plus a dimension is one
identity, that "year two" on a December filer means 2027. It exists so the product can compute and
compare across companies. It is never shown instead of the company's words.

Every naming question we have hit — statement lines, segments, KPIs, debt buckets — is one of these
two layers. Ask which layer a question belongs to and the answer follows.

## Rule zero

Nothing the SEC publishes is dropped. Every row and every column of every source file is stored.
Where a stage needs a subset, it selects it at read time with a flag, never by leaving rows out at
load time. Every load records raw / loaded / repaired / rejected counts, and a reject is a bug to
fix, not a number to tolerate.

## Where we actually are (2026-09-14)

Held and verified:

- 8,394 listed companies; 433,717 filings; 70 quarters of the SEC data sets reloaded with every row
  and every column, including the `segments` column that carries dimensions.
- Statements rebuilt for 2026q2: 2,329,892 lines over 7,714 filings, of which **694,242 lines across
  5,733 companies carry a dimension** and would have been missing a week ago. Triumph Financial's
  noninterest income now adds to 19,707,000 against a reported 19,707,000; before the fix it showed
  2,800,000 under the same total.
- Arithmetic checks run per filing and now bridge discontinued operations and equity-method income,
  compare the same concept across statements, and refuse to divide one share class's earnings by
  another's share count.
- Company header fields, filer category (`1-LAF` / `2-ACC` / `4-NON`), and a JSON catch-all for any
  field the SEC adds later.

Known wrong or absent, in the order it hurts:

| Gap | Consequence today |
|---|---|
| The newest quarter has no dimensioned lines | The most recent filing of every company is thinner than the one before it |
| Line labels for a broken-out tag | We show the axis=member text where the company showed a phrase |
| No real calculation tree | We cannot prove a statement adds up; our parent guess is positional |
| No debt maturity schedule | 2 of 4,802 annual filings tag it; the rest is a table in the notes |
| Documents stored for one company | We claim a number is what was filed and cannot show the filing |

## The keystone: read the original filing

All five rows of that table are answered by one source, and only by that source. Inline XBRL carries
the presentation, the company's own labels, the dimensions, the calculation tree and the note tables,
and we have to fetch the document anyway because Hicham's trust rule requires holding it.

So this is one project, not five. It also upgrades the data sets from primary source to cross-check:
two independently built copies that agree is real evidence, unlike the companyfacts reconciliation
that shared our blind spot and reported 100 %.

Nothing else in this plan is as valuable. It comes first.

## Order of work

### Phase 1 — The filing reader (now)

1. **Parsers, no network.** The four linkbases a filing ships (`_lab`, `_pre`, `_cal`, `_def`) and the
   instance document. Out of them: the calculation tree with weights, the presentation order with
   preferred labels, the company's own label per line, and every fact with its full dimensional
   context. Pure functions over bytes, tested against fixtures.
2. **Fetch and store.** The primary document and its linkbases for the filings we take numbers from,
   into the lake beside the filing. ~1.3 TB, ~20 dollars a month, ~twelve hours at the SEC's rate
   limit. Attachments are indexed now (one small request per filing, nothing downloaded) and stored
   later when the compute layer needs them, starting with the debt agreements.
3. **Statements from the filing.** Where we hold the filing, build the statement from it and keep the
   data sets as the cross-check. Any disagreement between the two is a bug with a name.
4. **The subtotal check, for real.** With the actual calculation tree, `subtotal_equals_children`
   becomes the check that catches a missing line, a duplicated line and a sign error at once. My
   positional version flagged 98.3 % of filings and was worthless; this one is not a heuristic.

   *Done when:* the newest quarter carries dimensioned lines with the company's own labels, every
   statement we publish has been through the real calculation tree, and the filing behind any number
   opens from our own storage.

### Phase 2 — Coverage and applicability, company by company

No sampling. One row per company: filings held against the submissions feed, facts held against
companyfacts, statements per fiscal year, which checks ran, which passed, which never applied.
Grouped by tier (NYSE/Nasdaq, other listed, filing but unlisted, everything else) so the numbers stay
readable — a gap in the first tier is a bug, a gap in the last is usually a registrant that never
filed financials. Expected explanations (foreign private issuers, fresh IPOs, SPACs, companies gone
dark) are reported as reasons, not failures.

Gross profit is optional under US GAAP, so many income statements skip that check. Hicham put its
applicability at 70–80 %; we measure it. A company with **zero** applicable checks is getting no
verification at all, silently, and that count goes on the scorecard.

*Done when:* coverage and applicability per tier are on the scorecard and every shortfall has a named
reason or an open bug.

### Phase 3 — The remaining checks

1. Retained earnings roll forward: opening + net income − dividends − buybacks ± other = closing.
2. Earnings per share: net income available to common / weighted average shares, basic and diluted.
3. Periods chain: Q1 + Q2 + Q3 + Q4 = the year for flow items; nine months + Q4 = the year.
4. Cross-filing agreement: this year's annual figures equal the prior-year column of next year's
   report. A difference is a **restatement** — recorded, surfaced to the user as a notice, never
   reported as a failure.

Late filers come from the same table and are now a rule rather than a guess: filer category gives the
actual deadline (Large Accelerated 60 days annual / 40 quarterly, Accelerated 75, Non-accelerated 90),
and we hold the category for every company.

These are internal. Hicham was explicit: the checks are ours, not the reader's. They gate what we
publish and tell us where to look; they do not appear on the page as badges or scores.

*Done when:* each check has tests, runs over the whole universe, and its pass / fail / not-applicable
counts are on the scorecard with a named exception list.

### Phase 4 — The five disclosures, in Hicham's order

The statements are not the product on their own. After they are right, these five, in this order:

1. **Segmentation.** Already tagged and already in the lake — Apple's Americas 45.09 bn, Europe
   28.06 bn, Greater China 20.50 bn, 158,080 segment facts in one quarter. Company wording on the
   page; the segmentation kind (geography, product, sub-company, customer) tagged underneath.
2. **Debt schedule.** Its own page, not a line on a statement. Maturities resolved to real years —
   "year two" on a December 2025 filer is 2027 — because an analyst thinks in years and a time series
   only works on absolute ones. The trap: resolution is against the filing's own fiscal year end, so
   a June filer's "year two" is *fiscal* 2027 and must say so.
3. **Preferred equity and other hybrids.**
4. **Acquisitions.**
5. **KPIs.** Left exactly as companies state them for now. 59,755 company-invented tags in one
   quarter; the work is understanding definitions, not mapping names, and that is its own project.
   It becomes load-bearing when we go beyond the US.

The statement of changes in equity is explicitly *after* these five.

### Phase 5 — The dictionary

Two companies call the same thing by different names. We hold ~190 concepts in seed lists. The unit
of a dictionary entry is **(base tag, axis, member)**, never the tag alone: keyed on the tag alone it
would collapse Triumph's deposit fees, card income and general fee income into one number.

Measure before theorising. Both halves of a dimension are often standard — Triumph's three members
are all `us-gaap:`. Custom members cluster on the business-segment axis, where the member is a
division name. The first output is a table: per axis, how many distinct members, what share are
standard, how many companies use each. That number decides how much human mapping is really needed.

Three layers: the calculation tree from each filing (phase 1 gives us this), the FASB taxonomy's own
relationships for standard concepts, and a human mapping table — data, not code, editable without a
release — reviewed with Hicham.

### Phase 6 — Pre-2009, and the sector

No XBRL tags exist before ~2009. We do not parse generically across thousands of label variations;
we take a company's own dictionary, learned from its tagged filings, and apply it backwards to *its
own* older filings. A company is only ever matched to itself. Scope: listed companies, annual
reports, 2001 onwards, ~75,000 documents. Values derived this way are labelled as derived wherever
they appear. 2009 already reaches back to 2008 because the 2009 report carries the prior year.

Sector: SIC is not GICS and GICS is licensed. Use Hicham's list where he has one, SIC as fallback.

## Standing decisions this plan assumes

- Foreign-domiciled filers (20-F, 40-F) are **in scope**: they file under US regulation and a US
  investor can buy them. 2,020 in the lake, 1,363 listed.
- Dead filers are out of scope for now; a "companies no longer with us" explorer is a later,
  separate thing.
- The data-set lag is DERA's, not EDGAR's. EDGAR publishes immediately; the quarterly summary files
  arrive ~2 months after quarter end. Never tell a user "the SEC is late".
- Provisional periods (built from company facts because the data sets have not published yet) are
  labelled as provisional on the page, in the grid and in the Excel export, and stay labelled until
  filings are read directly.
- Live share prices add little; the share count that matters is the **ending period** count, not the
  weighted average the statements report, and basic and diluted are two different numbers.

## What is still with Hicham

- The list of core companies, and the sector for each.
- Whether attachments beyond the primary document ever get stored, and which.
- Ten minutes on the Excel export.
