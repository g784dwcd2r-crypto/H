# Guarded local model refresh prototype

`filings_hub.export.model_refresh` previews or applies **explicit cell mappings** from Disclosure's
versioned financial API to a new Excel workbook. This is not a native Excel add-in, a continuously
refreshing connection, a model builder or a claim to support arbitrary workbooks.

The prototype addresses one narrow task: update known numeric historical-input cells while retaining
the analyst's formulas and manual work. It does not infer which cells belong to historicals, forecasts,
valuation assumptions, consensus estimates or user overrides. Every mapped target is explicit.

## Mapping and preview

Start with `docs/model-refresh-mapping.json`, replacing its illustrative target, source identity and
guard with values for the actual workbook. In that example, `300000` means the current number expected
in `Model!B2`, not a claim about Apple's reported revenue. The exact `line_key`, period label and unit
come from `/v1/companies/{cik}/financials`; do not guess them from a friendly row title. A changed key
fails explicitly rather than substituting a similarly named row.

Each mapping requires a worksheet, cell, CIK, statement, exact line key, period label, source unit and
`last_written`. The guard must be a finite number, or explicit `null` for an empty target. The guard is
compared exactly to the workbook; strings and booleans cannot impersonate numeric values. The prototype
supports up to 500 unique target cells per operation. A target cannot be a merged cell or contain a
formula. Unit mismatches, missing/ambiguous sources and unavailable values with insufficient evidence
block the operation. Currency totals may use units/thousands/millions/billions. Share counts, per-share
figures and ratios must use units. This uses the same conservative source values as the financial API.

```sh
uv run python -m filings_hub.export.model_refresh analyst-model.xlsx mapping.json
```

The default is **preview only**. The JSON report includes every current/guard/proposed value, a reason
for each conflict, source evidence and content snapshot identifiers. It changes no workbook. Root-level
`period_mode`, `presentation` and optional `as_of` select the financial view. Their limitations are
preserved in the report: `as_of` uses filing-date resolution and current period mapping, not an archived
intraday database snapshot. A content hash identifies returned data; it does not certify accounting
accuracy or archive the provider dataset. Production source reads share a database snapshot across CIKs;
the local lake's existing publication limitations still apply.

## Apply without overwriting

```sh
uv run python -m filings_hub.export.model_refresh analyst-model.xlsx mapping.json \
  --apply --out analyst-model-refreshed.xlsx
```

Applying is all-or-none: **any conflict or unavailable mapped source prevents the output workbook**.
A conflicting manual value or formula is never overwritten. An existing output path, input path,
macro-enabled extension or unsupported object fails explicitly. A successful operation writes a
separate, new workbook and never replaces the input. Input hash checks detect concurrent input changes.
The complete serialized artifact is published with an exclusive filesystem link, so a partial write
or concurrent output cannot silently replace another file. The local filesystem must support hard links.

The report's `next_mapping` advances each guard to the value just written. Save this mapping for the
next operation against the new workbook. A changed guard must be reviewed; do not blindly replace it
with a new manual value just to bypass a conflict. There is no automatic source-to-user override policy.

Updated cells retain source evidence in comments, including financial snapshot ID, source observations,
units and period. Existing ordinary comment text is retained when it belongs to another author. Formula
expressions and all unmapped cell values are checked after serialization; mapped values and evidence
must also survive round-trip verification before output publication.

## Supported workbook boundary

The supported input is a bounded, ordinary `.xlsx` OOXML package with worksheets, ordinary formulas,
styles, theme, hyperlinks and ordinary comments. Inputs are capped at 30 MiB, 1,000 package parts and
200 MiB expanded content. Unsupported package parts and extension elements are rejected before
openpyxl can silently discard them. Reader/writer warnings also fail the operation.

Macros/binary workbooks, external-workbook links/connections, charts/images, tables/pivots, embedded
objects, controls, extension-based features, array/spill/data-table formulas and protected workbooks
or worksheets are not supported. This strict boundary deliberately rejects many sophisticated
institutional models; extending compatibility requires an explicit preservation test per feature.
Ordinary comment text/author are retained, but this release does not promise rich comment styling or
arbitrary application metadata preservation.

**openpyxl does not calculate formulas.** Formula expressions are retained, but cached results are
not recalculated or preserved as certified outputs. The workbook requests full recalculation on open.
Open/recalculate/review it in desktop Excel before using dependent formula values; saving/reopening
with openpyxl is not desktop Excel formula acceptance. No workbook is uploaded to a server by this CLI.

## Verification

`tests/test_model_refresh.py` exercises real synthetic financial snapshots, explicit previews,
correct currency/per-share scaling, saved source comments, repeated refresh with next guards,
preserved formulas/manual values/styles, manual-override conflicts, unit changes, missing sources,
date cutoffs, empty/merged targets, charts/protection/unsupported parts, array formulas, non-overwrite
paths and mapping validation. The tests reopen actual output workbooks. They do not substitute for
desktop Excel calculation testing or real customer-model compatibility acceptance.
