# State of play, 2026-09-14

One page for "where are we". It carries no reasoning of its own: `data-plan.md` holds the running
order, `weaknesses.md` what is wrong, `decisions.md` why each choice was made, `legal-questions.md`
what is blocked on advice. This is the summary that points at them.

## What we have

**A working product.** A subscriber opens a US listed company and sees its statements as the company
printed them, with search, watchlists, a morning digest, Excel export and per-user display
preferences. Accounts, sign-in and sessions are live. It is deployed and serving.

**A lake that is ours end to end.** 8,394 listed companies, 433,717 filings, 70 quarters of the SEC
data sets held with every row and every column. We do not depend on anyone else's servers to render
a page.

**An architecture with one good separation in it.** Raw bytes as the SEC gave them, then our modelled
Parquet tables, then Postgres as a *disposable* serving copy that can be dropped and rebuilt from the
lake at any time. The lake is the source of truth; the database never is.

Worth naming as strengths because each one was a decision that could have gone the other way:

- **One storage abstraction** over fsspec, so local disk and R2 are a single code path: the whole
  test suite runs on a temp directory against the same code that serves production.
- **Two query backends behind one interface.** Postgres when `DATABASE_URL` is set, DuckDB straight
  over the lake when it is not, so the API, the exporter and every test run with no database at all.
- **Per-CIK partitioning**, which is what made serving the full lake from R2 affordable: a company
  page reads that company's files and never lists the bucket.
- **Rule zero enforced in code, not asserted in a doc.** Every FSDS column is read as text and cast
  explicitly so all 70 quarters land identically; unmapped columns pass through; company headers
  carry a `header_extra` JSON catch-all; every load records raw / loaded / rejected and a reject over
  threshold becomes a run-log failure.
- **A line's identity is concept plus dimension.** The fix that recovered 694,242 lines across 5,733
  companies in one quarter, and stopped a bank's fee income reading 2,800,000 against a reported
  19,707,000.
- **Checks that know what they are comparing.** They bridge discontinued operations and equity-method
  income, compare the same concept across statements rather than two that sound alike, refuse to
  divide one share class's earnings by another's share count, and refuse to run at all where the
  numerator would be a guess.
- **Evidence kept apart from arithmetic.** `value` is what was filed, `value_presented` what was
  shown, `source` says whether a row came from the data sets or the provisional fallback, and
  provisional periods are labelled on the page, in the grid and in the export.
- **Every run accounted for.** A `run_log` row per run, an advisory lock so two loaders cannot
  publish at once, and a refusal to publish at all from an incomplete source inventory.

**The filing reader's parsers**, finished this week: the four linkbases and the instance document,
read as pure functions over bytes. 650 tests pass across the suite.

## What is weak

Eight items, all confirmed against the code, written up in `weaknesses.md`. In one line each:

| # | Weakness | Status |
|---|---|---|
| 1 | The newest filing takes the thinnest path, and it is the most-read page | Settled: phase 1 fixes it |
| 2 | `parent_concept` is a positional guess that flagged 98.3 % of filings | Act now: stop shipping it as fact |
| 3 | Tolerance is a flat 0.5 % where the filing carries `decimals` | Gated on phase 1; measure now |
| 4 | Coverage is unmeasured: we cannot say what we are missing | Start now, needs nothing |
| 5 | Restatements land with nothing marking them | After the cross-filing check |
| 6 | `statements` is never compacted | Only when proven to hurt |
| 7 | The XBRL parser has never met a real filing | Sample before the full crawl |
| 8 | Seven tickers claimed by two companies; co-registrant rows dropped; and two serving-layer limits | Ticker bug now; rest measured first |

Items 1, 2, 3 and 7 share one root cause: **we have been reading the SEC's summary of a filing rather
than the filing.** Four weaknesses collapse into one fix, which is what makes phase 1 the
high-leverage move rather than merely the next item. Items 4, 5 and 6 survive it and are separate
work.

## What each weakness resolves to, against what was already decided

- **1** — the trust rule already settled it: if we claim a number is what was filed, we hold what was
  filed. Nothing new to decide.
- **2** — "a wrong check is worse than no check" decides this against us. The honesty fix is today's
  work and needs no download: stop presenting a guess as knowledge.
- **3** — the data sets carry no per-fact precision, so the real fix needs the filing. What is free
  today is measuring how much the flat tolerance hides, from the `lhs` / `rhs` / `difference` already
  stored on every check.
- **4** — already answered: coverage is an internal measurement, and the integrity plan's own order of
  work has the universe table, coverage and applicability all starting now, needing nothing.
- **5** — the single agreed exception to "quality is internal": a restatement is surfaced to the user
  as a notice, never as a failure.
- **6, 7, 8** — engineering judgement, not questions for anyone else.

## What changed today

**Classification turns over.** Buckets come from how analysts actually cover a name, not from what a
company sells, and companies are filled in afterwards. Recorded in `decisions.md` with the schema
shape, Mbarek's two accepted refinements (variable depth; a primary home plus explicit memberships
with exposure), the Transportation pilot and its test, and the two cautions. It supersedes the
"SIC as fallback" line in the data plan and it is layer-2 work.

**Coverage beyond the US is a source problem, one per region.** Europe is the easiest because ESEF is
inline XBRL and the parser already reads that format; Canada is harder than it feels; AUS/NZ has
Canada's shape. Also recorded.

**Share price stays parked** behind section 2 of `legal-questions.md`, and the plan now carries it in
its own set-aside section rather than as a buried bullet.

## Order of work

**Starts now, nothing blocking:** the coverage and applicability audit; demoting the parent guess;
measuring what the tolerance hides; the duplicate-ticker bug.

**Then, in sequence:** sample-validate the parser against real filings, fetch and store the file
sets, build statements from the filing with the data sets as cross-check, and run the real subtotal
check on the actual calculation tree.

**After the cross-filing check:** the restatement marker and the company-page notice.

**In parallel, as the list arrives:** the classification tree and the Transportation pilot.

**Only when proven necessary:** compaction.

## Open, and on whom

- **The company list** for the US, Canada and Europe, being gathered now. It upgrades the proxy
  universe and unblocks the sector work.
- **The classification definitions.** Assignment can be assisted; the buckets, the boundaries and the
  awkward calls are human, and review is a standing commitment.
- **With a solicitor:** market-data redistribution, and now also what protects a classification we
  author ourselves.
- **One discrepancy to settle:** the task list says a proxy universe of the top 4,000, while the
  integrity plan says the work runs over every company in the lake, grouped by tier, explicitly not a
  cutoff. The plan is the one to follow; the task wording should change.
