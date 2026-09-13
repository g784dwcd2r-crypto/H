# Financial period methodology and release limits

The API grid and Excel exporter use the same values and per-cell evidence. This implementation is a
conservative release boundary, not a complete financial normalization engine.

## Reporting and derivation

Directly reported values for the requested duration take priority, including a Q4 explicitly reported
in an annual filing. Annual and as-filed views preserve reported values. Balance sheets preserve
point-in-time observations in every mode.

Only the explicitly listed standard currency-flow concepts in `export/methodology.py` may be derived:

- Q2/Q3 flow = current YTD minus previous YTD.
- Q4 flow = annual minus nine-month YTD.
- LTM flow = current YTD plus prior annual minus prior YTD.

Required inputs must share currency, taxonomy family and presentation sign. Differences must share
a reporting start; LTM also requires contiguous prior-year-end and current-YTD-start dates. Inputs
from custom taxonomies, unknown concepts, missing filings, incompatible dates, or conflicting later
comparatives produce an unavailable cell with an explanation. We do not substitute a sum of separately
reported quarters when the necessary YTD data is missing.

EPS, ratios, weighted-average shares, average balances and other non-additive figures are shown only
when directly reported for the requested period. Subtracting annual and nine-month average shares is
not a quarter's average. EPS also has numerator/denominator and dilution rules; the IFRS Foundation's
[IAS 33 overview](https://www.ifrs.org/issued-standards/list-of-standards/ias-33-earnings-per-share/)
describes these separate inputs. No derived EPS approximation is offered.

The allowlist is intentionally incomplete. Extending it requires a reviewed concept definition,
compatible units and a source-based regression case; presentation classification is not proof of
additivity. Unavailable figures must remain unavailable in exports and the interface.

## Per-cell evidence

Each line's `value_metadata` is keyed by the displayed period label:

```json
{
  "status": "derived",
  "formula": "FY − nine months YTD",
  "sources": [
    {
      "accession": "filing-accession",
      "concept": "NetIncomeLoss",
      "taxonomy": "us-gaap/2025",
      "period_start": "2025-01-01",
      "period_end": "2025-12-31",
      "qtrs": 4,
      "unit": "USD",
      "value": 450,
      "coefficient": 1
    }
  ]
}
```

This illustrative metadata fragment omits the second input. Actual derived cells include every
original operand, so the sum of `value × coefficient` reproduces the displayed value. Sources also
include available filing dates and document URLs. No document anchor or page number is invented.
For reported cells the single source has no arithmetic coefficient.

Statuses are `reported`, `derived`, `unavailable` and `latest_presentation`. Unavailable cells include
a `reason`. With source inclusion enabled, Excel puts the same evidence, operands and explanations
in cell comments, in both workbook orientations.

Source dates reflect the stored observations. Some FSDS observations use the existing ingestion
fallback to estimate dates from `qtrs` and rounded period end when exact Company Facts dates cannot
be matched. These are not guaranteed original XBRL context dates. This remains a data-foundation
limitation; exact-context provenance is a separate ingestion improvement.

Legacy FSDS per-share facts with currency-only units are normalized from their explicit `perShare`
datatype before display/export scaling; `reported_unit` and `unit_note` retain the original unit and
explain the correction. New FSDS staging normalizes before context-date matching as well. Historical
files need controlled rebuilding to benefit from corrected dates. FSDS sources carry `date_note`
because the existing schema does not distinguish exact matched dates from inferred dates.

Unique concepts align across label changes only when taxonomy family and unit agree across the
selected filings. `labels` preserves the wording for every period. Repeated occurrences in primary or
comparative columns are never collapsed by this alignment; opening and closing balances stay separate.

## Later presentations

The legacy API option is named `restated`, but its behavior is latest available comparative
presentation. A later comparative can reflect reclassification or presentation changes without a
formal restatement. The actual source is resolved per cell. If later filings omit a line, its original
reported value and original source are retained with an explanation. Different-currency later values
are unavailable instead of appearing under the original currency label.

Period-level `basis` and `restated_from` remain for backward compatibility and are summaries only.
Interfaces must use cell metadata for evidence rather than infer a number's source from a column.

This release does not implement full amendment history, original/as-of-date snapshots, dimensional
normalization or cross-filing reconciliation sufficient to prove unchanged accounting policies.

## Serving and release checks

Full, incremental and CLI Postgres loads now retain primary, comparative and YTD rows by default.
Existing installations previously loaded with primary rows only require a full lake-to-Postgres
reload to restore omitted historical rows. A normal incremental load repairs only touched filings.
Do not run a full production reload concurrently with an active ingestion job.

`--no-all-periods` remains an explicit legacy reduced-data option. Such a database cannot support
complete quarterly/LTM/latest-presentation coverage and should not serve the full product.

Regression tests cover non-additive values, reported Q4 preference, unknown/custom concepts,
currency/sign/date incompatibility, changed comparatives, source coefficients, retained original
cell provenance, Excel comments and default full/incremental Postgres-to-lake grid parity. The test
database is a disposable local Postgres cluster; the running production backfill is untouched.

Passing these tests does not replace validation against a diverse set of original company filings.
