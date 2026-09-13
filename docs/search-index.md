# Durable SEC research search

This release adds a **lexical document index**, not semantic search or an AI answer engine. It searches
public SEC content explicitly registered and extracted into this deployment. A search request does
not contact EDGAR, fetch a filing, or read raw lake documents.

## API and query contract

`GET /research/search?q=...&cik=...&form=...&from=YYYY-MM-DD&to=YYYY-MM-DD&limit=20&offset=0`

Company, exact form (including `/A`) and inclusive filing-date filters are optional. CIK is numeric.
Dates refer to filing dates, not financial periods. Search is case-insensitive **whole-word** matching:
`risk` does not match `risks`. Adjacent words mean AND. Uppercase `NOT`, `AND`, `OR` are operators,
in that precedence order; parentheses override precedence. Lowercase `and` is searched literally.
Quoted phrases require adjacent word tokens. Punctuation and line breaks separate tokens:
`"non-GAAP"` and `"non GAAP"` match the same phrase. There is no stemming, synonym expansion, regex,
wildcard or implicit semantic inference.

```text
"material weakness" AND NOT remediation
(liquidity OR "debt covenant") AND restructuring
NOT (dividend OR repurchase)
```

Malformed queries return 422 rather than silently changing meaning. Limits: 1,000 query characters,
64 terms/operators, 12 nesting levels, 16 words per phrase and 100 characters per query word. Empty
queries return coverage and zero matches. `limit` is 1–100; offset is nonnegative. `total` is the exact
matching document count and `next_offset` advertises another page. Ordering is filing date descending,
then CIK and stable document ID. There is no hidden result cap. Counts and a page read one database
snapshot. Separate pagination requests may change when an index update arrives; this release does
not pin a multi-request research snapshot.

Results include `document_id`, `version_id`, `cik`, `accession`, `filename`, `title`, optional
`company_name`, `form`, `filed_date`, `source_url` and a **plain-text** context snippet. A snippet is an
excerpt, not the complete hit set. It is never HTML and must not be rendered as trusted markup.
`GET /research/documents/{version_id}` returns immutable `text_content`, content hash, source metadata,
indexing time, extractor version and PDF page text offsets when known. HTML has no invented page
references. The original SEC document remains authoritative for layout, tables and accounting context.

## Scope and completeness

Coverage reports `indexed`, `failed`, `pending`, `unsupported`, `total`, `filings_known`,
`inventories_complete`, `inventories_pending`, `inventories_failed`, `discovery_complete`,
`last_discovery_at`, `last_indexed_at` and `partial`. These are **registered-corpus** counts after the
same public-source and metadata filters as search. They are not a claim to have all EDGAR documents.
A completed discovery pass reflects that pass's source database and timestamp.

The worker inventories every document in a fetched filing index, including related exhibits,
supplements, graphics and XBRL/support files. Unsupported formats remain counted. Legacy cached
inventories cannot establish completeness because older ingestion could save a primary-only fallback;
they remain pending until the full index is parsed. Failed/malformed inventories are counted separately.
Invalid identifiers keep their inventory failed. Missing source bytes remain pending. Failed
fetches/extraction never become successful empty documents. Pure-NOT queries complement only eligible
indexed documents, excluding missing/failed documents. No match is not proof of no disclosure.

Only `source_id='sec-edgar'` and `visibility='public'` records are admitted, before matching, results,
counts and version retrieval. Other sources/private rows cannot enter through this worker. These
guards are not a completed licensed-content or private-corpus authorization system; those sources
need grants and tenant-aware ingestion.

## Storage and indexing

Migration `0009_research_index.sql` adds inventories, document states, immutable versions, token
positions and discovery metadata. Production uses Postgres; local development uses
`research/search.sqlite3` under the local lake, with WAL transactions. A remote lake requires Postgres.
The real inverted index is `research_terms(term, version_id, position)`. Both backends share Unicode
word tokenization and parameterized Boolean compilation. Positions are not truncated at a full-text
engine's position ceiling; phrases beyond the 16,383rd word are regression tested.

Document IDs use the shared SEC contract. Version IDs hash document identity and original bytes;
original SHA-256 is also recorded. Source bytes are saved under `research/versions/`; text and metadata
are not replaced on reindex. Default search uses the current successfully indexed version; old
versions remain addressable with current access checks. A failed recheck removes a document from
default matching until repaired, rather than presenting an old extraction as current. Updating
extractor semantics requires a separately versioned extraction migration; identical bytes do not
silently rewrite previous extracted text.

Run a bounded batch using the configured lake/database:

```sh
uv run python -m filings_hub.research_ingest --filings 25 --documents 100
uv run python -m filings_hub.research_ingest --cik 320193 --fetch --filings 25 --documents 100
uv run python -m filings_hub.research_ingest --retry-failed --recheck-indexed
```

