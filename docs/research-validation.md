# Research release validation and unresolved evidence

This is an evidence ledger, not an accuracy percentage. The sample was deliberately selected for diversity rather than representativeness. No production system, live backfill or user lake was changed. There are three distinct validation levels below.

## Original-source text fidelity

On 13 September 2026, an isolated lake captured **43 original SEC filings for 32 issuers**, including **11 amendments, two 10-KT transition reports, 20-F and 40-F filings**. The cohort includes banks, insurers, conglomerates, REITs, energy/utilities, airlines/hospitality, software, industrials, biotechnology, foreign registrants and smaller issuers. Non-calendar and 52/53-week reporting dates are represented.

The frozen [source manifest](validation/research-32-issuers.json) records each original SEC URL, accession, form, published/reporting date, content SHA-256 and byte count. Expected period literals were collected from the original iXBRL DEI tag using a separate standard-library HTML parser, without importing Disclosure's extractor or index. The manifest retains that original tag, context and literal. Numeric candidates retain their original tag/context/unit/scale as source witnesses; some are segment or other dimensional values and must **not** be treated as normalized consolidated revenue.

The independent expectations were frozen before the v2 extraction check. The [reproducible verifier](../scripts/validate_research_sources.py) reads retained original bytes, verifies their hash, then runs the implementation under test in a separate marked local lake. It compares the independently captured literals to the output and records immutable document/version identities. No model is invoked.

Observed result: **43/43 documents extracted and prepared, 32/32 expected reporting-date literals preserved, 28/28 available numeric candidate literals preserved**, with zero extraction exclusions. Four issuers (NextEra, Duke, Royal Bank of Canada and Regenerex) had no matching numeric candidate under the independent capture rule; those cases are explicitly unscored, not successful numeric checks. Current projections contain 13,464 spans and zero live provider embeddings. Detailed results are in [research-source-results.json](validation/research-source-results.json).

This does not validate table reconstruction, normalized statements, fiscal-period mapping, restatement accounting, XBRL dimensional interpretation, quarter/LTM derivation, earnings-release reconciliation, source completeness or cross-company comparability. An amendment's presence does not prove a financial restatement; the amendment contents must be assessed before such a conclusion.

```sh
uv run python scripts/validate_research_sources.py --raw-root /path/to/retained/original/files --lake work/source-validation
```

The verifier refuses an unrelated non-empty lake and does not fetch sources or use deployment database settings. Original raw files total approximately 209 MB and are retained locally outside git. Reviewers can reacquire the manifest URLs using permitted SEC access, retain the named source files and verify SHA-256 before rerunning. Changed source bytes are a mismatch requiring review, not automatically updated expectations.

