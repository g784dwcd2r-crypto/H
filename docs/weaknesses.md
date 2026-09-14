# Where the data is weak

Our own list, written against the code on 2026-09-14, not a review by anyone else. Each entry says
what is actually wrong, where it lives, what a user would see, and what fixes it. Ordered by how much
damage it can do, which is not the same as how hard it is to fix.

Nothing here is speculative: every item was confirmed by reading the module named against it.

| # | Weakness | Damage |
|---|---|---|
| 1 | The newest filing takes the thinnest path | The most-read page is the least complete |
| 2 | `parent_concept` is a positional guess | We cannot prove any statement adds up |
| 3 | Tolerance is a fixed 0.5 %, not the filer's own precision | Real breaks hide inside the slack |
| 4 | Coverage is unmeasured | We do not know what we are missing |
| 5 | Restatements land with no marker | A number moves and nothing says so |
| 6 | No compaction for `statements` | Half a million small files, growing quarterly |
| 7 | The XBRL parser has never met a real filing | Verified only against our own idea of a filing |
| 8 | Smaller, still real | See below |

## 1. The newest filing is the weakest, and that is the one people open

The SEC's data sets lag a quarter or two, so the most recent filing of every company goes down the
fallback path in `sync_statements.py` (`build_fallback_rows`, `fill_all_fallbacks`) with
`source='facts_fallback'`. That path is built from company facts, which publishes **undimensioned
facts only**, and it takes line order and labels from the company's last data-set-covered filing as a
template. So the page a user is most likely to open is built from the thinnest data, laid out to a
stale plan.

It is labelled provisional on the company page, in the grid and in the Excel export, which is honest.
It is still the weak spot sitting in the highest-traffic place.

*Fixed by:* reading the original filing (data plan, phase 1).

## 2. `parent_concept` is a guess stacked on a guess

`checks.assign_parents` sets each line's parent to *the next subtotal below it in the list*. Purely
positional — it mirrors a SQL window in `sync_statements`, and neither knows anything about what the
company said adds into what. The subtotal it looks for comes from `checks.is_subtotal`, which is a
seed list of concepts plus a regex over the label.

Stack a guess on a guess and you get the number we measured: it flagged **98.3 % of filings**. That is
not a finding, it is a broken instrument. Today we cannot prove a single statement adds up, and we
ship `is_subtotal` and `parent_concept` columns that read as though we can.

*Fixed by:* the real calculation tree, which `xbrl.calculation_children` already returns and which
nothing consumes yet.

## 3. Tolerance is a fudge factor where the filing carries the real answer

`checks.py` sets `RELATIVE_TOLERANCE = 0.005` and `ABSOLUTE_TOLERANCE = 1.0`, and every check
everywhere uses them. On a 400 bn balance sheet, 0.5 % is 2 bn of slack: a real break fits inside it
comfortably.

XBRL carries `decimals` per fact — the company stating exactly how far they vouch for a number
("-6" means they rounded to millions). Our new parser keeps it (`xbrl.Fact.decimals`), but neither
`FACTS_SCHEMA` nor `STATEMENTS_SCHEMA` has the column, so the information dies before it reaches a
check. The tolerance should be built from what the filer vouched for, not from a constant we chose.

*Fixed by:* carrying `decimals` through into the statement rows and deriving the tolerance per line.

## 4. We do not know what we are missing

There is no core universe table, so coverage is unmeasured. We can say what we **have** — 8,394
listed companies, 433,717 filings, 70 quarters — but not what we **should** have. A company whose
filings produce zero applicable checks is getting no verification at all, silently, and we cannot
currently count those companies.

This is the one that matters most structurally, because every other weakness on this list is
something the audit would have found. We are fixing what we happened to notice.

*Fixed by:* phases 2 and 3 of the data plan. Needs Hicham's list, or the proxy universe as a stand-in.

## 5. Restatements land in the data with nothing marking them

`periods` records `amendment_accessions`, but `results_accession` points at the original filing, and
the fallback path skips amendments outright (`is_amendment` in `sync_statements.fill_fallbacks_for_cik`).
So when a company restates, the amended figures may exist in `statements` while the period still
resolves to the original — with nothing telling a user the number moved.

This is the worst kind of wrong: the user has no signal to distrust it. A restatement is also not a
failure and must never be reported as one — it is real information about the company, and it should
surface as a notice.

*Fixed by:* the restatement marker and company-page notice (data plan, phase 3, item 4).

## 6. `statements` is never compacted

`compact_filings` exists for the `filings` table only (`sync_filings.py`). Statements are written per
company per quarter — `statements/cik={cik}/fsds_{quarter}_*.parquet` — so 70 quarters across 8,394
companies is on the order of half a million small Parquet files, and it grows every quarter.

Per-CIK partitioning keeps a single company page cheap, which is what made serving from R2 viable at
all. But any full-lake scan pays object-metadata cost per file, and there is no compaction step to
stop the count rising.

*Fixed by:* a compaction pass for `statements` and `statement_checks`, in the shape of `compact_filings`.

## 7. The XBRL parser has never met a real filing

`filings_hub/testing/xbrl_fixtures.py` is synthetic — real-shaped, modelled on Triumph Financial, but
hand-written. The 14 tests in `tests/test_xbrl.py` all run against invented XML.

Real filings are where the ugliness lives: unusual namespaces, malformed linkbases, files named off
an unexpected base, pre-inline filings whose instance has no distinguishing suffix. We handled the
cases we could imagine. We will find out about the rest when we fetch real documents, and we should
expect to find some.

*Fixed by:* phase 1 step 2, and by keeping a handful of real filings as fixtures once we hold them.

## 8. Smaller, still real

- **Co-registrant rows are dropped from statements.** `sync_statements` selects `coreg IS NULL`. The
  rows are kept in the raw `fsds/num` table, so this obeys rule zero — selected out at read time,
  not lost at load time — but a jointly-filed statement quietly loses lines.
- **Seven tickers are claimed by two companies each.** A known open bug; it can route a user to the
  wrong company from search.
- **One DuckDB connection behind a lock.** Necessary — a concurrent `execute` replaces the pending
  result and silently pairs one query's columns with another's rows — but it is a hard throughput
  ceiling on the serving instance.
- **Serving tables are replaced one at a time.** `db.load._replace_all` does `TRUNCATE` then `COPY`
  inside a transaction, under an advisory lock, so no two loaders overlap. But the tables are not
  swapped as a set, so a reader mid-load can see one table already replaced and another not.

## The pattern

Items 1, 2, 3 and 7 share one root cause: **we have been reading the SEC's summary of a filing
instead of the filing.** That is what makes phase 1 the high-leverage move rather than simply the
next item on a list — four weaknesses collapse into one fix.

Items 4, 5 and 6 are independent and survive that work. Of those, item 4 is arguably the one to do
first, because it is how we would learn which of the others actually bites.

## Deliberately not on this list

- **Values are doubles.** `value` is `float64` because the SEC publishes doubles; introducing a
  decimal type would add precision we do not actually have.
- **Postgres can be dropped.** It is a disposable serving copy, rebuilt from the lake. That is the
  design, not a risk.
- **Provisional periods.** They are a consequence of item 1, and they are labelled everywhere they
  appear. The weakness is the thin data, not the labelling.
