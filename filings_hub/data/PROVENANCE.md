# Vendored reference data

## sp500_constituents.csv

The S&P 500 constituent list used by `filings-hub verify` for the plan's
"`checks_passed` >= 95 % on S&P 500 filings since 2020" criterion.

| | |
| --- | --- |
| Source | https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv |
| Retrieved | 2026-09-12 |
| SHA-256 | `e06b473e4679074b2aaa49da67dfc154338b466ca66102935d93486c34e16883` |
| Rows | 503 constituents |

Third-party data, treated strictly as data: only the `Symbol` and `CIK` columns are
read, and a row whose CIK is not an integer is skipped. The index changes a few names a
year, which does not materially move a pass rate measured across ~500 companies, but
pass `--tickers-file` to `filings-hub verify` to use your own list.

## reader_set.csv

The real filings the XBRL reader is tested against (steps.md, step 5). Not third-party data:
a list we wrote, one row per filing, each with the reason it is awkward.

It is the golden set above plus the cases step 5 names that the golden set lacks: the bank whose
fee income is told apart only by a dimension (Triumph, the filing the synthetic fixture was
modelled on), a discontinued-operations filer, a 20-F filer, a filing from the first year of
mandatory XBRL, and small companies that invent their own labels. The two small companies are
given by CIK rather than ticker because a ticker for a micro-cap is not stable; both CIKs were
taken from the lake's own check report.

`filings-hub reader-fetch` resolves each row to an accession offline, from the lake's `tickers`
and `filings` tables, and downloads that filing's five XBRL files into
`tests/fixtures/real_filings/<key>/`, gzipped, with a manifest. `year`, when set, picks the
latest filing of that form filed in that year; otherwise the latest.
