# Selected real-company acceptance: Apple and JPMorgan Chase

Date: 2026-09-13. Outcome: **40 selected annual observations match issuer-published statements after
the fixes described below. This is a bounded acceptance sample, not full financial-data certification.**

## Scope and evidence handling

The completed local lake was read only. Selected company/period rows, the two
company statement/check partitions and relevant filing metadata were copied into an isolated
6,277,945-byte, 284-Parquet-file sample under `work/real-acceptance/lake`. No source file, running
process, credential or production database was changed. The new grid and exporter ran on this copy.

Expected numbers were transcribed from original issuer PDF tables independently of the lake and
implementation fixtures. The six relevant statement pages were rendered and visually inspected to
confirm annual-versus-quarterly columns, units and parentheses. The 2024 values were checked against
the comparative columns in the 2025 publications, not against a separately downloaded 2024 publication.

The local evidence includes the downloaded PDFs, page renders, a reproducible `verify.py` and an
`acceptance-results.json` containing the expected/actual observations, grid metadata and separate
automated check results. These are working evidence, not shipped product data.

## Independently checked annual values

### Apple, CIK 320193

Source: Apple's [FY2025 Q4 consolidated financial statements](https://www.apple.com/newsroom/pdfs/fy2025-q4/FY25_Q4_Consolidated_Financial_Statements.pdf),
PDF pages 1-3. This issuer earnings-release attachment is labelled unaudited. The two annual columns
end September 28, 2024 and September 27, 2025; the quarterly columns on page 1 were not used here.

Money is USD millions; EPS is USD/share; diluted weighted-average shares are millions of shares
(converted from the issuer's explicitly stated thousands). All 20 values below match the annual grid.

| Measure | FY2024 | FY2025 |
|---|---:|---:|
| Net sales | 391,035 | 416,161 |
| Net income | 93,736 | 112,010 |
| Diluted EPS | 6.08 | 7.46 |
| Diluted weighted-average shares | 15,408.095 | 15,004.697 |
| Assets | 364,980 | 359,241 |
| Liabilities | 308,030 | 285,508 |
| Shareholders' equity | 56,950 | 73,733 |
| Operating cash flow | 118,254 | 111,482 |
| Investing cash flow | 2,935 | 15,195 |
| Financing cash flow | -121,983 | -120,686 |

Grid source filings: FY2024 `0000320193-24-000123`; FY2025 `0000320193-25-000079`.

### JPMorgan Chase & Co., CIK 19617

Source: the issuer's [2025 Form 10-K](https://www.jpmorganchase.com/content/dam/jpmc/jpmorgan-chase-and-co/investor-relations/documents/quarterly-earnings/2025/4th-quarter/corp-10k-2025.pdf),
printed pages 165, 167 and 169 (PDF pages 167, 169 and 171). Both annual periods end December 31.

Money and shares are millions; EPS is USD/share. These are consolidated reported amounts, including
net revenue after interest expense, not a managed-revenue measure. All 20 values match the annual grid.

| Measure | FY2024 | FY2025 |
|---|---:|---:|
| Net revenue | 177,556 | 182,447 |
| Net income | 58,471 | 57,048 |
| Diluted EPS | 19.75 | 20.02 |
| Diluted weighted-average shares | 2,879.0 | 2,781.5 |
| Assets | 4,002,814 | 4,424,900 |
| Liabilities | 3,658,056 | 4,062,462 |
| Stockholders' equity | 344,758 | 362,438 |
| Operating cash flow | -42,012 | -147,782 |
| Investing cash flow | -163,403 | -265,565 |
| Financing cash flow | 63,447 | 269,533 |

Grid source filings: FY2024 `0000019617-25-000270`; FY2025 `0001628280-26-008131`.

## Defects exposed by this sample and corrected

1. **FSDS per-share units could be scaled as currency totals.** Both companies' old FSDS EPS rows
   carried `unit=USD` with `datatype=perShare`. A millions export would incorrectly divide EPS by a
   million. The grid now restores `USD/shares` from that explicit taxonomy datatype before scaling,
   while source evidence retains `reported_unit=USD` and an explanatory `unit_note`. New FSDS staging
   performs the same normalization before joining Company Facts. Raw lake inputs were not rewritten.
   Share-count values and their `shares` unit were already correct. Excel preserves raw shares under
   their explicit unit rather than applying the currency scale.

2. **Label changes split one concept across rows.** Apple's investing cash-flow label and JPMorgan's
   net-income label changed across these years, producing an artificial blank in each of two rows.
   Unique same-taxonomy/concept/unit observations now align on one row. The old wording is retained
   per period in `labels` and source metadata. Repeated concepts, different currencies, unknown
   identities and different taxonomies remain separate. Regression tests protect opening/closing
   balance occurrences and repeated comparative lines.

3. **Some source dates were inferred, not exact context dates.** Apple's stored FY2025 EPS row spans
   October 1, 2024-September 30, 2025, although the issuer period ends September 27. Revenue and share
   rows have the exact fiscal dates. The per-share unit mismatch prevented the EPS context-date join.
   The corrected staging join recovers exact dates on rebuild when matching facts are available;
   a regression checks September 29, 2024-September 27, 2025. Existing FSDS metadata now carries a
   `date_note` explaining possible rounding/inference. Improving historical stored dates requires a
   separate controlled reconciliation/rebuild; this acceptance run did not perform it.

## Automated invariants, separate from source validation

- The same 40 selected values survived workbook save/reopen at units and millions scale: **80 numeric
  export checks**. EPS stayed unchanged and shares retained the explicitly labelled shares unit.
- The four annual balance sheets satisfied assets = liabilities + equity.
- The five FY2025 headline values in each company's `company_metrics` row agreed with the selected
  source observations. This does not add independent observations to the count of 40.
- In the latest eight available periods for each company, **416 derived cells** reproduced the sum of
  their original operands multiplied by stored coefficients. This verifies calculation provenance,
  not that all underlying reporting bases are economically comparable. Those derived numbers were
  not independently checked against every original quarterly filing.
- **67 targeted tests passed**, including exporter/scaling tests, FSDS staging, non-additive and
  incompatible-input cases, row identity, and real disposable-Postgres parity for all four period modes
  plus latest presentation. This Postgres test uses synthetic fixtures, not the production database.

## Remaining acceptance work

This sample covers two US GAAP companies and two annual periods. It does not certify every line,
quarterly/LTM values, amendments, restatement history, foreign filers, insurance, REITs, segment facts,
custom metrics, source-page anchors, complete document coverage, search or alerts. Unsupported
derived concepts still return an explicit unavailable value. Their frequency in banks is material;
the reviewed allowlist and source coverage need further expansion before broad completeness claims.

Source inspection currently links to the filing/document and discloses date uncertainty. It does not
guarantee an exact XBRL context or page for every cell. Opening a workbook in desktop Excel and
Google Sheets, formula recalculation, browser acceptance and production-load performance are separate
checks. Expand the independent benchmark to the planned diverse company set before public launch.

## Source fingerprints

- Apple PDF SHA-256: `43e7f0730b3cce0fc37301a2f43c29712bbde6ab299d97c6df345fd0c754508a`
- JPMorgan PDF SHA-256: `e16cdad03ca84732dbe21b2595c112e975d5a3f27bce9f394828160275bfe79c`

The check ran against the isolated implementation working tree based on commit
`1a5369b2e5c82457ddd9a015fce7d37f97463425`, including the financial corrections in this change set.
