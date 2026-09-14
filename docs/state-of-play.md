# Where we stand, 2026-09-14

A short page: what we have, what is broken, what is next.

Detail lives elsewhere. `data-plan.md` has the order of work. `weaknesses.md` has what is broken.
`decisions.md` has why we chose things. `legal-questions.md` has what a lawyer needs to answer.

## What we have

**A working website.** You look up a US listed company and see its financial statements, laid out the
way the company printed them. Search, watchlists, a morning email, Excel export, sign-in and
per-user display settings all work. It is live.

**Our own copy of the data.** 8,394 listed companies. 433,717 filings. 70 quarters of the SEC's data
files, every row and every column. We do not need anyone else's servers to show a page.

**Three layers, kept apart:**

1. Raw files, exactly as the SEC gave them.
2. Our tables, as Parquet files. This is the source of truth.
3. Postgres, a copy we use to serve pages fast. We can delete it and rebuild it from layer 2.

**Things we got right, that could have gone another way:**

- One storage layer covers both local disk and R2. Tests and production run the same code.
- Queries work with or without a database. No Postgres? It reads the Parquet files directly. So the
  API, the exporter and all tests run without a database.
- Files are split by company. A company page reads only that company's files. This is why serving
  from R2 is cheap.
- We keep everything the SEC publishes. Every column is read as text and converted on purpose, so
  all 70 quarters look the same. Unknown columns are kept. Every load counts rows read, loaded and
  rejected, and too many rejects becomes a logged failure.
- A line is a concept **plus its dimension**. This fix brought back 694,242 lines across 5,733
  companies in one quarter. One bank's fee income read 2,800,000 when the company reported
  19,707,000.
- Our checks know what they are comparing. They compare the same concept across statements, not two
  that sound alike. They will not divide one share class's earnings by another's share count. They
  refuse to run when a number would be a guess.
- We keep the filed number and the shown number in separate columns, and record where each row came
  from. Numbers built the provisional way are labelled as provisional everywhere.
- Every run writes a log row. Two loaders cannot publish at once. An incomplete load will not
  publish at all.

**The filing reader.** Finished this week. It reads a filing's own XBRL files. 650 tests pass.

## What is broken

Eight things. Full detail in `weaknesses.md`.

| # | Problem | What we do |
|---|---|---|
| 1 | The newest filing uses our weakest method, and it is the page people open most | Already planned: phase 1 |
| 2 | We guess which line adds into which. The guess flagged 98.3 % of filings | Stop publishing the guess. Now |
| 3 | Our error tolerance is a flat 0.5 %, so real errors hide inside it | Needs the filing. Measure now |
| 4 | We cannot say what we are missing | Start now. Nothing blocks it |
| 5 | When a company restates, nothing tells the user | After the cross-filing check |
| 6 | Statement files are never merged, so there are ~500,000 small ones | Only if it starts to hurt |
| 7 | The filing reader has only been tested on made-up filings | Test on real ones before the big download |
| 8 | Seven tickers point at two companies each, plus three smaller issues | Fix the ticker bug now |

Problems 1, 2, 3 and 7 have the same cause: **we read the SEC's summary of a filing instead of the
filing.** One fix solves all four. That is why the filing work comes first.

Problems 4, 5 and 6 are separate and stay after that fix.

## What we already decided about these

- **1.** Settled. If we say a number is what a company filed, we must hold the filing.
- **2.** "A wrong check is worse than no check." So we stop showing the guess as fact. No download
  needed.
- **3.** The SEC's data files do not say how precise a number is. Only the filing does. But we
  already store the two sides of every check, so we can measure today how much the 0.5 % hides.
- **4.** Settled. Coverage is our own internal measure. The plan already says this starts now.
- **5.** The one thing users do see. A restatement is shown as a notice, never as a failure.
- **6, 7, 8.** Our call. Nobody else needs to decide.

## What changed today

**Classification.** We group companies by how analysts cover them, not by what they sell. Then we
put companies into those groups. Written up in `decisions.md` with the table design, Mbarek's two
changes, and Transportation as the first test. It replaces the old "use SIC" line in the data plan.

**Other countries.** Each region is a different source, not a longer list. Europe is easiest: its
filings are inline XBRL, which our reader already handles. Canada is harder. AUS/NZ is like Canada.

**Share prices stay parked** until a lawyer answers section 2 of `legal-questions.md`.

## What is next

**Start now, nothing blocking:**

- Measure our coverage, company by company.
- Stop publishing the subtotal guess.
- Measure how much the 0.5 % tolerance hides.
- Fix the seven duplicate tickers.

**Then, in order:**

1. Test the reader on ~20 real filings.
2. Download and store the filing files.
3. Build statements from filings, and use the SEC data files to cross-check.
4. Run the real subtotal check.

**After that:** the restatement notice.

**Alongside, when the company list arrives:** the classification tree, starting with Transportation.

**Only if needed:** merging the small files.

## Still open

- **The company list** for the US, Canada and Europe. Being gathered now.
- **The classification definitions.** We can help assign companies. The groups and the hard calls are
  human, and someone has to keep reviewing them as companies change.
- **For a lawyer:** market data, and what protects a classification we build ourselves.
- **One thing to settle:** the task list says "top 4,000 companies". The integrity plan says every
  company, grouped by tier, with no cutoff. The plan is right; the task wording should change.
