# Source-provider readiness packet

Prepared 13 September 2026 for full-plan workstreams D02, D03, D04, D08, D16 and D20. This is a
requirements packet for source assessment, adapters and launch acceptance. It does not select a
supplier, obtain rights, buy content, send outreach, or certify a deployment. No provider pricing is
assumed. It complements `docs/full-platform-plan.md`, `filings_hub/platform/catalog.py` and the
identity/grant contracts in `filings_hub/platform/contracts.py`.

The present implementation has SEC ingestion and public SEC research-index support. Other premium,
global, expert, market and private-content families in the source register are `provider_required`.
That status does not mean their adapters, entitlements or operating workflows already exist.
Internal connectors are also future software work. Public availability and possession of an API
credential do not establish all the intended storage, AI, export or redistribution rights.

## One assessment record per source and intended use

Create a versioned assessment containing:

| Field group | Required contents |
|---|---|
| Identity and accountability | Source ID, provider/source owner, dataset/product, territory, proposed audience, accountable operator, assessment date and reviewer |
| Scope | Issuer/security identifiers, countries, languages, document/event types, historical depth, expected universe, exclusions, update/correction policy |
| Use rights | Storage, indexing, embeddings, AI input/output, snippets, display, derived data, user/team sharing, download/export, API/MCP, offline use, retention and termination |
| Entitlements | Organization and user grants, product bundle, per-seat/system restrictions, embargoes, external sharing, permitted subprocessors/regions and revocation mechanism |
| Commercial inputs | Actual quote reference, minimums, usage/seat fees, redistribution charges, overages, term/renewal, permitted pilot, service commitments and exit costs |
| Technical inputs | Approved endpoint/feed/channel, schema/version, authentication, sandbox, bulk/history access, incremental cursor, timestamps, limits, retry rules and support escalation |
| Evidence | Agreement or documented source assessment reference, approved operations, sample inventory, acceptance results, credential owner, rollout/rollback and next unresolved dependency |

Treat pricing and source-volume cells as unknown until supported by an actual dated source or quote.
Compare providers against the same declared issuer/event cohort, language coverage, history and
operations; a lower headline price for materially different rights is not an equivalent offer.

Track external and software readiness separately:

| Dimension | States and meaning |
|---|---|
| External access/rights | `assessment_required`; `provider_required`; `terms_under_review`; `authorized_for_pilot`; `authorized_for_production`; `expired_or_revoked` |
| Credentials | `not_provisioned`; `sandbox_only`; `production_provisioned`; `invalid_or_revoked` |
| Software | `not_implemented`; `adapter_fixture_verified`; `sandbox_verified`; `production_observed`; `disabled` |
| Assurance | `not_assessed`; `deployment_controls_verified`; `independent_assessment_pending`; `independently_assessed_for_stated_scope` |

These are proposed assessment-workflow fields, not new states already implemented in the public
catalog. Keep a source unavailable while any requirement for its intended operation is unmet.
Fixture success never advances rights or credentials. A signed agreement never advances adapter
verification. Explicitly distinguish "needs a provider agreement" from "we have not built this yet."

## D02: SEC and additional public disclosure channels

**External requirements.** Record the regulator/exchange/issuer channel, permitted acquisition and
downstream uses, historical access, rate/fair-access requirements and contact/account prerequisites.
Assess third-party exhibits separately where their intended use requires it. For each new market,
identify the primary publication channel and the authoritative amendment/correction relationship;
do not assume a universal API or that another site's aggregation may be redistributed.

**Software requirements.** SEC work includes timely event discovery, daily reconciliation, complete
exhibit inventories, source timestamps and a review queue. Each additional jurisdiction needs its
own adapter, local form/language mapping, issuer/security reconciliation, calendar handling,
document versions, extraction/OCR and coverage reporting. Original text stays accessible alongside
any translation; translation is a derived representation with its own version and quality status.

**Acceptance packet.** Choose a declared cohort including co-filers, ticker changes, foreign SEC
registrants, fiscal transitions and amendments. Reconcile expected publications and all supported
attachments against the primary source. Replay duplicate, delayed, corrected and withdrawn events.
Measure source publication-to-index latency during real reporting activity and record missing
cases. SEC software does not establish coverage of a foreign registrant's domestic regulator.

