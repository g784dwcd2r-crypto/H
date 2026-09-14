# Legal and regulatory questions, for advice

**This is a brief to take to a lawyer, not advice.** Nothing here is a legal opinion. It is written
so that a UK solicitor can answer quickly rather than start from nothing: each section says what we
actually do, what we currently believe and why, and the specific question we need answered. Where we
already believe something is settled, it is marked so — confirm it cheaply rather than research it.

Company is UK-based. Product is US-listed company filings today, Europe and possibly Canada later.

## What we are, in the terms a lawyer needs

- A subscription web product that republishes US SEC filings and the financial statements inside
  them, plus our own presentation, search and export of that material.
- Data comes from EDGAR, the SEC's public system. We download it, store our own copy, restructure it
  into tables, and show it. We do not alter the reported numbers.
- We intend to add end-of-day share prices from a commercial vendor, to compute and display market
  capitalisation.
- We hold personal data of two kinds: our own subscribers, and named individuals who appear in the
  filings themselves (company officers and directors in insider-dealing forms).
- Storage is Cloudflare R2; the application runs on Render. We should confirm where each holds data.

## 1. Redistributing SEC filings — believed settled, confirm only

**What we do.** Take EDGAR filings and data sets, store them, restructure them, publish them to
paying subscribers worldwide.

**What we believe.** US federal government works are not subject to copyright, EDGAR is published
expressly for public use, and the SEC's only stated conditions are fair-access ones (identify
yourself in the user agent, stay within request rates), which we comply with. The filings' *content*
is the filer's, but it is filed into a public disclosure system for the purpose of being read.

**Ask:** does being a UK company change any of that, and is there anything in the SEC's terms of use
that restricts commercial republication? Is a filer able to object to us republishing their filing?

## 2. Market data licensing — the live question

**What we would do.** Subscribe to an end-of-day price feed (EODHD and Polygon/Massive are the
candidates), store the prices in our lake, and show a closing price and a market capitalisation to
subscribers.

**What we believe.** Exchange prices are the exchanges' property. Vendors hold the exchange
agreements and sub-licence onward. Whether we may show a price to a paying customer depends entirely
on the vendor's redistribution clause, and most free tiers are personal-use only.

**Ask:**
- Does the vendor's agreement actually permit onward display to our paying subscribers, and is that
  "redistribution", "display" or "derived data" in their language? These are different permissions.
- Are there per-subscriber or per-displaying-user fees that scale with our customer count?
- Market capitalisation is our own calculation from their price and a share count we take from the
  filings. Is that a "derived work" that escapes the display licence, or still their data?
- Storing the history: are we allowed to keep a local copy, and what happens to it if we cancel?
- The Canadian feed reaches the vendor through a reseller rather than the exchange. Does that change
  the chain of rights?
- Governing law and jurisdiction of the vendor agreement, and what that means for us in the UK.

## 3. Database right — the difference between the UK and the US

**Why it matters.** The UK retains the EU *sui generis* database right, which protects the
investment in compiling a database even where the individual facts are public. US law has no
equivalent; there, facts are not protectable and compilations get thin protection.

**Ask, both directions:**
- **Against us:** does the database right make it unlawful to extract price or reference data from
  another compiler's database — including free sources whose terms are vague — in a way that would
  be lower risk in the US? We assume yes and have ruled out scraping on that basis.
- **For us:** do *we* acquire a database right in our own lake, given the substantial investment in
  obtaining, verifying and presenting it? If so, what do we need to do to be able to assert it, and
  what should our terms say?

## 4. UK GDPR — the one most easily missed

**What we do.** Insider-dealing forms (SEC Forms 3, 4 and 5) name real individuals: a named officer
or director, their role, the shares they bought or sold, the price, and how many they hold
afterwards. We plan to publish these as a card per person, with a chart of that person's holding
over time. Institutional filings (13F) name fund managers. This is personal data about identifiable
living individuals, published by a UK company.

**Ask:**
- What lawful basis applies — legitimate interests, or something else? The source is a public
  register in another jurisdiction, which is not automatically a basis under UK GDPR.
