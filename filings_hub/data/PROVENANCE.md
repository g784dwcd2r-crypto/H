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