**Current gap.** Broader public-source adapters and their source assessments remain unimplemented
or unconnected; credential/access requirements depend on the channel. SEC production completeness
and timeliness still require deployment-specific observation. Source-assessment starting point:
[SEC access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data).

## D03: Earnings transcripts and audio

**External requirements.** Obtain a declared event/company/language universe; rights for live audio,
transcription, corrected/final text, timestamps, excerpts, playback, search, AI, export and retention;
entitlement restrictions; and actual delivery/availability terms. Specify what happens to cached
audio, transcripts and derived outputs when rights end.

**Software requirements.** Build event-to-issuer mapping, live/revised/final version states, speaker
roles, prepared remarks versus Q&A, audio/text alignment, reconnect/backfill and change propagation.
Guidance/KPI extraction must distinguish management statements, analyst questions and model
interpretations. A raw transcript's provisional status must survive search, notes and exports.

**Acceptance packet.** Reconcile an earnings-event calendar against received audio/text; exercise
overlapping speakers, delayed starts, interrupted streams, corrected numbers and final revisions.
Verify representative speaker/timestamp alignment and restrictions across playback, search and
exports. Measure delay against the actual source event, not merely the ingestion job's start time.

**Current gap.** Provider access, approved uses and credentials are external prerequisites. The
live-event/transcript adapter, version UI, extraction and monitoring workflows also need building.

## D03: News, broker research and specialist content

**External requirements.** Assess news/trade publications, broker/independent reports, industry and
credit research, and specialist regulatory/clinical/sustainability datasets separately. Obtain the
actual entitlement model, publication embargoes, permitted audiences/operations, corrections,
retractions and availability on termination. A broker report accessible to one user must not become
accessible to an entire organization through a summary or shared note.

**Software requirements.** Build provider connectors, per-user/firm entitlements, source-aware
retrieval, embargo timing, article/report identity, corrected versions and duplicate-story grouping.
Carry permissions into snippets, cached answers, grids, notifications and future exports. Specialist
datasets additionally require domain entities, units, statuses and change semantics; a PDF importer
alone is not a clinical-trial or credit-research workflow.

**Acceptance packet.** Use a rights-approved corpus with ordinary, embargoed, restricted, corrected
and withdrawn items. Verify that users with different subscriptions receive different permissible
results, including after revocation and in derived artifacts. Reconcile source inventories and
measure missed/duplicate updates. For specialist structured data, independently check entity,
status, effective/publication dates and numerical units.

**Current gap.** Premium content rights and credentials are not acquired. Provider adapters,
production grant enforcement and these specialist workflows remain software dependencies.

## D04: Expert libraries, interviews and channel checks

**External requirements.** A qualified network/library relationship must define expert identity,
relevant experience, screening, conflicts/restricted-information review, consent, recording,
transcript availability, permitted distribution and actual fees. Identify who handles questions,
complaints and restricted-content escalation. Library reuse, bespoke calls, AI-led interviews and
recurring channel-check programs can require different terms and operating controls.

**Software requirements.** Build briefs, selection/screening, scheduling, consent records, call
status, transcript/audio ingestion, review status and project-linked evidence. Recurring channel
checks need stable question definitions, cohort/participant metadata, dates and longitudinal grids.
AI-led calls come after the approved interview/review process works; scheduling or paying for a call
must require the appropriate explicit authority. No invented expert or synthetic conversation is
represented as an actual interview.

**Acceptance packet.** Run agreed pilot calls with consenting counterparties and complete records;
test withdrawn consent, failed recordings, review holds and restricted distribution. Check repeated
questions across changing cohorts without implying statistical representativeness. Interview
interpretations must retain conflicting evidence and the context of the expert's experience.

**Current gap.** Network participation, expert consent and accountable review require real
counterparties. Library/call/channel-check software is also unimplemented. Agent-built code does
not substitute for those participants or for independent review required by the operating model.

## D08: Prices, corporate actions, FX, estimates and ownership

**External requirements.** Obtain product-specific market/reference-data rights, venue and delay
terms, contributor/consensus scope, covered history, adjustment methodology and the allowed use of
derived results. Confirm display/non-display, exports, APIs and redistribution for the actual target
users. Record identifiers and their licensing/redistribution conditions separately where applicable.

