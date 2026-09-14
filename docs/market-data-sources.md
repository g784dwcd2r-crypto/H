# Market data beyond EDGAR: what is free, what is not

EDGAR gives us everything a company files. It does not give prices, index membership or GICS.
This is the search for free and legal routes to the rest, September 2026. Hosts below are blocked
by the sandbox egress proxy, so every "verify" step runs on the Mac, not in a Claude session.

## Already in our lake, free forever

Checked against the R2 lake for Apple, Microsoft, JPMorgan and Nvidia:

| What | XBRL concept | Rows in that sample |
|---|---|---|
| Dividends per share declared | `CommonStockDividendsPerShareDeclared` | 1,133 |
| Dividends paid, cash | `PaymentsOfDividendsCommonStock` | 263 |
| Shares outstanding, cover page | `EntityCommonStockSharesOutstanding` | 280 |
| Shares outstanding, balance sheet | `CommonStockSharesOutstanding` | 411 |
| Weighted average shares, diluted | `WeightedAverageNumberOfDilutedSharesOutstanding` | 933 |
| Public float | `EntityPublicFloat` | 108 |

So dividends and the share count are solved with no new source. Market capitalisation is price
times shares, and we already hold the shares. Only the price is missing.

## Free and official, not yet ingested

**Listing status, exchange, ETF flag, test issues.** Nasdaq publishes the symbol directory as two
pipe-delimited files updated through each day, no key and no login:
`https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt` and `.../otherlisted.txt`
(also over anonymous FTP at ftp.nasdaqtrader.com, folder SymbolDirectory). This is the
authoritative answer to "is this ticker really listed, and where", better than inferring it from
our ticker file.

**Index membership, two free routes.**
1. *ETF holdings from the issuer.* An index fund holds the index. BlackRock publishes a daily
   holdings CSV for IVV (S&P 500) and IWM (Russell 2000) on ishares.com; State Street does the
   same for SPY. Free download, daily, no key.
2. *SEC Form N-PORT.* Every registered fund files position-level holdings in structured XML,
   public quarterly, about 60 days in arrears, in EDGAR, which we already ingest. Slower than the
   issuer files but it is a primary source and it needs no new vendor relationship.

Both are membership by proxy: a fund's holdings, not the index itself. Fine for ranking and
screening internally. Displaying "member of the S&P 500" as a labelled fact is what needs an S&P
Dow Jones Indices licence.

**Industry classification, free alternatives to GICS.** GICS is owned by MSCI and S&P and must be
licensed; there is no free route. What is free:
- SIC code and description, already in our companies table.
- `owner_org`, the SEC's own office assignment (for example "06 Technology"), added to the
  companies table in the header work of 2026-09-14. Coarser than GICS but current and official.
- Our own sector mapping over SIC, reviewed with Hicham. Data, not code, so it can be corrected
  without a release.

## Prices: where free runs out

Real-time US consolidated quotes are exchange property. NYSE, Nasdaq and Cboe charge per
displaying user, and a product showing live quotes to customers needs an exchange agreement or a
vendor carrying one. There is no free-and-redistributable real-time US equity feed. Delayed and
end-of-day are a different market, and much cheaper.

Free options, with the catch stated:

| Source | What you get | Catch |
|---|---|---|
| Stooq bulk CSV | Daily OHLCV, US and worldwide, no key | Terms of use do not clearly permit commercial redistribution. Verify before shipping. |
| Alpha Vantage free tier | Daily and intraday | Request cap is small; personal use |
| Finnhub free tier | Quotes, fundamentals, 30 years of dividends | Free tier is personal use |
| Twelve Data, Marketstack free tiers | Daily and delayed | Request caps; non-commercial |
| Databento | Real-time and historical, pay per use | Advertises zero licence fees and free redistribution rights, with a starting credit rather than a free tier. Worth a direct read of the pricing page. |

Cheapest route that is clean for a commercial product: EODHD or Polygon, end-of-day plus
dividends and splits, tens of dollars a month, with the redistribution clause read first. The
headline price is not the deciding factor. The redistribution clause is.

## Recommended order

1. Nasdaq symbol directory. Free, official, no licence question, improves the universe we already
   have. Small ingest.
2. Prices, end of day only. Start on a free tier for development, move to a paid plan with written
   redistribution rights before anything is shown to a customer.
3. Market capitalisation computed by us: price times shares outstanding from the lake, handling
   multiple share classes.
4. Index membership from ETF holdings, internal ranking first, display only with a licence.
5. Sector: SIC plus `owner_org` plus our mapping now, GICS only if a customer requires the label.
6. Real-time: defer until a customer asks and pays, because exchange fees scale per user.

Every source follows the same rule as EDGAR: download the raw file untouched into `raw/`, turn it
into a table with row counts reconciled, and never drop a row or a column.