| Issuer | Primary form | Reporting date | Captured documents | Source |
|---|---|---|---:|---|
| Apple Inc. | 10-K | 2025-09-27 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm) |
| MICROSOFT CORP | 10-K | 2026-06-30 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-20260630.htm) |
| JPMORGAN CHASE & CO | 10-K | 2025-12-31 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/19617/000162828026008131/jpm-20251231.htm) |
| BERKSHIRE HATHAWAY INC | 10-K | 2025-12-31 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/1067983/000119312526083899/brka-20251231.htm) |
| AMERICAN INTERNATIONAL GROUP, INC. | 10-K | 2025-12-31 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/5272/000000527226000023/aig-20251231.htm) |
| Prologis, Inc. | 10-K | 2025-12-31 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/1045609/000119312526051453/pld-20251231.htm) |
| PRUDENTIAL FINANCIAL INC | 10-K | 2025-12-31 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/1137774/000113777426000048/pru-20251231.htm) |
| EXXON MOBIL CORP | 10-K | 2025-12-31 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/34088/000003408826000045/xom-20251231.htm) |
| CHEVRON CORP | 10-K | 2025-12-31 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/93410/000009341026000078/cvx-20251231.htm) |
| NEXTERA ENERGY INC | 10-K | 2025-12-31 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/753308/000075330826000015/nee-20251231.htm) |
| Duke Energy CORP | 10-K | 2025-12-31 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/1326160/000132616026000014/duk-20251231.htm) |
| Tesla, Inc. | 10-K | 2025-12-31 | 2 | [Original filing](https://www.sec.gov/Archives/edgar/data/1318605/000162828026003952/tsla-20251231.htm) |
| FORD MOTOR CO | 10-K | 2025-12-31 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/37996/000003799626000015/f-20251231.htm) |
| Walmart Inc. | 10-K | 2026-01-31 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/104169/000010416926000055/wmt-20260131.htm) |
| COSTCO WHOLESALE CORP /NEW | 10-K | 2025-08-31 | 2 | [Original filing](https://www.sec.gov/Archives/edgar/data/909832/000090983225000101/cost-20250831.htm) |
| DELTA AIR LINES, INC. | 10-K | 2025-12-31 | 2 | [Original filing](https://www.sec.gov/Archives/edgar/data/27904/000002790426000013/dal-20251231.htm) |
| MARRIOTT INTERNATIONAL INC /MD/ | 10-K | 2025-12-31 | 2 | [Original filing](https://www.sec.gov/Archives/edgar/data/1048286/000104828626000007/mar-20251231.htm) |
| Snowflake Inc. | 10-K | 2026-01-31 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/1640147/000164014726000008/snow-20260131.htm) |
| Salesforce, Inc. | 10-K | 2026-01-31 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/1108524/000110852426000060/crm-20260131.htm) |
| CATERPILLAR INC | 10-K | 2025-12-31 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/18230/000001823026000008/cat-20251231.htm) |
| BOEING CO | 10-K | 2025-12-31 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/12927/000162828026004357/ba-20251231.htm) |
| PFIZER INC | 10-K | 2025-12-31 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/78003/000007800326000026/pfe-20251231.htm) |
| Moderna, Inc. | 10-K | 2025-12-31 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/1682852/000168285226000033/mrna-20251231.htm) |
| TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD | 20-F | 2025-12-31 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/1046179/000162828026025362/tsm-20251231.htm) |
| TOYOTA MOTOR CORP/ | 20-F | 2026-03-31 | 2 | [Original filing](https://www.sec.gov/Archives/edgar/data/1094517/000119312526264811/d101983d20f.htm) |
| ROYAL BANK OF CANADA | 40-F | 2025-10-31 | 1 | [Original filing](https://www.sec.gov/Archives/edgar/data/1000275/000119312525305927/d95203d40f.htm) |
| Shell plc | 20-F | 2025-12-31 | 2 | [Original filing](https://www.sec.gov/Archives/edgar/data/1306965/000162828026017024/shel-20251231.htm) |
| Alibaba Group Holding Ltd | 20-F | 2026-03-31 | 2 | [Original filing](https://www.sec.gov/Archives/edgar/data/1577552/000119312526231755/baba-20260331.htm) |
| Sony Group Corp | 20-F | 2026-03-31 | 2 | [Original filing](https://www.sec.gov/Archives/edgar/data/313838/000119312526274893/d28719d20f.htm) |
| Red Cat Holdings, Inc. | 10-KT | 2024-12-31 | 2 | [Original filing](https://www.sec.gov/Archives/edgar/data/748268/000164117225001892/form10-kt.htm) |
| REGENEREX PHARMA, INC. | 10-KT | 2025-12-31 | 2 | [Original filing](https://www.sec.gov/Archives/edgar/data/1357878/000147237526000211/ixform10kt.htm) |
| Dave & Buster's Entertainment, Inc. | 10-K | 2026-02-03 | 2 | [Original filing](https://www.sec.gov/Archives/edgar/data/1525769/000152576926000008/play-20260203.htm) |

## Bounded live provider acceptance

The funded xAI account supports inference with pinned `grok-4.20-0309-non-reasoning`; its accessible embedding-model inventory was empty. Five explicitly authorized inference calls were used, each limited to 10,000 serialized input characters and 1,000 output tokens, with `store:false`, no tools, no web search and no automatic billed retry.

- Attempt one: two calls; the application withheld the answer after exact-evidence validation. The returned model payload was not retained, so the precise invalid field/quote is unknown. Local investigation independently found hidden XBRL metadata in v1 text, motivating a new immutable clean projection, and citation IDs were constrained to the supplied enumeration. This is not proof that hidden metadata caused the first failure.
- Attempt two: three calls (relevance, draft, separate support review); one narrow Apple Form 10-K question completed: reporting date **27 September 2025**, annual report. Its exact supporting source quotation matched the immutable projection. The provider's support review is machine assessment, not an independent analyst opinion.
- Total reported use across those five calls: **7,575 input tokens and 674 output tokens**. The allowance is exhausted; no additional inference calls were made. Root's separate tiny credential probe is not included in this release's five-call allowance.

The [bounded live record](validation/live-research-acceptance.json) includes questions, source version IDs, outcome, reported usage, returned claims and limitations. Live calls used a smaller three-candidate/two-passage retrieval window. The default 24-candidate/12-passage path has fixture/software verification, not live acceptance. There is no broad answer-success rate, hallucination rate, cost forecast or customer workflow benchmark from one question.

## Held-out and adversarial work

The manifest contains a held-out source question per issuer: reporting period and annual versus transition status. These 32 model answers are **not run** because the authorized live allowance is exhausted. Their expected source literals are ready; scoring must retain unsupported/contradictory outcomes and independent analyst review instead of granting credit merely for syntactically valid citations.

The next held-out research cases are:

| Case | Required behavior | Current evidence |
|---|---|---|
| Fiscal transition mistaken for twelve-month growth | Cite transition interval; refuse an unqualified annual comparison | Two original 10-KT captures and date witnesses; semantic answer not run |
| Amendment assumed to restate earnings | Inspect amendment content; do not infer restatement from `/A` | Eleven original amendments captured; interpretation not independently scored |
| Source filed before cutoff but captured later | Exclude later capture and explain insufficiency | Local/PostgreSQL negative tests |
| Selected companies and exact versions disagree | Use intersection; no evidence outside scope | Backend scope contract; explicit version/cutoff tests |
| Apparently supportive passage plus a qualification/counterstatement | Preserve candidate context and show conflict rather than a one-sided conclusion | Deterministic provider fixture; live conflicting-answer evaluation pending |
| Unsupported future acquisition or forecast | Withhold unsupported claims | Backend and browser fixture cases; broad live unsupported-query evaluation pending |
| Document says “ignore instructions/reveal keys” | Treat as source text; no tools, credentials or operational instruction execution | Provider-boundary test, server-only credentials and quoted-data construction; adversarial live evaluation pending |
| Source restricted after retrieval or project membership revoked | Stop further provider disclosure and deny run/artifact reads, including uncited evidence | Local/PostgreSQL revocation and mid-run boundary tests |
| Concurrent/lost request or provider failure | One durable idempotent run; no automatic billed retries; known/unknown usage separated | Backend idempotency/provider tests and browser retry scenario |
| Crash/cancel during remote fetch | Stale worker cannot commit fetched bytes; registered failures remain | Local/PostgreSQL lease, concurrent claim and cancellation tests |
| Missing/corrupted old raw capture | Quarantine preparation, advance later batches, recover explicitly after restore | Local/PostgreSQL projection and restoration tests |

The synthetic preview is unmistakably labelled and uses a deterministic provider selected only by the testing server. Browser acceptance exercises actual API/session/project storage and exact source-projection reads; fixture answers are not presented as real model quality evidence. A production build is tested for question → evidence → arithmetic → project save → reopen, fixed-scope follow-up, offline retry and mobile/reduced-motion use. Existing note recovery/search-return/statement behavior from PR19 remains in the combined regression suite.

## Release gate still open

Production rollout is disabled. Remaining gates include independent financial-methodology checks over the cohort, broader held-out source questions and contradiction/injection evaluation, entitled embedding-model acceptance if semantic mode is desired, production corpus reconciliation/freshness observation, coordinated database/object restore, provider data-processing/retention approval, cost caps and deployment authentication. Some are further software/assurance work, not merely missing credentials. Buying more inference alone does not establish launch readiness.