**Software requirements.** Reconcile issuer versus security/share-class/listing; timestamps,
currency/FX basis, splits/dividends, raw versus adjusted prices, fiscal period mapping, estimate
revisions/dispersion and contributor coverage. Keep reported actuals, management guidance,
consensus and analyst assumptions separate. Ownership needs holdings and disclosure dates,
amendments and overlapping reporting entities; it is not a live position feed.

**Acceptance packet.** Independently validate a defined sample spanning splits, multiple listings,
ADRs, negative values, FX changes, fiscal transitions and estimate revisions. Confirm correct
look-back availability rather than applying today's consensus to a historical question. Reconcile
ownership overlaps and late amendments. Test stale feeds, entitlement expiry and provider outage.

**Current gap.** No production market/consensus feed or rights are established here. Reference-data,
action-adjustment, consensus and ownership adapters/semantics also need implementation; existing
SEC financial statements do not fill these gaps.

## D08: Private companies, funding and M&A

**External requirements.** Define regional/company/deal coverage, identity sources, update cadence,
verification status, historical availability and permitted profiles, screening, AI and exports.
Request clear methods for estimated figures and correction/dispute handling.

**Software requirements.** Distinguish announced, revised, closed and terminated deals; enterprise
value from equity value; stake from consideration; round size from pre/post-money valuation; and
reported from estimated operating metrics. Resolve subsidiary and investor identities and preserve
source confidence. Undisclosed values remain unavailable.

**Acceptance packet.** Reconcile deals with changing terms, cancelled transactions, multi-tranche
funding, currencies and duplicate announcements. Verify that missing values are not silently
estimated and announcement dates do not become completion dates. Test historical queries and
correction propagation into profiles, screens and saved work.

**Current gap.** Provider agreement/access and coverage validation are external dependencies;
private-market schemas, adapters, matching, screens and change workflows are still software work.

## D16: Customer internal systems

**External requirements.** Obtain the customer's authorization, tenant/account ownership,
administrator consent where needed, supported deployment/security requirements and credentials
for the selected system. Define processing/subprocessor regions, retention/deletion, model-data
use and contractually required assurance. Actual customer permission is separate from a generic
connector implementation or access to publicly available provider documentation.

**Software requirements.** Build uploads and selected drive/document integrations before widening
to email, CRM and other repositories. Every connector needs selective sync, cursor recovery,
versioned documents, malicious-file handling, folder/item permission inheritance, group/user
mapping, deletion propagation, disconnect/reauthorization and visible sync failures. Tenant
membership is necessary but does not replace the source system's document ACLs.

**Acceptance packet.** Use a consenting test tenant with overlapping groups, restricted folders,
shared links, moved/deleted documents and departing employees. Revoke access during queued jobs
and verify retrieval, caches, grids, notifications and future artifacts no longer expose content.
Exercise interrupted synchronization and permission recovery without widening access. Record
which independent deployment controls or assessments remain outstanding.

**Current gap.** Organizations/roles/projects exist as a foundation. Internal connectors, SSO/SCIM,
document ACL propagation and private-source retrieval are not completed by those tables. Customer
credentials, administrative consent and independent assurance remain external gates.

## D20: Commercial and release decision

For each proposed bundle, attach the source assessments, real quotes, known software work, expected
usage envelope and operational ownership. Calculate cost with actual minimum/seat/usage terms plus
storage, indexing, OCR/audio, inference, delivery, support and migration. Keep fixed commitments
separate from per-account costs. Do not promise unlimited research, worldwide coverage or an SLA
before costs, rights and observed service behavior support it.

A source's release packet must contain: approved scope/uses; provisioned credentials without
secrets in source control; replayable adapter fixtures; independent cohort reconciliation; tested
entitlement/deletion behavior; observed delivery/quality evidence; support/incident contacts;
rollout/rollback; and customer-facing limitations. Independent assessments are performed by the
appropriate external parties and described only for their actual scope.

Enable only the approved operations and cohorts. On expiry, revocation, failed access or delivery
failure, show an unavailable/stale/partial state with a reason. Do not substitute another provider,
private source or generated estimate silently. Customer migration covers their own portable notes,
watchlists, mappings and permitted references; it does not imply ownership of an incumbent's library.

The immediate deliverable is a reviewable, evidence-filled assessment for each priority source and
an implementable adapter backlog. Signing agreements, supplying credentials, arranging experts,
observing real reporting events and commissioning independent assurance are explicitly different
tasks from writing the software. None is marked complete by this packet.
