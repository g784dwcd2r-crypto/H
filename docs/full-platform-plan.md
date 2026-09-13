# Disclosure: full-platform development plan

Implementation update: the bounded cited-research/indexing release is documented in [cited-research.md](cited-research.md), with [source-backed validation and unresolved gates](research-validation.md). The 170-requirement plan remains the target; these increments do not establish full platform or competitor parity.

Prepared 13 September 2026. Planning baseline: repository H at `d9e5ac949ce59fe5fd68fe0b51a0a440c2791e5a` (theme PR #17), building on merged PR #16. This document expands the earlier product-readiness plan; it does not mark the earlier production gates complete. No implementation, deployment or content purchase is performed by this planning exercise.

**1. The target and the meaning of parity**

Build a complete research platform for public-market investors, investment banks, private-market investors, corporate strategy teams and independent researchers. Match the publicly documented AlphaSense capability families, then compete on the quality of the complete research task. Audience breadth remains the ambition; releases add verified capabilities and coverage in explicit cohorts.

Full parity has four separate dimensions: usable functionality, relevant content coverage and rights, dependable operation, and successful completion of a customer's existing workflow. A feature appearing in a menu is not sufficient. Equivalent content must be acquired legally; AlphaSense-owned or exclusive collections cannot be assumed available for us to license. Any unfilled requirement remains a recorded parity gap.

Maintain a dated competitor register with source, availability, subscription/entitlement restrictions, observed behavior, Disclosure status and evidence. Public documentation cannot reveal every contractual or unreleased capability. Validate unknowns with authorized product demonstrations and consenting customer workflow inventories before making replacement claims.

AlphaSense currently groups its product around search, research, work products, internal knowledge, financial data, agents and monitoring. This is the comparison baseline, not evidence that every feature is generally available. [Platform overview](https://www.alpha-sense.com/platform/)

**2. The foundation we already have**

| Area | Current Disclosure evidence | What remains |
|---|---|---|
| Public experience | Responsive homepage, direct company search, source-backed historical example | Measured activation, clearer workflow proof and simpler working controls |
| Documents | SEC filing organization, exhibits, reader and company phrase search | Broader document inventory, indexing, exact anchors, global sources and complete-search reporting |
| Financials | As-reported statements, conservative quarterly/LTM derivation, source metadata and exports | Exact contexts across history, dimensions, revisions/as-of history and diverse independent validation |
| Personal workflow | Accounts, preferences, watchlists, alert controls and export profiles | Production acceptance, projects, organizations, reliable delivery and migration |
| Engineering | CI, database tests, recovery checkpoints and browser acceptance | Atomic publication, production restore/freshness evidence, capacity and institutional controls |

The independent real-data sample checks 40 selected annual observations from two issuers. The local browser preview uses synthetic workspace data. Neither establishes broad universe coverage or operational reliability. The controlling evidence is in the repository's financial methodology, real-data acceptance, recovery and release-readiness documents.

**3. The delivery rules**

Use five statuses: planned; implemented; verified against independent evidence; production-validated; generally available for a stated scope. Keep code status separate from source acquisition and operational status. A blocked content agreement does not become a completed feature because its adapter works with fixtures.

Retain the current Next.js, Python API, Postgres and raw analytical lake unless a measured requirement demands a change. Add services behind explicit contracts: source adapters, durable jobs, lexical/vector retrieval, model/tool execution and notifications. Avoid a wholesale rewrite while the team is still validating data semantics.

The common contracts are: permanent issuer/security identities; immutable document versions; exact financial observations; source grants; research artifacts/citations; tenant identities and access policies; versioned jobs/events; usage records. Every substantive PR names the affected contracts, dependencies, evidence and rollback.

**4. The complete capability backlog**

The IDs below are workstream IDs. Each item within a workstream becomes a bounded issue/PR packet with its own acceptance cases. These are proposed Disclosure requirements, not claims that AlphaSense lacks them.

| ID | Workstream | Delivery route | First release wave |
|---|---|---|---|
| D01 | Identity, evidence and rights | Build core; reference feeds where justified | R1 |
| D02 | SEC and global public documents | Build adapters; permitted feeds/partners | R1-R2; further cohorts R5 |
| D03 | News, transcripts and premium research | License/partner plus ingestion | Acquisition starts R0; delivery R3-R5 |
| D04 | Expert library and call services | Partner first; build workflow | R5 |
| D05 | Document processing and reader | Build | R2 |
| D06 | Trusted financial observations and history | Build core | R1-R2 |
| D07 | Segments, KPIs and industry packs | Build plus curated feeds | R2-R3 |
| D08 | Markets, estimates, holdings and private data | Primarily license feeds; build semantics | R3-R5 |
| D09 | Screeners, comparisons and charts | Build on validated datasets | R3 |
| D10 | Excel refresh and model library | Build; license input data | R3 onward |
| D11 | Search and cited questions | Build on permissioned evidence | R2-R4 |
| D12 | Research grids, deep research and agents | Build orchestration and evaluations | R4; persistent execution R6 |
| D13 | Monitoring and portfolio dashboards | Build; event feeds where required | R2-R3 |
| D14 | Projects, collaboration and work products | Build | R3-R4 |
| D15 | Office assistants and linked presentations | Build integrations | R4-R6 |
| D16 | Enterprise identity and internal connectors | Build; provider integration contracts | Identity R1; connectors R3-R5 |
| D17 | APIs, external integrations and mobile | Build | APIs R2; mobile R3-R5 |
| D18 | Product experience and accessibility | Extend existing design | Every wave |
| D19 | Operations, security and assurance | Build controls; independent assessment | R1 onward |
| D20 | Commercial service, support and migration | Build tooling plus commercial operations | R0 research; paid pilots R3 onward |

**D01 — A common identity, evidence and permissions foundation.**

Add permanent issuer IDs independent of ticker/CIK, historical names and listings, subsidiaries, share classes, securities, ADR relationships, mergers and identifier mappings. Keep a security distinct from its issuer. Resolve conflicts visibly rather than guessing.

Record document owner, source ID, publication/acceptance time, discovery time, content hash, language, source URL, document type, versions and extraction method. Attach observations and citations to a particular immutable document version. Store business-effective dates separately from when information became public and when Disclosure received it.

Create a source-grant register for storage, search, embeddings/AI use, snippets, display, redistribution, downloads, offline storage, retention and termination. Enforce grants through indexes, retrieval, derived artifacts and new exports. Record what an authorized download permitted; do not claim the platform can recall files already lawfully downloaded to an external device.

Exit evidence: historical ticker changes do not merge unrelated companies; duplicate/corrected documents resolve correctly; expired grants disappear from future retrieval; cross-tenant and revoked-user tests pass across search, caches and artifacts.

**D02 — Public filings and worldwide coverage.**

Complete the SEC document universe relevant to customer jobs: financial reports, releases, material announcements, all relevant exhibits, proxy materials, prospectuses, registrations, merger documents, ownership and insider disclosures. Treat SEC foreign registrants separately from coverage of their domestic regulator.

Add issuer presentations, earnings supplementals and investor-relations material where acquisition and use are permitted. Introduce timely event discovery alongside daily reconciliation; distinguish source publication, document availability, extraction completion and verified financial availability.

Candidate expansion waves are UK/European disclosures, Canada and Australia, then Japan, Hong Kong, Singapore, India and additional markets including Korea, Brazil and mainland China subject to customer demand and access feasibility. Each regulator, exchange and issuer channel needs its own source assessment. No assumed universal API or scraping permission.

Each cohort includes original-language retrieval, searchable translation, local forms, fiscal calendars, currency, accounting standards, amendments and source-linked originals. Publish company/document/period coverage and known omissions. AlphaSense documents global filing coverage; our implementation must earn coverage market by market. [Global filings overview](https://help.alpha-sense.com/hc/en-us/articles/41913107681043-Global-Filings-Content-Overview)

Exit evidence: a verified source register, a representative independent sample, reconciled document inventories and observed event latency through reporting activity. A ticker count never substitutes for filing completeness.

**D03 — Earnings calls, news and premium research.**

Run separate acquisition tracks for earnings transcripts/audio, news and trade journals, broker/independent research, industry and credit research, expert transcript libraries, and specialist content such as clinical-trial, regulatory and sustainability material. These remain full-scope requirements even where commercial terms are unresolved.

Transcript capabilities include event calendars, live/revised/final versions, speaker roles, prepared remarks versus Q&A, audio timestamps, topic navigation, guidance extraction, searchable translations and comparisons over time. Preserve version changes so a live transcription error does not silently become permanent evidence. [Transcript versions](https://help.alpha-sense.com/hc/en-us/articles/41916900552595-Event-Transcripts-Content-Overview)

Broker integration needs individual and firm entitlements, embargo/release timing, coverage dates and downstream-use controls. News requires correction/retraction handling, duplicate-story grouping and publisher attribution. Licensed access is not a right to redistribute the full provider library to everyone. [Broker entitlement model](https://help.alpha-sense.com/hc/en-us/articles/41919784082323-Broker-Research-Content-Overview)

Exit evidence: signed rights for the intended uses, sample reconciliation, acceptable delivery performance, permission tests and a sustainable quote. A live feed must disclose unavailable events and provisional text.

**D04 — Expert research as a service.**

First integrate a licensed expert library and a qualified network partner. Build project briefs, expert discovery, relevant relationships, screening questions, selection, availability, scheduling, fees, consent, recording, transcripts, review status, project summaries and follow-up requests.

Add AI-led interviewing only after this operating model works. The interview must identify itself, follow the agreed research scope and route restricted or questionable material for the required review. Qualified experts, conflicts screening and accountable review cannot be replaced by fabricated conversations. AlphaSense's documented AI-call process still includes human and automated review. [AI-led calls](https://help.alpha-sense.com/hc/en-us/articles/49288197594515-AI-Led-Expert-Calls)

Add a recurring channel-check program: consistent questions, qualified expert cohorts, interview dates, source-linked responses and longitudinal comparisons of demand, pricing, inventory and supply conditions. Connect reviewed calls to typed grids and dashboards. Record cohort changes, contradictory responses and sample limits; repeated interviews do not automatically form a representative survey. This depends on D04 consent/review, D07 definitions and D12 grids. [Channel-check baseline](https://www.alpha-sense.com/solutions/channel-checks/)

Exit evidence: partner agreement, operational ownership, verified expert/consent records, tested review and restricted-content handling, clear costs and permitted distribution. No autonomous call or payment merely because a research agent suggested it.

**D05 — A research-grade document engine and reader.**

Handle HTML, inline XBRL, PDF, scans, tables, spreadsheets, presentations and permitted audio. Add OCR, section hierarchy, table structure, reading order, footnotes and stable paragraph/table/cell/audio anchors. Retain original documents beside extracted representations and flag extraction uncertainty.

Index embedded figures and charts as searchable evidence, including captions, axes, units and original page locations. Return the original image beside any extracted interpretation; visually estimated values must not silently become reported financial observations. Test figures whose decisive information is absent from surrounding text. [Image-search baseline](https://www.alpha-sense.com/solutions/competitive-intelligence-for-leading-corporations/)

Upgrade the reader with search highlighting, next/previous result, linked footnotes, compare versions, synchronized source/evidence panels, selected-text questions, annotations, bookmarks and permitted table copy/export. Preserve table units, headers and footnotes when copying.

Exit evidence: difficult scans, multicolumn reports, multi-page tables and amended documents retain accurate reading order and anchors; a citation opens the actual supporting passage; malformed content cannot execute in the reader.

**D06 — Trusted financials, exact history and revisions.**

Extend the observation model with exact contexts, dimensions, raw reported precision, units, currencies, dates, original labels and transformation versions. Use source-precision-aware decimal handling. Keep reported, normalized, calculated, guidance, consensus and analyst estimates separate.

Support annual, quarterly, YTD, LTM, fiscal transitions and 52/53-week calendars under written methods. Provide original filing, latest presentation and known-as-of views. Record the reason for a change only when evidence supports it; do not infer a formal restatement from a changed comparative column.

Repair historical inferred contexts through controlled reconciliation. Add amendment chains, duplicate-context handling, accounting-policy changes, discontinued operations, currency changes and per-share/corporate-action semantics. Publish metric-level availability and validation status.

Exit evidence: broaden independent source expectations from the current two-issuer sample to at least 30 deliberately diverse issuers plus edge cases, followed by stratified ongoing checks. Verify periods, values, source anchors, calculations and exported results independently. Reproduce a historical research cutoff without later-publication leakage. Passing a sample is scoped assurance, not a universal accuracy percentage.

**D07 — Segments, company KPIs and industry packs.**

Ingest XBRL dimensions and tables from notes, supplementals, releases and presentations. Keep segment hierarchies and their history; show changed definitions rather than stitching incompatible series together. Store non-GAAP reconciliations and company-defined formulas separately from standardized metrics.

Develop packs for banks, insurance, REITs, software/SaaS, retail/consumer, industrials, energy/mining, utilities, airlines/hotels, telecom and life sciences. Examples include net interest income, loss ratios, FFO/AFFO, retention, same-store sales, backlog, production, occupancy, ARPU and development milestones. Each metric needs a definition, scope, period and evidence; matching names do not establish comparability.

Exit evidence: reconcile reported/managed bank measures, acquisitions within growth rates, changing SaaS definitions and reorganized segments. Peer rankings must disclose incompatible or missing observations.

**D08 — Market, consensus, ownership, deals and private-company data.**

Evaluate licensed feeds for prices, corporate actions, FX, estimates, reference data, ownership, private companies, M&A and funding. Build the reconciliation and analytical layer rather than attempting to recreate broad exchange feeds or broker consensus from filings alone.

Prices need time, delay, venue, currency and adjustment basis. Consensus needs period/basis mapping, contributor coverage, revisions and dispersion. Keep management guidance separate. Ownership distinguishes holdings dates from disclosure dates, amendments and overlapping reporting entities; it is not a live portfolio feed.

Private-company profiles combine verified identity, financial/funding history, ownership, workforce and source confidence. Deals distinguish announced, revised, closed and terminated states; enterprise/equity value, consideration and stake. Funding distinguishes round size from pre/post-money valuation. Missing or undisclosed figures remain missing.

This covers the broader financial-data categories AlphaSense advertises, while exact provider coverage remains an acquisition requirement. [Financial-data scope](https://www.alpha-sense.com/platform/financial-data/)

Exit evidence: correct splits and FX; no double-counted holdings; no announced deal shown as completed; no round amount displayed as valuation; documented fiscal/basis alignment for estimates and actuals.

**D09 — Screening, comparisons and interactive analysis.**

Build saved universes, editable peer sets, sector templates, custom columns, filters, sorting, distribution/percentile views, historical charts and exports. Include fundamental, valuation, growth, profitability, liquidity, leverage, quality, ownership and covered KPI screens. Add private-company, funding and M&A screens after the corresponding data gates.

Show period alignment, definitions, currency choices, exclusions and coverage denominators. Negative denominators and unavailable values need explicit treatment. Natural-language screen requests compile to inspectable deterministic filters. Historical screens use historical constituents and information availability.

Exit evidence: independent recomputation of selected comps; stable company/security mapping; no zeros manufactured from blanks; no future information in an as-of screen. [Industry comparison baseline](https://help.alpha-sense.com/hc/en-us/articles/42489594638995-Industry-Comps)

**D10 — Excel connection and a maintainable model library.**

First add stable metric IDs and versioned queries to the existing exporter. Then create a supported Excel add-in for formula pulls and mapping data into existing workbooks. Provide cell-level sources, refresh previews, accepted/rejected changes, preserved formulas and assumptions, stale/offline states, mapping history and rollback.

Build linked financial models with revenue/segment drivers, margins, working capital, debt/interest, tax, cash, dilution and share count. Add DCF, scenario, sensitivity, LBO and transaction templates where inputs are available. Maintain company-specific/sector models through filing changes; generated files are not a maintained library by themselves.

Visually and structurally separate reported historicals, management guidance, consensus, analyst assumptions and generated placeholders. Define supported workbook structures and Windows/Mac/web compatibility; do not promise arbitrary workbook updates.

AlphaSense already documents financial formulas and model-refresh tools, so this is core parity work. [Excel solutions](https://help.alpha-sense.com/hc/en-us/articles/51437573696915-Excel-Add-In-Solutions), [model capabilities](https://help.alpha-sense.com/hc/en-us/articles/42489711231763-Canalyst-Models)

Exit evidence: refresh an analyst-modified workbook across earnings, an acquisition and a segment change; preserve custom formulas/formatting/overrides; independently recalculate in supported Excel environments; undo returns to the prior model version.

**D11 — Complete search and cited questions.**

Replace on-demand limited phrase scanning with indexed documents and versioned chunks. Support exact/Boolean/proximity queries, company/sector/source/date/form/language filters, semantic matches, synonyms, selected-document search and cross-company/portfolio search. Make query scope and incomplete retrieval visible, including failed, pending and excluded documents.

Add conversational questions with follow-ups, exact supporting citations, selected source sets and historical cutoffs. Use deterministic tools for financial arithmetic and counting. Separate retrieved evidence from interpretation and label unsupported, conflicting or insufficient answers. Recheck permission on retrieval, output and citation opening.

Exit evidence: held-out analyst query judgments, search recall/false omissions, source support and negative-query cases; no hidden failed-document coverage. Test adversarial document instructions and cross-account leakage. A generated answer must never imply an exhaustive search when scope is partial. [Search interaction baseline](https://help.alpha-sense.com/hc/en-us/articles/41666587181203-Interacting-with-Generative-Search)

**D12 — Research grids, deep research, workflow agents and persistent execution.**

Research grids apply typed questions across companies, documents and periods, retaining source spans, definitions, missing/conflicting states, analyst overrides and change-only refresh. Deterministic calculations handle counts and arithmetic. [Grid baseline](https://help.alpha-sense.com/hc/en-us/articles/41680141048979-Leveraging-Generative-Grid)

Deep research starts with an editable brief, scope, time cutoff, budget and evidence plan. It performs multi-step retrieval, tests counterarguments, computes with tools and produces a report plus evidence ledger. Include progress, partial results, cancellation, checkpoints, version history and a reproducible source set.

Offer prebuilt earnings, company-ramp, industry, competitive, guidance, credit-risk, M&A and investment-committee workflows. Add reusable custom templates, typed inputs, organization libraries, schedules, triggers and run histories. Rights and budgets apply on every run. [Custom/scheduled agents](https://help.alpha-sense.com/hc/en-us/articles/48564685232275-Custom-and-Scheduled-Workflow-Agents)

Persistent execution comes last: user-controlled memory, ongoing thesis tracking, event-triggered updates, sandboxed code, model/memo/deck revisions and reviewed actions. Keep memory scoped to a project/tenant, inspectable and deletable. Research content cannot authorize instructions or external actions. AlphaSense's SuperAnalyst is a moving comparison target with documented limitations, so maintain an availability register. [SuperAnalyst FAQ](https://help.alpha-sense.com/hc/en-us/articles/53911346856851-SuperAnalyst-FAQs)

Exit evidence: blind review of complete assignments, contradictory evidence and unsupported claims; no future-source leakage; reproducible calculations; cancelled/retried jobs do not duplicate mutations; clear action history, bounded spend and recoverable artifact edits.

**D13 — Monitoring, alerts and portfolio dashboards.**

Extend watchlists to company/sector/topic/portfolio dashboards, saved searches and event inboxes. Monitor filings, amendments, guidance, KPIs, transcripts, licensed news and thesis-relevant changes. Let users configure widgets, materiality rules, time zones, quiet hours, digests, acknowledgement, pinning and review state.

Add sentence-level transcript sentiment, management-tone changes and topic trends with cited passages, transparent model versions and uncertainty. Separate prepared remarks from Q&A and compare like-for-like periods; tone is an analytical interpretation, not a proven predictor of returns. [Sentiment baseline](https://help.alpha-sense.com/hc/en-us/articles/41711901352211-Sentiment-Analysis)

Use canonical event IDs and transactional queues for delivery. Display publication/discovery/processing/notification times separately. Distinguish a new document from a supported interpretation of what changed. Handle replayed events, corrected documents, duplicate stories, opt-outs and delayed ingestion. [Dashboard baseline](https://help.alpha-sense.com/hc/en-us/articles/41809206884243-Leveraging-and-Customizing-Your-Dashboard)

Exit evidence: replay a real event set and account for every expected event, duplicates and omissions. Prove delivery and pause/unsubscribe behavior, then observe real source-to-user latency during an earnings cycle.

**D14 — Research workspaces, collaboration and publishable outputs.**

Add projects with curated documents, notes, highlights, saved searches, grids, model snapshots, thesis records and decision history. Introduce team folders, comments, assignments, review requests, approved artifacts and controlled sharing. New evidence should create a reviewable revision rather than silently rewriting approved conclusions.

Generate editable company briefs, earnings notes, initiation reports, investment-committee memos, diligence packs, comparison tables and presentations from reusable firm templates. Support Word, PDF, PowerPoint and spreadsheet outputs with visible dates, sources and calculation evidence. [Workspace baseline](https://help.alpha-sense.com/hc/en-us/articles/51087728136979-Getting-Started-with-Workspaces)

Exit evidence: permissions on source and derived work; correct rendering, units and citations; attribution/history survives export where supported; concurrent edits do not lose analyst work.

**D15 — Office assistants and linked presentations.**

After reliable Excel refresh, add assisted model editing, formula explanations, scenario creation and change proposals inside Office. Add a PowerPoint assistant for sourced slides, firm templates, charts/tables linked to model versions and refreshable evidence. Preserve notes, master slides, formatting and user edits. Show a preview and support undo for material edits.

Separate reliable financial-data add-ins from AI assistants in our own roadmap. AlphaSense's current Office documentation includes beta/availability restrictions, including an AI Excel assistant not yet generally available in setup guidance. [Office deployment guide](https://help.alpha-sense.com/hc/en-us/articles/50684671343763-AlphaSense-for-PowerPoint-and-Excel-IT-Admin-Guide-Centralized-Deployment)

Exit evidence: independently calculated scenarios; correct formula dependencies; supported-platform round trips; one changed assumption updates only intended cells/charts/slides; rollback restores the prior version.

**D16 — Enterprise identity and internal knowledge.**

Introduce tenant organizations, membership, roles, groups, invitations, ownership transfer, session/device revocation and audit events in R1. Add SAML/OIDC SSO, SCIM lifecycle, service accounts and policy administration before a buyer-dependent enterprise launch.

Deliver uploads and selected Google Drive/SharePoint integrations, then Box, Egnyte, S3, email and CRM according to verified requirements. Each connector needs selective sync, malware handling, retries, versions, permission mapping, deletion propagation, status, disconnect and reauthorization. Uploaded business documents require the same extraction and evidence model as public content.

Permission filtering must cover lexical/vector indexes, reranking, snippets, summaries, grids, caches, notifications and newly generated outputs. Revoked documents must not survive in an accessible summary merely because the original link is blocked. [Integration security baseline](https://www.alpha-sense.com/security/integration-security/)

Exit evidence: tenant/group/shared-link adversarial tests; rapid permission changes and employee departure; safe connector failure/restart; accurate deletion and retention behavior. Contractual isolation and residency promises require deployment-specific proof.

**D17 — Public APIs, integrations and mobile.**

Expose versioned company, document, search, financial, citation, job and export interfaces. Add scoped credentials, service accounts, quotas, pagination, stable identifiers, signed webhooks, a sandbox, SDK examples, changelogs and deprecation policy. Offer MCP through the same access/entitlement layer; it is an interface, not a bypass. AlphaSense also documents APIs and a beta MCP connector. [Developer platform](https://developer.alpha-sense.com/), [MCP](https://developer.alpha-sense.com/agent-api/mcp/overview)

Integrate approved notification channels and customer systems with explicit delivery configuration. Mobile starts with responsive source reading, search, dashboards and jobs; progress to installable access and native iOS/Android where notifications, offline work and distribution justify them. Include offline documents only where rights permit, synchronized notes and account-safe local storage.

Exit evidence: token/permission tests, compatible API upgrades, webhook retries/signature validation, offline/reconnect conflicts, logout clearing account content, correct deep links and licensing-compliant offline expiry. [Mobile baseline](https://help.alpha-sense.com/hc/en-us/articles/42253345516435-AlphaSense-on-iOS)

**D18 — A coherent professional experience.**

Keep the near-white/deep-ink/royal-blue direction. Build navigation around Home/Today, Search, Companies, Screener, Research, Models and Settings as those capabilities become real. Do not show empty destinations as completed features.

Simplify the statement toolbar to period mode, visible periods, units and export; put persistence scope, formatting and advanced preferences behind View settings. Add command search, keyboard navigation, pinned headers/labels, resizable panels, density controls, sensible defaults, clear loading/error/partial states and source-context continuity.

Use first-run onboarding based on companies and an actual task. Make coverage, timestamps and source quality easy to inspect without overwhelming the main screen. Test keyboard, screen readers, zoom, reduced motion, contrast and responsive layouts.

Exit evidence: first-time users complete company-to-source-to-output tasks without coaching; advanced users can work efficiently with the keyboard; no lost state, inaccessible controls or undisclosed missing data.

**D19 — Reliability, security and accountable operation.**

Publish compatible data snapshots atomically, use one ingestion owner per lake, retain replayable raw inputs and support rollback. Move production multi-user writes to Postgres with migrations and isolation. Add durable queues, idempotency, transactional notification outboxes, monitored retries and quarantine for bad data.

Add infrastructure as code, staging, secret management, encryption, backups, restore drills, least privilege, vulnerability handling, incident ownership, status reporting, audit logging, retention/deletion and model/subprocessor disclosures. Add independent penetration testing and formal assurance where target buyers require it; certification is externally assessed, not generated by an agent. [Security baseline](https://www.alpha-sense.com/security/)

Measure availability, interactive latency, freshness, completeness and financial correctness independently. Initial targets to validate: p95 warm search under 1 second; common company views under 2 seconds; ordinary exports under 5 seconds on declared dataset/concurrency; 99.9% monthly interactive availability; account-data RPO at most 1 hour and RTO at most 4 hours. Intraday sources need a separately agreed source-to-index budget, provisionally 5 minutes where provider terms support it. Define fast-query classes, cold-start behavior and provider-excluded time explicitly; these are proposed goals, not current guarantees.

Exit evidence: production restore/replay, load tests, corrected-source recovery, visible stale/partial states and incident drills. Commit to contractual service levels only after measured operation and affordable coverage.

**D20 — Commercial readiness, support and migration.**

Create discovery, professional and enterprise packages with separately entitled premium sources and metered expensive research. Accuracy and truthful source labeling stay consistent across tiers. Prices remain unset until provider quotes, usage measurements and willingness-to-pay evidence exist. AlphaSense's public pricing is customized, not a universal dollar benchmark. [Pricing baseline](https://www.alpha-sense.com/pricing/)

Build billing, invoices, trials, cancellation, failed-payment recovery, account administration, training, support tickets, incident escalation and service documentation. Import user-owned watchlists, notes, citation references, export profiles and workbook mappings, with conflict/ambiguity reporting. Do not assume a customer may export/rehost its incumbent's licensed library.

Give customers portable research records and a clear exit procedure. Run parallel pilots against actual incumbent tasks, record missing functionality and content, and validate a commercially acceptable offer. Service and licensing operations have named accountable owners even when agents write all software.

Exit evidence: billing/entitlement lifecycle, migrated data reconciliation, repeat real usage, supported workflows completed with fewer or no additional corrections, credible support and a sustainable contribution margin.

**5. The architecture and critical dependencies**

Retain immutable raw sources and add versioned publication manifests. The canonical entity/document/observation stores feed a permission-aware retrieval index and validated analytical views. A policy service resolves tenant, role and source grants. A job system runs ingestion, exports, grids, research and notification delivery. Research artifacts reference immutable evidence and data versions; Office and mobile consume the same APIs.

Do not build separate truth layers for the website, Excel, AI and mobile. All calculations and source metadata flow from common versioned services. Recheck entitlements when a queued job executes, when an artifact is shared and when a citation is opened.

| Dependency | Work it unlocks |
|---|---|
| Entity/security history | Global coverage, prices, estimates, holdings and deals |
| Document versions, anchors and source grants | Search, citations, AI, internal content and exports |
| Exact observation periods/dimensions | Comps, revisions, model refresh and historical analysis |
| Tenant identity and revocation | Collaboration, internal connectors, enterprise APIs and mobile sync |
| Durable jobs and atomic publication | Reliable freshness, agents, grids, alerts and recoverable updates |
| Validated metric IDs and model mappings | Excel formulas, changed-input review and linked presentations |
| Contracted content | The actual premium research experience, beyond fixture demonstrations |

**6. Release sequence**

| Wave | Deliverable | Exit gate |
|---|---|---|
| R0: scope and calibration | Dated parity register; verified current inventory; provider requirements and quote packets; architecture contracts; 3 representative task benchmarks | Supported scope and missing prerequisites are explicit; first delivery estimates calibrated from verified work |
| R1: foundations | Canonical identities/evidence/grants; tenant/session baseline; snapshot publication; historical repair plan; source-quality queue | Isolation/revocation tests, coherent snapshots, rollback and independent observation cases |
| R2: research depth | Broad SEC document handling; indexed search; financial history; initial segment packs; deterministic change review; versioned APIs | Query completeness, exact evidence, period/segment correctness and end-to-end source reconciliation |
| R3: professional workflow | Comps/screens; licensed market/consensus where ready; Excel refresh; monitoring; projects; first commercial pilot | Analysts complete earnings-to-model tasks; live freshness/delivery and workbook preservation demonstrated |
| R4: research intelligence | Cited questions, grids, deep research, reusable/scheduled agents, sourced reports and initial Office assistance | Held-out task quality, grounded outputs, cancellation/retry, historical cutoffs and artifact fidelity |
| R5: institutional breadth | Contracted premium sources; additional jurisdictions; internal connectors/SSO/SCIM; broader private/deal data; mobile and expert-service integration | Each cohort passes rights, coverage, security, operations and customer task acceptance |
| R6: persistent execution | Inspectable memory, event-driven research and reviewed model/memo/deck updates | All underlying tools reliable; bounded authority/spend; durable history and recoverable edits |

These are dependency waves, not a requirement that every source wait for an entire wave to finish. Content negotiations and security evidence begin in R0; platform controls begin in R1. Ready source cohorts can integrate sooner. Unavailable contracts stay visible on the critical path instead of blocking unrelated engineering silently.

**7. The first implementation packets**

| Packet | Outcome | Depends on |
|---|---|---|
| P01 | Freeze reviewed baseline; inventory real serving data and open release gates | Current repo and read-only deployment inventory |
| P02 | Capability/source register with status, owner, rights, coverage and acceptance fields | P01 |
| P03 | Versioned entity/document/observation/artifact/entitlement contracts | P01-P02 |
| P04 | Tenant membership, session/device revocation and audited access primitives | P03 |
| P05 | Dataset manifests, atomic publication and safe migration/rollback | P03 |
| P06 | Diverse independent golden corpus and historical context repair cases | P01-P03; separate validator |
| P07 | Durable document ingestion with extraction/anchor/failure manifests | P03-P05 |
| P08 | Indexed exact/Boolean search with complete/partial/failure reporting | P04-P07 |
| P09 | Exact financial history and original/latest/as-of retrieval | P03, P05-P06 |
| P10 | Before/after number and document change review | P07-P09 |
| P11 | Stable metric API and Excel mapping/refresh prototype | P09-P10 |
| P12 | Source discovery/processing/delivery telemetry and event inbox | P05-P07, P10 |
| P13 | Simpler statement controls and persistent evidence context | Stable P03/P09 API contracts; design can prototype sooner |
| P14 | End-to-end earnings-to-model benchmark with real analyst task scripts | P08-P13 |
| P15 | Provider comparison and contract requirement packets for transcripts, market data and research | P02; runs alongside engineering, with no purchase implied |

Each packet specifies a bounded scope, schemas/migrations, failing cases, independent expected results, test commands, resource usage, rollout and rollback. Large packets are split before assignment; one PR should not conceal an entire program.

**8. Agent delivery and review**

Use an orchestrator plus up to three simultaneous implementation/review agents in the present four-slot setup. Roles rotate: data/ingestion, financial modeling, search/AI, frontend/Office, platform/security and independent validation. Avoid two agents editing the same schema or live dataset at once; agree contracts before parallel implementation.

The author cannot be the only reviewer. Financial expected results are assembled independently from source filings. Search and AI evaluation uses held-out tasks and contradictory/missing evidence. Browser checks exercise real workflows. Release evidence records commit, dependencies, dataset version, golden cases, rendering, performance and rollback results.

Agents can implement software, adapters, tests, monitoring configuration, documentation and migration tools. Provider contracts, expert participation, independent assurance, actual customer trials and accountable incident/support ownership require real counterparties. This does not change the agent-built engineering model; it identifies external dependencies that code alone cannot satisfy.

**9. Acceptance and the replacement test**

| Category | Proposed acceptance evidence |
|---|---|
| Data correctness | Zero unexplained discrepancies in the agreed release corpus; exact provenance for supported outputs; reproducible calculations |
| Coverage | All expected documents accounted for in the tested cohort; missing, delayed and unsupported cases visible |
| Search | Held-out recall/precision judgments, failure accounting and exact passage navigation; no exhaustive claims for partial searches |
| AI | Claim-level evidence, correct units/calculations, historical cutoff, counterarguments and independent analyst task review |
| Workbooks | Supported Excel environments recalculate correctly; formulas/overrides preserved; refresh/undo tested |
| Rights/security | No unauthorized retrieval, cached text, generated output or export in the adversarial suite; revocation and deletion verified |
| Operation | Observed reporting-period latency, restore/replay, capacity and incident handling within agreed targets |
| Adoption | Real analysts complete recurring work and return voluntarily; pricing supports the actual operating model |

Set numerical AI/search thresholds from a labeled calibration set and the consequences of failure, then freeze them before the held-out evaluation. Do not manufacture impressive percentages without labels or a defined denominator. Sample-level correctness does not establish correctness across every issuer.

Run an initial pilot with 5-10 analysts using their own approved coverage lists and models through an earnings cycle; include failures and departures in the results. Compare task completion, corrections, manual cleanup, source verification, event delay and end-to-end time against their current workflow. Customers' actual AlphaSense entitlements define the replacement requirement. Cancelling the incumbent requires every mandatory workflow to be covered or an explicitly accepted gap—not merely successful use of one module.

**10. Economics, schedule and owner decisions**

Budget separately for agent implementation, hosting/database/object storage/search, content minimums and per-seat fees, market/identifier rights, inference/embedding/OCR/audio, expert services, Office/mobile distribution, independent assessments, support and migration. Build a per-account contribution model: subscription and usage revenue less licensed content, compute, delivery and servicing cost. Fixed operating costs and provider minimums remain separate. Offer expensive jobs with visible limits and budget controls; do not promise unlimited research before measuring costs.

This is a multi-release program. First calibrate on the R0/R1 contracts, one difficult financial case, one search query set and an existing-workbook update. Forecast dates from accepted work and known provider lead times, not the number of agents. The schedule must separately show engineering, licensing, assurance and live observation. A target completion date for full parity is not credible before scope/rights and resource costs are known.

Decisions to resolve before committing spend: operating/agent budget ceiling; first contracted content bundles; jurisdiction order; redistribution/internal-content policy; service/support commitments; commercial packaging and launch scope. Defaults for planning are managed shared infrastructure, no unsupported worldwide claim, no model training on private customer content without agreement, and verified cohorts expanding toward the full platform target.

**11. Features that can give Disclosure its own reason to win**

After the common platform works, prioritize: a change-impact map from filing to numbers to workbook; reproducible research snapshots; a comparability view that exposes inconsistent KPI definitions; a coverage-aware assistant that lists what it could not verify; analyst-owned mappings/assumptions with portable history; and an evidence-linked thesis log that preserves what was known at each decision.

These are proposed differentiators to validate, not assertions that competitors lack them. The product promise should follow measured performance on a complete task: new disclosure, understood changes, defensible numbers, maintained model and shareable evidence.

**12. Competitor availability register: initial exceptions**

- Financial-data formulas and Canalyst modeling tools are separate from newer AI Office assistants; do not merge their availability into one status.
- Current Office deployment guidance says the AI Excel assistant is not generally available, while related marketing describes beta assistants. Verify rollout and account access.
- Custom/scheduled agents, organization workflows and persistent SuperAnalyst behavior have different documented limits; retain separate entries.
- Some dashboard AI functionality is described as forthcoming in help documentation. Build requirements can include it, but the competitor baseline must preserve that status.
- MCP is documented as beta and its broker-content behavior has special restrictions. Do not assume a connector conveys unrestricted source access.
- Source volume, expert libraries, global coverage and financial datasets are coverage claims requiring contract- and cohort-level verification, not software feature counts.

Primary comparison sources are linked next to the relevant workstream. This register is an initial public-documentation inventory; refresh it before commercial parity claims.
