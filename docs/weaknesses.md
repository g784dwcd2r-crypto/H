# What is broken in our data, and how we fix it

Written on 2026-09-14 by reading the code, not from memory. Every item was checked against the file
it names. Each one says what is wrong, how we fix it, and how we would know the fix worked.

Ordered by damage. That is not the same as how hard it is to fix.

| # | Problem | Fix | When |
|---|---|---|---|
| 1 | The newest filing uses our weakest method | Read the original filing | Phase 1 |
| 2 | We guess which line adds into which | Stop publishing the guess, then use the real tree | Now, then phase 1 |
| 3 | Error tolerance is a flat 0.5 % | Measure what it hides, then use the filing's own precision | Now, then phase 1 |
| 4 | Coverage is not measured | Per-company audit over the whole lake | Now |
| 5 | Restatements are not marked | Cross-filing check, then a notice | After the check |
| 6 | Statement files are never merged | A merge pass | Only if it hurts |
| 7 | The reader has only seen fake filings | Test it on ~20 real ones | Before the big download |
| 8 | Four smaller issues | One each, below | Ticker bug now |

## 1. The newest filing uses our weakest method

The SEC's quarterly data files arrive one or two quarters late. So for the newest filing of every
company we fall back to a second method (`build_fallback_rows` in `sync_statements.py`).

That method has two problems. It uses company facts, which publishes only totals, not breakdowns.
And it copies line order and labels from the company's previous filing, which may be out of date.

So the page people are most likely to open is built from the thinnest data. We do label these numbers
as provisional everywhere, which is honest. It is still our weak spot in the busiest place.

**Fix.** No separate work. This is phase 1: download the filings and build statements from them.

**How we know it worked.** Take a company whose newest quarter is provisional today. After the fix,
its newest filing has breakdown lines with the company's own labels. And the quarter before it, which
the SEC data files do cover, matches what we built from those files.

**Size.** Big. It is the main project.

## 2. We guess which line adds into which

`checks.assign_parents` decides a line's parent by looking down the list for the next subtotal. It is
pure position. It knows nothing about what the company said adds into what. Finding a subtotal is
also a guess: `checks.is_subtotal` uses a list of known concepts plus a pattern match on the label.

A guess on top of a guess gives what we measured: it flagged **98.3 % of filings**. That is not a
result, it is a broken tool. Today we cannot prove any statement adds up, and we publish
`is_subtotal` and `parent_concept` columns that look like we can.

**One thing is safer than it looks.** The Excel export only writes a `SUM()` formula when the guessed
children really do add up to the total, within 1 unit (`_adds_up` in `export/excel.py`). Otherwise it
writes plain values. So a bad guess degrades quietly instead of shipping a wrong formula to a
customer. The damage is to the checks and to how authoritative the data looks, not to exports.

**Fix now, no download needed.** Stop treating the guess as fact. Do not run a subtotal check off it,
and mark `parent_concept` and `is_subtotal` as derived wherever we expose them.

**Real fix.** Take the parent from the company's own `_cal` file, with its sign.
`xbrl.calculation_children` already returns this and nothing uses it yet.

**How we know it worked.** The failure rate drops from 98.3 % to something small, and every remaining
failure is worth opening. That is the test: not that failures reach zero, but that they become
readable.

**Size.** Small now. The rest rides on phase 1.

## 3. Error tolerance is a flat 0.5 %

`checks.py` sets `RELATIVE_TOLERANCE = 0.005` and `ABSOLUTE_TOLERANCE = 1.0`, and every check uses
them. On a 400 bn balance sheet, 0.5 % is 2 bn of slack. A real error fits inside that easily.

XBRL filings carry a `decimals` value on every number. That is the company saying how precise it is:
"-6" means they rounded to millions. Our tolerance should come from that, not from a constant we
picked. Our reader keeps it (`xbrl.Fact.decimals`), but the SEC's data files do not publish it, and
neither our facts table nor our statements table has the column. So it never reaches a check.

**Fix now.** One query. We already store both sides of every check and the difference. Look at how
close the passes are. If nearly all are exact, the flat tolerance is harmless in practice. If there
is a cluster sitting just under 0.5 %, we have a real problem. An hour of work, and it tells us
whether this is urgent.

**Real fix.** Carry `decimals` from the filing into facts and statements, and set the tolerance per
line from it.

**How we know it worked.** A company that rounds to millions gets about half a million of slack on a
subtotal. A company reporting to the dollar gets about a dollar. Today both get 0.5 %.

**Size.** The measurement is an hour. The real fix rides on phase 1.

## 4. Coverage is not measured

We have no list of which companies should be complete. So we can say what we **have** (8,394 listed
companies, 433,717 filings, 70 quarters) but not what we **should** have. A company whose filings
produce no applicable checks is getting no verification at all, silently, and we cannot count those
companies today.

This is the most important one structurally. Everything else here is something we happened to notice.
We are fixing what caught our eye.

**Not to be confused with `coverage.py`.** That is a public summary built from serving data: totals
only, no per-company detail, and it switches off on the remote lake because it would scan everything.
What we need is an internal audit, run offline over the lake.

**Fix.** Build the universe table with a tier per company — every company, not a top 4,000. Then one
row per company: filings we hold against the SEC's list, facts held, statements per year, which
checks ran, which passed, which never applied. Group by tier. Report the expected explanations
(foreign filer, recent IPO, SPAC, gone dark) as reasons, not failures.

