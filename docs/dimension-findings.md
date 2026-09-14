# What the dimension data shows

Measured on the reloaded lake, quarter 2026q2 (7,684 filings, 719,327 presented statement lines).
Method: a line is lost when the SEC's presentation file says the company printed it, the filing has
no undimensioned value for that tag, and it does have one or more dimensioned values. No heuristics,
no calculation tree needed.

## Lines we drop

| | |
|---|---|
| Filings losing at least one presented line | 7,014 of 7,684 (91.3 %) |
| Presented lines with no undimensioned value | 46,672 of 719,327 (6.49 %) |

By statement:

| Statement | Lines lost | Share | Filings |
|---|---|---|---|
| Equity | 24,336 of 80,058 | 30.4 % | 5,771 |
| Balance sheet | 14,760 of 252,845 | 5.8 % | 3,596 |
| Income statement | 5,091 of 145,808 | 3.5 % | 1,766 |
| Cash flow | 2,276 of 222,107 | 1.0 % | 721 |
| Comprehensive income | 209 of 18,509 | 1.1 % | 94 |

Not all equally serious. The equity statement is dimensional by nature: every movement is tagged by
equity component, so it cannot be built from undimensioned values at all. Most balance-sheet losses
are share counts and par values broken out by share class. The income statement and cash flow losses
are the Triumph Financial case: real revenue and expense lines the reader expects to see.

**On NYSE and Nasdaq specifically, 1,867 of 5,781 filings (32.3 %) lose income-statement or cash-flow
lines.** Among them: Berkshire Hathaway (37 lines), KKR (38), Northrop Grumman (35). This is not an
edge case confined to small filers.

Most affected tags overall are `SharesOutstanding`, `StockIssuedDuringPeriodShares*`,
`CommonStockShares{Issued,Outstanding,Authorized}`, `CommonStockValue`, and, on the income
statement, `EarningsPerShareBasic` / `Diluted` (472 and 466 filings) — all broken out by share class.

## How big the dictionary really is

One quarter carries 2,876,388 axis=member pairs, across 1,340 distinct axes and 156,532 distinct
members. Those totals are misleading; the distribution is what matters.

| Axis | Facts | Members |
|---|---|---|
| InvestmentIdentifier | 667,495 | 83,189 |
| EquityComponents | 458,812 | 1,416 |
| BusinessSegments | 158,080 | 5,373 |
| ClassOfStock | 137,517 | 1,991 |
| ConsolidationItems | 124,621 | 24 |
| LegalEntity | 120,552 | 2,006 |
| ProductOrService | 74,985 | 8,790 |
| InvestmentType | 73,593 | 2,214 |
| ConsolidatedEntities | 64,306 | 621 |
| FairValueByFairValueHierarchyLevel | 60,498 | 7 |
| Geographical | 43,877 | 1,155 |
| Restatement | 30,716 | 105 |

Reading it:

- **Half the member count is one axis that needs no dictionary.** `InvestmentIdentifier` holds 83,189
  members because each is one loan or holding of a fund. Those are identifiers, not concepts.
- **The standardised axes are tiny.** `ConsolidationItems` has 24 members, the fair-value hierarchy 7.
  Where the taxonomy defines the members, there is almost nothing to map.
- **The human mapping is concentrated in two axes**: `BusinessSegments` (5,373 members) and
  `ProductOrService` (8,790). These carry the company-invented names. That is where the
  "claims authorized on vehicle service agreements" problem lives, and it is roughly 14,000 names
  before deduplication across companies, not 156,000.
- **`Restatement` is a free input for the restatement work**: 105 members, 30,716 facts. Companies tag
  restated figures on this axis, so the restatement notice does not have to be inferred by comparing
  filings.

## What this settles

The unit of identity is the base tag plus its dimension. A dictionary keyed on the tag alone would
merge distinct revenue streams, distinct share classes and distinct segments into single numbers.

It also supports the view that the edge cases fall into a handful of types: twenty axes cover the
overwhelming majority of facts, and only two of them carry a mapping problem of any size.