- Do we owe these individuals a privacy notice, given we never collect the data from them?
- What do we do with an erasure or objection request from a named director? We cannot alter the
  filing, and the filing is the evidence — but we control our copy and our presentation of it.
- Does building a per-person holding history over time change the analysis? It is profiling in
  ordinary language, if not necessarily in the regulation's.
- Do we need to register with the ICO, and what does our record of processing need to cover?
- Separately and more routinely: subscriber data, cookies and analytics, and our privacy policy.

## 5. FCA perimeter — where information becomes advice

**What we do today.** Publish factual financial information as filed, with search, comparison and
export. We make no recommendations.

**What we may do.** Screening and ranking (e.g. sort companies by a metric), alerts, and a "quality"
or coverage signal. Internally we run arithmetic checks on filings; these are deliberately *not*
shown to users.

**Ask:**
- Is publishing factual financial information a regulated activity? We assume not, and want that
  confirmed rather than assumed.
- Where is the line between a screener and investment advice or a personal recommendation? What
  specifically must we avoid — ranking, scoring, "top picks", anything with a buy/sell shape?
- Does the financial promotions regime apply to how we *market* the product, separately from what
  the product does?
- Do any disclaimers need to appear, and where?

## 6. Index and classification licensing

**What we want.** To say a company is in the S&P 500, and to show a sector for each company.

**What we believe.** Index membership as a labelled fact needs a licence from the index owner (S&P
Dow Jones Indices, FTSE Russell). GICS is owned by MSCI and S&P and must be licensed. We have free
alternatives — a fund's published holdings as a proxy for membership, and SIC codes plus our own
mapping for sector — and intend to use those.

**Ask:**
- Is using an index fund's published daily holdings as an internal proxy for index membership a
  breach of anything, if we never display the index name?
- If we later want to display "member of the S&P 500", what does that licence involve?
- If we publish our own sector classification, derived from public SIC codes and our own judgement,
  do we need anything? Can we say it is "not GICS" without inviting a problem?
- If we ever publish a ranking that behaves like an index, does the UK Benchmarks Regulation bite?

## 7. Our own terms, and what happens when a number is wrong

**The exposure.** We publish financial figures that people may rely on. Our position is that every
number is what the company filed, and that the filing sits underneath it. But we will get something
wrong eventually — a parsing error, a missed line, a stale period.

**Ask:**
- What do our terms of service need to say about accuracy, reliance and liability, and how much of
  that is enforceable against a business customer versus a consumer?
- We will show some values that are *derived* rather than filed — for example figures read from
  pre-2009 filings that carry no machine-readable tags, and our mapping of differently-named line
  items onto a common name. We intend to label them as derived wherever they appear. Is labelling
  enough, and what should the label say?
- Do we need professional indemnity insurance, and at what level?

## 8. Selling to customers

- **Consumer contracts:** if we sell to individuals, what do the Consumer Contracts Regulations
  require — 14-day cancellation, information before purchase, auto-renewal disclosure?
- **B2B terms** as a separate set, and which we default to.
- **VAT** on digital subscriptions to UK, EU and US customers.
- **Payments:** obligations that come with the payment processor.

## 9. Ownership of the work itself

- Who owns the code and the data pipeline, given more than one person is contributing and there is
  no company agreement yet in place. Founders' IP assignment, and contributor arrangements for
  anyone helping who is not a founder.
- Whether anything we have built is patentable or worth protecting, or whether the answer is simply
  keep it confidential and move fast.
- Trade mark on the product name, once the domain is bought.

## 10. Where the data physically sits

- Cloudflare R2 and Render both need a documented answer on the region data is stored and processed
  in, for the GDPR record and for the privacy policy.
- Whether any transfer mechanism is needed for personal data leaving the UK.

## Decisions waiting on these answers

| Blocked | On |
|---|---|
| Buying a price feed at all | §2 redistribution clause |
| Publishing insider cards with named individuals | §4 lawful basis and erasure |
| Building a screener or ranking | §5 perimeter |
| Displaying index membership or a sector label | §6 |
| Launching to paying customers | §7 terms, §8 consumer rules |

Until §2 is answered, no price vendor is engaged and no price data enters the lake. Until §4 is
answered, insider data stays an internal capability and is not published with names.
