# Reports shared with reviewers

Snapshots, not live data. Each file is what the checks said on the day in its name, kept so a
reviewer can be sent a link rather than asked to run a command.

Regenerate with:

```
LAKE_ROOT=data filings-hub check-report --xlsx reports/failures-YYYY-MM-DD.xlsx
```

**Date every file.** These are a few megabytes each and every version is kept in the repository's
history forever, so overwriting one in place buries the old numbers and adds a second full copy
regardless. A dated name makes it obvious which run a reader is looking at, and lets an old one be
deleted once nobody needs it.

## What is in `failures-*.xlsx`

Every arithmetic check that failed, one row each.

* **Summary** — the headline, the split by check, the split by reason.
* **Failures** — company, filing, which check, why, the two numbers compared.

Filter the **Why** column first: it sorts the pile into rounding, a handful of mechanical shapes,
and `unexplained`, which is where the real work is and the only count that should be shrinking.

## How to read one row

Every row is one sentence: *we added up the filing's own lines and got this; the filing itself
says that; here is the gap.* Nothing is corrected — the two numbers are shown as they are.

| Column | What it is |
| --- | --- |
| Company, CIK, Filing | Who, and which filing. The filing number opens on EDGAR. |
| Statement | `IS` income statement, `BS` balance sheet, `CF` cash flow |
| Check | The arithmetic that was tested, written out |
| Why | The shape of the gap — see below |
| Computed / Reported | What the filing's parts add to / what the filing states |
| Difference | Computed minus Reported |
| Times over tolerance | 1.0 is exactly at the limit. 1.2 is a rounding difference; 145 is not. |
| What was compared | The exact tags used, so the row can be checked by hand |

A real row, in words:

> `ARTS WAY MANUFACTURING` · `Revenues - CostOfGoodsAndServicesSold = GrossProfit` ·
> computed 2,345,561 · reported 2,330,654 · 1.27 times over tolerance

Their revenue minus their cost of goods comes to about fifteen thousand dollars more than the gross
profit they print. On a two-million-dollar number that is a rounding difference, which is what
`just over the tolerance` and a low multiple mean. Compare with:

> `AAR CORP` · `SalesRevenueNet - CostOfGoodsSold = GrossProfit` ·
> computed 225,300,000 · reported 61,500,000 · 145 times over tolerance

That is not rounding. The computed figure is 3.7 times the reported one, which is what a
nine-month revenue paired against a three-month gross profit looks like.

## What the Why column means

| Why | What it usually means | Whose problem |
| --- | --- | --- |
| `just over the tolerance` | Rounding, usually within a few parts in a thousand | Nobody's — noise |
| `scale: factor of 1,000 or 1,000,000` | One side was filed in thousands or millions and the other in units | Usually the filer's |
| `period: factor of 2 to 4` | A year-to-date figure was paired with a quarterly one | **Usually ours** |
| `sign: exact negatives` | One side is the other with the sign flipped | Either |
| `one side is zero` | A line was tagged zero, or left blank and read as zero | Usually the filer's |
| `unexplained` | No simple pattern. Needs a person to read the filing. | Where the real work is |

## Before drawing conclusions from the totals

The two **EPS, approximate** rows are the largest block of failures, and they are the least
alarming. Those are the filings where the company did not tag the earnings figure its own
per-share number was calculated from, so we inferred it and allowed a 5 % tolerance. A failure
there often means our inference was wrong, not that the filing disagrees with itself. Read the
other checks first.

The three checks that run on the most filings are close to clean, and that is the more useful
headline: the balance sheet balanced on all but 608 of 427,162 tests, net income matched between
the income statement and the cash flow statement on all but one of 351,519, and ending cash matched
between the cash flow statement and the balance sheet every single time out of 213,786.