`--fetch` explicitly enables the existing SEC client and its configured identification/rate limiting.
Without it, cached raw documents are extracted. Discovery cursors advance after a bounded batch and
survive restart. At pass completion the cursor resets, allowing later passes to discover new filings.
Pending extraction selects the oldest attempt so uncached items do not permanently starve others.
A crash leaves unfinished work pending and completed versions durable. Run one discovery scheduler
per scope; this initial CLI has no distributed lease. Limits: 1–500 filings and 1–500 documents per
batch. Helper APIs are `discover_batch` and `index_documents_batch`.

HTML/plain text and text PDFs are supported. Limits: 25 MiB source bytes, two million extracted
characters, 1,000 PDF pages and a per-page decoded PDF stream bound. Exceeding limits fails the entire
document visibly; no prefix is silently indexed. pypdf is not OCR. Empty/image-only pages require OCR
or blank-page review, so mixed scanned PDFs remain unsupported. Run extraction workers with operating
system memory limits: compressed streams may allocate memory before decoded size is checked. Full
live-corpus performance and completeness have not been validated.

## Verification

`tests/test_research_index.py` covers exact words, phrases, Boolean nesting/negation, invalid syntax,
parameterized inputs, multi-company retrieval, source restrictions before counts, pagination, immutable
versions/restart, long-document phrase positions, real PDF offsets, unsupported/failed/pending states,
retry recovery, full exhibit inventory, bounded discovery, offline search and Postgres/SQLite parity.
Run with Postgres binaries on PATH so production-backend parity executes instead of skipping.

## Source version history and extracted-text comparison

`GET /research/documents/{version_id}/history?limit=20&offset=0` lists only immutable captures of that
same document, newest indexing timestamp first (version ID breaks timestamp ties). It returns
`document_id`, `current_version_id`, `versions`, `total`, `limit`, `offset`, and `next_offset`. History
items contain `version_id`, `content_sha256`, `indexed_at`, `extractor_version`, `content_bytes`, `title`,
`filename`, `source_url`, `cik`, `accession`, `form`, and `filed_date`. History contains metadata rather
than duplicating complete text bodies. These are indexing/capture timestamps; they are not asserted
SEC modification timestamps or evidence that the source changed at that exact time.

`GET /research/compare?before={version_id}&after={version_id}&context=3&max_hunks=20&max_lines=600`
compares two stored versions of **the same document**. Each version must pass the current public SEC
access filter inside one read snapshot. An absent or restricted version returns the same 404, before
checking whether document identities differ. Two accessible versions of different documents return
422; arbitrary cross-document comparisons and private/provider content are not supported. Revoking a
document's eligible source/visibility also removes its old history and comparisons from access.

The response contains `comparison: "extracted-text-v1"`, `document_id`, separate `before`/`after`
metadata objects using the history-item fields, `text_identical`, `complete`, `input_truncated`,
`output_truncated`, `total_hunks_in_compared_text`, `hunks`, `coverage`, `limits`, and `limitations`.
Each hunk includes one-based `before_start`/`after_start`, `before_count`/`after_count`, `truncated`, and
`lines`. For a zero-length insertion/deletion range, the start is the preceding line number (zero at
the start of the text). Each line has `kind: "context" | "delete" | "insert"`, nullable `before_line`
and `after_line`, and plain `text`. The text preserves extracted whitespace and line endings, so it
must be rendered as text rather than HTML. No semantic or accounting-change interpretation is made.
A distinct raw-byte version can legitimately have identical extracted text.

Comparison uses deterministic line matching, with context 0–10, 1–50 hunks, and 1–1,000 output lines.
Changed inputs are limited to the first 100,000 characters and 2,000 lines of each version; output is
also bounded to 100,000 text characters. Oversized input or omitted output is flagged explicitly,
and `complete` is false. If a character limit splits a source line, the result concerns that compared
prefix. Hunk totals apply only to the compared portion. A difference beyond the prefix can produce
zero returned hunks with `text_identical=false` and `input_truncated=true`; the UI must not label this
as “no changes.” Full equality of stored texts is checked directly, so identical large texts can
return a complete empty diff without running the bounded hunk algorithm. Returned changes are a
valid deterministic text edit description, not a guarantee of the mathematically smallest diff.

`coverage` records both total and compared character counts. `limits` records every effective limit.
A hunk cut by the output budget has `truncated=true`; even when a returned hunk is whole, later hunks
may be omitted (`output_truncated=true`). The full immutable extracted documents and original-source
links remain available for further inspection. There is no diff caching that bypasses access checks.

`tests/test_research_compare.py` verifies exact replacements and line endings, insert/delete positions,
identical extracted text with different bytes, all explicit truncation boundaries, metadata history
pagination, current checks on both versions, opaque unavailable responses, and SQLite/Postgres parity.
