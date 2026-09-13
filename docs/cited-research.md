# Cited questions, evidence and saved research

Baseline: merged main/PR20 `bde7f83b56833e9d00ea29ee4e1a95ec79ae8776`, retaining PR19 draft/context fixes and the separate administration console. This release connects selected public SEC documents to bounded questions, exact evidence inspection, deterministic arithmetic and authorized project artifacts. It is not a general research agent, licensed-content platform or AlphaSense parity claim.

## What happens in one run

1. A signed-in user selects companies and/or immutable document versions and a UTC-day cutoff. Combining companies and versions uses their intersection. Source filing date **and original capture date** must be on or before the cutoff; a later capture of an old filing cannot rewrite a historical answer. Company scope picks the newest eligible capture per document; explicit versions preserve the user's choice.
2. Retrieval admits only sources whose current document and captured version are both public SEC records. At most 500 captured versions and 5,000 spans may enter the selected scope. Larger scopes fail with instructions to narrow them, rather than silently dropping text.
3. The configured retrieval mode returns at most 12 passages. Hybrid mode combines exact lexical overlap with cosine similarity and reciprocal-rank fusion over fully prepared embeddings for the explicitly selected scope. It uses durable per-model vectors and a bounded local exact scan, not a corpus-scale approximate-nearest-neighbor service. Lexical reranking sends at most 24 deterministic candidates to the configured language model and returns at most 12; cover-page candidates preserve reporting-period context and remaining candidates use lexical ranking. This mode is explicitly labelled; it is not exhaustive semantic retrieval.
4. A structured draft can use only supplied passage IDs. Each quotation must match an exact contiguous substring. A separate model call reviews support and possible contradictory passages. Invalid source IDs/quotes withhold the answer; rejected claims remain absent. Missing evidence and conflicts remain explicit. Both calls treat source text and questions as untrusted data, with no tools, web search, executable code or external browsing.
5. Every released claim is labelled **machine-assessed**. An exact quote verifies location, not entailment or factual truth. A second call to the same model is not independent factual validation. The analyst must inspect source context and qualifications.
6. The user may select two complete signed number literals (including Unicode minus), explicitly supply matching units and request sum, difference, ratio or growth. Decimal arithmetic uses 50 significant digits. The API rechecks exact offsets, entire-number boundaries and units; it rejects zero denominators and never guesses period/metric comparability, FX conversion or accounting meaning. Up to ten calculations attach to an unsaved run.
7. Saving attaches the immutable question, scope, cutoff, passages, claims and calculations to an authorized project. It is a separate machine-research artifact, not a user-authored note. Project members may read it only while current project and all underlying source permissions still allow access. Follow-ups create linked runs with the same explicit scope and cutoff. Prior question and claim text supplies conversation context only; only newly retrieved exact passages are admissible evidence.

## Evidence and historical preservation

Version IDs bind raw bytes to the canonical document ID. Projection IDs bind that immutable capture to an extractor version and exact projected text. Span IDs include projection identity and start/end offsets in Unicode code points. Browser inspection re-fetches both the span and full immutable projection and refuses to highlight a mismatch. Original URLs and both raw-version/projection identities remain inspectable.

The v2 extractor excludes hidden iXBRL headers, head/scripts/styles/forms and explicitly hidden HTML subtrees. Older stored extracted versions are not overwritten. When original raw bytes are available and hash-verified, preparation creates a new immutable v2 text projection; older cited spans remain resolvable. Ordinary lexical search over old v1 captures retains its original index text until separately reconciled. PDF text pages retain offsets; scanned/image-only/encrypted PDFs and OCR remain unsupported and inventoried.

## Provider configuration and cost bounds

Research is disabled by default. Secrets stay in server environment, never browser bundles, committed examples or source prompts. Configure a provider only after an operator verifies its account/model access and permitted source processing. `research_provider_readiness` is an explicit deployment gate, not a self-certifying live health probe.

For the xAI account actually tested on 13 September 2026:

```text
RESEARCH_ENABLED=true
RESEARCH_PROVIDER=xai
RESEARCH_PROVIDER_READINESS=ready
RESEARCH_RETRIEVAL_MODE=lexical_rerank
RESEARCH_XAI_MODEL=grok-4.20-0309-non-reasoning
RESEARCH_XAI_EMBEDDING_MODEL=
```