**How we know it worked.** Every gap in the top tier has a named reason or a bug number. And the
count of companies getting zero applicable checks is on the report, because that is the silent case.

**Size.** Medium. Nothing blocks it. It scans the whole lake, which is what makes item 6 relevant.

## 5. Restatements are not marked

`periods` stores the amendment accession numbers, but `results_accession` still points at the
original filing. The fallback path skips amendments entirely
(`sync_statements.fill_fallbacks_for_cik`).

So when a company restates, the new figures may be in `statements` while the period still points at
the old ones, and nothing tells the user the number moved. This is the worst kind of wrong, because
the user has no reason to doubt it.

A restatement is not a failure. It is real information about the company, and it should appear as a
notice.

**Fix.** The cross-filing check first: this year's annual figures against next year's prior-year
column. Where they differ, record what restated what, then show a notice on the company page.

**One thing to be careful about.** A difference might be our own error, not a restatement. So only
trust it where we hold both filings and both parsed cleanly. Otherwise we would announce a
restatement that never happened.

**How we know it worked.** A company we know restated shows the notice, and the numbers behind it can
be queried.

**Size.** The check is part of step 3. The marker and notice are small after that.

## 6. Statement files are never merged

We merge files for the `filings` table (`compact_filings`), but not for statements. Statements are
written per company per quarter, so 70 quarters across 8,394 companies gives roughly half a million
small files. It grows every quarter.

Splitting by company is what makes a single company page cheap, and that was the right call. But any
full scan of the lake pays a cost per file, and nothing stops the count rising.

**Fix.** A merge pass, the same shape as the one for filings: read a company's statement files, write
one sorted file, delete the old ones. Same for `statement_checks`.

**When.** Only if the coverage audit turns out slow. Measure first, do not pre-optimise.

**How we know it worked.** The audit runs in a sensible time and the file count stops growing per
quarter.

**Size.** Small.

## 7. The reader has only seen fake filings

`filings_hub/testing/xbrl_fixtures.py` is made up. It is shaped like a real filing and modelled on
Triumph Financial, but we wrote it. All 14 tests in `tests/test_xbrl.py` run against invented XML.

Real filings are messier: odd namespaces, broken linkbases, files named off an unexpected base, older
filings whose instance file has no clear suffix. We handled the cases we could think of. We will find
out about the rest when we fetch real documents, and we should expect to find some.

**Fix.** Fetch about 20 real filings, chosen to be awkward on purpose:

- Triumph Financial, for the broken-out fee lines we already know about.
- Berkshire Hathaway, because it is huge.
- Citigroup, for discontinued operations and equity-method income.
- A 20-F and a 40-F, for foreign filers.
- One from 2009 or 2010, before inline filing, where the instance file has no clear suffix.
- A small filer with many custom tags.

Run the reader over them, write down what breaks, and keep them as test fixtures.

**How we know it worked.** All 20 parse. The file picker finds the right files in all 20 without
guessing. And for at least one, the calculation tree matches the statement as printed.

**Size.** About a day, a few hundred requests. Do it before the twelve-hour download, not after.

## 8. Four smaller issues

**Seven tickers point at two companies each.** The cause is almost certainly a symbol reused after a
company delisted. Our key is company-plus-ticker, so nothing stops two companies claiming one symbol.
*Fix:* when a symbol has two owners, search and routing pick the one still filing; keep the other in
the table as history. *Test:* the seven cases each resolve to the live company, and search never
shows two. *Size:* small, do it now.

**Co-registrant rows are dropped from statements.** `sync_statements` selects `coreg IS NULL`. The
rows are still in the raw data, so nothing is lost, but a jointly-filed statement loses lines.
*Fix:* count first — one query tells us how many filings have them and which companies. Then decide,
because if a company printed those lines, leaving them out breaks the display rule.

**One database connection, used one query at a time.** Needed, because two queries at once on the
same connection can mix one query's columns with another's rows. But it caps how much the server can
handle. *Fix:* leave it. If the server gets slow, use a few connections instead of one. Not a
redesign.

**Serving tables are replaced one at a time.** Each replacement is safe on its own and two loaders
cannot overlap, but the tables are not swapped as a set, so someone reading mid-load can see one
table updated and another not. *Fix:* only if someone actually sees a half-loaded page. Then load
into new tables and rename them together.

## The pattern

Problems 1, 2, 3 and 7 have one cause: **we read the SEC's summary of a filing instead of the
filing.** Four problems, one fix. That is why the filing work comes first.

Problems 4, 5 and 6 are separate and survive that fix. Problem 4, the coverage audit, does not wait
its turn behind the filing work: it needs nothing and runs in parallel from the start, because it is
how we learn which of the others actually matters.

## What to do first

Four things need nothing from anyone:

1. **The tolerance measurement** (item 3). An hour, and it might change the order of everything else.
2. **The ticker bug** (item 8). Users are being sent to the wrong company.
3. **Demote the parent guess** (item 2). Stop showing a guess as fact.
4. **The coverage audit** (item 4). The biggest of the four, and nothing blocks it.

Then: test the reader on real filings, download and store them, build statements from them, and run
the real subtotal check.

## Deliberately not on this list

- **We store numbers as doubles.** That is what the SEC publishes. A more precise type would suggest
  accuracy we do not have.
- **Postgres can be deleted.** It is a copy we rebuild from the lake. That is the design.
- **Provisional labels.** They are a symptom of problem 1, and they are shown everywhere they apply.
  The weakness is the thin data, not the label.
