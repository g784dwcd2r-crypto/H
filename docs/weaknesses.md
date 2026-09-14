# What is broken in our data

Written on 2026-09-14 by reading the code, not from memory. Every item below was checked against the
file it names.

Ordered by how much damage it does. That is not the same as how hard it is to fix.

| # | Problem | Damage |
|---|---|---|
| 1 | The newest filing uses our weakest method | The most-read page is the least complete |
| 2 | We guess which line adds into which | We cannot prove a statement adds up |
| 3 | Error tolerance is a flat 0.5 % | Real errors hide inside it |
| 4 | Coverage is not measured | We do not know what we are missing |
| 5 | Restatements are not marked | A number changes and nothing says so |
| 6 | Statement files are never merged | ~500,000 small files, growing each quarter |
| 7 | The filing reader has only seen fake filings | We do not know how it handles real ones |
| 8 | Four smaller issues | See below |

## 1. The newest filing uses our weakest method

The SEC's quarterly data files arrive one or two quarters late. So for the newest filing of every
company we fall back to a second method (`build_fallback_rows` in `sync_statements.py`).

That method has two problems. It uses company facts, which only publishes totals, not breakdowns.
And it copies the line order and labels from the company's previous filing, which may be out of date.

So the page people are most likely to open is built from the thinnest data.

We do label these numbers as provisional everywhere they appear, which is honest. It is still our
weak spot sitting in the busiest place.

**Fix:** read the original filing. Phase 1 of the data plan.

## 2. We guess which line adds into which

`checks.assign_parents` decides a line's parent by looking down the list for the next subtotal. It is
pure position. It knows nothing about what the company said adds into what.

Finding a subtotal is also a guess: `checks.is_subtotal` uses a list of known concepts plus a pattern
match on the label.

A guess on top of a guess gives what we measured: it flagged **98.3 % of filings**. That is not a
result, it is a broken tool. Today we cannot prove any statement adds up, and we publish
`is_subtotal` and `parent_concept` columns that look like we can.

**Fix now, no download needed:** stop publishing the guess as fact. Either drop those two columns or
mark them clearly as derived, and do not run a subtotal check until we have the real answer.

**Real fix:** the calculation tree, which `xbrl.calculation_children` already returns and nothing
uses yet.

## 3. Error tolerance is a flat 0.5 %

`checks.py` sets `RELATIVE_TOLERANCE = 0.005` and `ABSOLUTE_TOLERANCE = 1.0`. Every check uses them.

On a 400 bn balance sheet, 0.5 % is 2 bn of slack. A real error fits inside that easily.

XBRL filings carry a `decimals` value on every number. That is the company saying how precise the
number is: "-6" means they rounded to millions. Our tolerance should come from that, not from a
constant we picked.

Our new reader keeps it (`xbrl.Fact.decimals`). But the SEC's data files do not publish it, and
neither our facts table nor our statements table has the column. So it never reaches a check.

**Fix now:** we already store both sides of every check and the difference. Measure how many passes
sit close to the 0.5 % line. That tells us how much is hiding before we build anything.

**Real fix:** carry `decimals` through from the filing and set the tolerance per line.

## 4. Coverage is not measured

We have no list of which companies should be complete. So we can say what we **have** (8,394 listed
companies, 433,717 filings, 70 quarters) but not what we **should** have.

A company whose filings produce no applicable checks is getting no verification at all, silently. We
cannot count those companies today.

This is the most important one structurally. Everything else on this list is something we happened to
notice. We are fixing what caught our eye.

**Fix:** phases 2 and 3 of the data plan. The proxy universe is enough to start; Hicham's list
improves it later.

## 5. Restatements are not marked

`periods` stores the amendment accession numbers, but `results_accession` still points at the
original filing. The fallback path skips amendments entirely
(`sync_statements.fill_fallbacks_for_cik`).

So when a company restates, the new figures may be in `statements` while the period still points at
the old ones, and nothing tells the user the number moved.

This is the worst kind of wrong, because the user has no reason to doubt it.

A restatement is not a failure. It is real information about the company, and it should appear as a
notice.

**Fix:** the restatement marker and company-page notice. Needs the cross-filing check first.

## 6. Statement files are never merged

We merge files for the `filings` table (`compact_filings`), but not for statements. Statements are
written per company per quarter, so 70 quarters across 8,394 companies gives roughly half a million
small files. It grows every quarter.

Splitting by company is what makes a single company page cheap, and that was the right call. But any
full scan of the lake pays a cost per file, and nothing stops the count rising.

**Fix:** a merge pass for `statements` and `statement_checks`, like the one for filings. Only worth
doing if the coverage work turns out to be slow.

## 7. The filing reader has only seen fake filings

`filings_hub/testing/xbrl_fixtures.py` is made up. It is shaped like a real filing and modelled on
Triumph Financial, but we wrote it. All 14 tests in `tests/test_xbrl.py` run against invented XML.

Real filings are messier: odd namespaces, broken linkbases, files named off an unexpected base, older
filings whose instance file has no clear suffix. We handled the cases we could think of. We will find
out about the rest when we fetch real documents, and we should expect to find some.

**Fix:** fetch about 20 real filings first, chosen to be awkward. Check the reader against them and
keep them as test fixtures. Then do the full download.

## 8. Four smaller issues

- **Co-registrant rows are dropped from statements.** `sync_statements` selects `coreg IS NULL`. The
  rows are still in the raw data, so nothing is lost, but a jointly-filed statement loses lines.
  Count how many filings this affects before deciding anything.
- **Seven tickers point at two companies each.** A known bug. It can send a user to the wrong company
  from search. Fix it.
- **One database connection, used one query at a time.** Needed, because two queries at once on the
  same connection can mix one query's columns with another's rows. But it caps how much the server
  can handle.
- **Serving tables are replaced one at a time.** Each replacement is safe on its own and two loaders
  cannot overlap. But the tables are not swapped as a set, so someone reading mid-load can see one
  table updated and another not.

## The pattern

Problems 1, 2, 3 and 7 have one cause: **we read the SEC's summary of a filing instead of the
filing.** Four problems, one fix. That is why the filing work comes first.

Problems 4, 5 and 6 are separate and survive that fix. Of those, 4 is probably the one to do first,
because it is how we would learn which of the others actually matters.

## Deliberately not on this list

- **We store numbers as doubles.** That is what the SEC publishes. A more precise type would suggest
  accuracy we do not have.
- **Postgres can be deleted.** It is a copy we rebuild from the lake. That is the design.
- **Provisional labels.** They are a symptom of problem 1, and they are shown everywhere they apply.
  The weakness is the thin data, not the label.