Supply `XAI_API_KEY` separately through protected environment/secrets. Do not use an OpenAI model/embedding ID or send this key to OpenAI. The tested account returned an empty `/v1/embedding-models` list; embedding-backed live acceptance therefore remains unavailable. The optional OpenAI adapter has separate key/model configuration and was verified with mocked transport, not live credentials in this release.

xAI's official [Responses API](https://docs.x.ai/developers/rest-api-reference/inference/responses) and [structured-output documentation](https://docs.x.ai/developers/model-capabilities/text/structured-outputs) support the shape used here. Requests specify `store:false`, structured JSON schema and disabled truncation; they omit tools and hosted search. Embedding entitlement is checked separately from inference; an [embedding endpoint](https://docs.x.ai/developers/rest-api-reference/inference/embeddings) existing does not mean a model is available to an account. `store:false` is a request setting, not a claim of zero provider retention or contractual data governance.

Each user has 20 attempted runs per UTC day, including failures. A run has at most three provider calls; requests cap serialized input at 100 KB and output at 1,800 tokens (support review 1,400). No automatic billed retries occur. Idempotency is durably reserved before calling the provider; a lost response can retrieve/reuse the same run without another call. A running record abandoned for five minutes becomes failed on read. Provider errors expose no raw account response or prompt. Reported token usage is retained; unreturned failed-call usage is labelled unknown. Set an actual provider spending cap before deployment—these limits are not a currency budget, pricing quote or billing system.

The live acceptance was stricter: five authorized calls total, each capped at 10,000 serialized input characters and 1,000 output tokens. Two calls in the first attempt withheld an answer; three in the second produced one exact Apple reporting-date answer. Total reported use was 7,575 input and 674 output tokens. No further calls were made. This does not validate the larger default retrieval window, broad answer accuracy or investment conclusions. See `research-validation.md`.

## API and privacy contract

- `GET /research/capabilities`: provider status, workflow availability/reason, corpus counts, bounds and limitations.
- `POST /research/runs`: `{question,ciks,version_ids,as_of,parent_run_id?,idempotency_key}`. Status is `running`, `completed`, `insufficient_evidence`, `conflicting_evidence` or `failed`.
- `GET /research/runs/{id}`: owner-private until project save; rechecks project membership and every retrieved source, including uncited candidates.
- `POST /research/runs/{id}/calculations`: explicit operation, two `{span_id,start,end,unit}` operands and idempotency key.
- `POST /research/runs/{id}/save`: `{project_id}`; creator-only mutation, immutable after save.
- `GET /projects/{id}/research-runs`: currently authorized artifact summaries.
- `GET /research/spans/{id}` and `/research/projections/{id}`: exact public source text and immutable metadata, with current/captured public-source checks.

The Next gateway allowlists routes, forwards the existing signed session and server key, requires matching origin for mutations and disables private caching. No shared answer cache or private source index exists. Provider access is rechecked at each source-transmission boundary. The system cannot retract text already disclosed before a later rights change.

Browser flow: `/research/ask` → inspect exact source → choose numbers → calculate → save project → reopen artifact. Account/run-scoped tab recovery preserves question, source/cutoff scope, follow-up identity and the pending idempotency key across source navigation, browser Back and reload. The server rechecks access before mounting recovery; local labels are not evidence of source authorization. Identical retries reuse the same request key. Tab closure recovery is not promised; blocked browser storage is disclosed. Existing PR19 note recovery remains intact. The existing project JSON download contains notes/references, not these new machine-research artifacts; artifact export/deletion workflows remain planned.

## Release verification

On the combined merged PR20 base, all 513 Python tests passed with real PostgreSQL and zero skips; 37 frontend unit tests, production build, Ruff lint/format and production dependency audit passed. All eight cited-research and six administrator browser scenarios passed after integration. The prior 26 ordinary browser scenarios passed before the final administration merge and rerun with the complete suite in GitHub CI. Three independently reproduced issues—accidental company submission, follow-up draft loss through source navigation, and Unicode-minus sign loss—have focused API/unit/browser regressions. These checks use an explicitly synthetic provider and corpus; original-source and bounded live-provider validation are described separately above. The final GitHub results and reviewed browser artifacts are attached to [PR21](https://github.com/g784dwcd2r-crypto/H/pull/21).
