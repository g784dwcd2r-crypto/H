"""Explicit, bounded SEC document indexing. Never called from a user search request.

Run ``python -m filings_hub.research_ingest`` repeatedly to advance durable discovery cursors.
Without --fetch, only already cached filing documents are read; missing documents remain pending.
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import PurePosixPath
from typing import Any

from filings_hub.db.database import Database
from filings_hub.ingest import documents
from filings_hub.ingest.edgar_client import EdgarClient
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage
from filings_hub.reader import html_to_text
from filings_hub.research_index import ResearchIndex, now, open_index

MAX_BYTES = 25 * 1024 * 1024
MAX_TEXT = 2_000_000
MAX_PDF_PAGES = 1000
TEXT_EXTENSIONS = {".htm", ".html", ".txt", ".xhtml"}


class ExtractionError(ValueError):
    pass


class UnsupportedDocument(ExtractionError):
    pass


def extract(raw: bytes, filename: str) -> tuple[str, list[dict[str, int]]]:
    """Text PDFs retain page offsets. Empty/scanned pages are not a successful complete extraction."""
    if len(raw) > MAX_BYTES:
        raise ExtractionError("Document exceeds the 25 MiB extraction limit; no text was indexed.")
    suffix = PurePosixPath(filename).suffix.lower()
    pages = []
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise UnsupportedDocument("Encrypted PDF requires a separate supported extraction workflow.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ExtractionError("PDF exceeds the 1,000 page extraction limit; no pages were silently omitted.")
        texts, offset = [], 0
        for number, page in enumerate(reader.pages, 1):
            contents = page.get_contents()
            if contents is not None and len(contents.get_data()) > MAX_BYTES:
                raise ExtractionError(f"PDF page {number} exceeds the decoded stream limit.")
            text = page.extract_text() or ""
            if not text.strip():
                # A blank page may be intentionally blank or scanned. Without a visual/OCR check we cannot tell.
                raise UnsupportedDocument(
                    f"PDF page {number} has no extractable text; OCR or blank-page review needed."
                )
            if offset + len(text) > MAX_TEXT:
                raise ExtractionError("Extracted document exceeds 2 million characters; no partial text was indexed.")
            pages.append({"page": number, "start": offset, "end": offset + len(text)})
            texts.append(text)
            offset += len(text) + 2
        text = "\n\n".join(texts)
    elif suffix in TEXT_EXTENSIONS:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
        if suffix != ".txt":
            text = html_to_text(text)
    else:
        raise UnsupportedDocument(f"{suffix or 'Unknown format'} is inventoried but has no supported text extractor.")
    if not text.strip():
        raise ExtractionError("Document contains no extractable text; no empty successful index entry was created.")
    if len(text) > MAX_TEXT:
        raise ExtractionError("Extracted document exceeds 2 million characters; no partial text was indexed.")
    return text, pages


def discover_batch(
    database: Database,
    storage: Storage,
    index: ResearchIndex,
    *,
    limit: int = 25,
    cik: int | None = None,
    client: EdgarClient | None = None,
) -> dict[str, Any]:
    if not 1 <= limit <= 500:
        raise ValueError("filing batch size must be 1–500")
    scope = str(cik) if cik is not None else "all"
    cursor = index.meta(f"discovery:{scope}:cursor")
    where, params = [], []
    if cik is not None:
        where.append("f.cik=?")
        params.append(cik)
    if cursor:
        where.append("(f.cik>? OR (f.cik=? AND f.accession>?))")
        params += [cursor["cik"], cursor["cik"], cursor["accession"]]
    clause = " WHERE " + " AND ".join(where) if where else ""
    filings = database.query(
        "SELECT f.cik,f.accession,f.form,f.filed_date,f.items,f.primary_doc,c.name company_name "
        "FROM filings f LEFT JOIN companies c ON c.cik=f.cik" + clause + " ORDER BY f.cik,f.accession LIMIT ?",
        [*params, limit + 1],
    )
    index.meta(f"discovery:{scope}:complete", False)
    more = len(filings) > limit
    filings = filings[:limit]
    cache: dict[int, list[dict]] = {}
    registered = 0
    for filing in filings:
        company, accession = int(filing["cik"]), filing["accession"]
        index.register_filing(filing)
        if company not in cache:
            cache[company] = documents.read_documents(storage, company).to_pylist()
        known = [doc for doc in cache[company] if doc["accession"] == accession]
        index_path = f"research/inventories/{company}/{accession}.html"
        inventory_status, error = "pending", "Only the legacy cached inventory is known; full bundle not verified."
        try:
            html = storage.read_text(index_path) if storage.exists(index_path) else None
            if html is None and client is not None:
                html = client.get(documents.filing_index_url(company, accession)).text
                if documents.parse_filing_index(html):
                    storage.write_text(index_path, html)
            if html is not None:
                rows = documents.parse_filing_index(html)
                if not rows:
                    raise ExtractionError("Filing index contains no parseable document inventory.")
                known = documents.documents_table(
                    company, accession, filing.get("form") or "", filing.get("items"), filing.get("primary_doc"), rows
                ).to_pylist()
                inventory_status, error = "complete", None
        except Exception as exc:  # one failed bundle is counted and cannot abort the rest of the bounded batch
            inventory_status, error = "failed", f"Inventory extraction failed ({type(exc).__name__})."
        if filing.get("primary_doc") and not any(doc["filename"] == filing["primary_doc"] for doc in known):
            known.append({"filename": filing["primary_doc"], "label": filing.get("form") or "Primary filing"})
        for doc in known:
            try:
                index.register_document(filing, doc)
                registered += 1
            except ValueError:
                inventory_status, error = "failed", "Inventory contains an invalid source document identifier."
        index.inventory_status(company, accession, inventory_status, error)
    next_cursor = {"cik": int(filings[-1]["cik"]), "accession": filings[-1]["accession"]} if more else {}
    index.meta(f"discovery:{scope}:cursor", next_cursor)
    index.meta(f"discovery:{scope}:complete", not more)
    index.meta(f"discovery:{scope}:at", now())
    return {
        "filings_registered": len(filings),
        "documents_registered": registered,
        "discovery_complete": not more,
        "next_cursor": next_cursor or None,
    }


def index_documents_batch(
    storage: Storage,
    index: ResearchIndex,
    *,
    limit: int = 100,
    cik: int | None = None,
    client: EdgarClient | None = None,
    retry_failed: bool = False,
    recheck_indexed: bool = False,
) -> dict[str, int]:
    if not 1 <= limit <= 500:
        raise ValueError("document batch size must be 1–500")
    statuses = ["pending"]
    if retry_failed:
        statuses += ["failed", "unsupported"]
    if recheck_indexed:
        statuses += ["indexed"]
    where = "status IN (" + ",".join("?" for _ in statuses) + ")"
    params: list[Any] = list(statuses)
    if cik is not None:
        where += " AND cik=?"
        params.append(cik)
    pending = index.query(
        "SELECT * FROM research_documents WHERE source_id='sec-edgar' AND visibility='public' AND "
        + where
        + " ORDER BY CASE WHEN attempted_at IS NULL THEN 0 ELSE 1 END,attempted_at,document_id LIMIT ?",
        [*params, limit],
    )
    counts = dict(attempted=len(pending), indexed=0, failed=0, pending=0, unsupported=0)
    for doc in pending:
        document_id, filename = doc["document_id"], doc["filename"]
        try:
            if PurePosixPath(filename).suffix.lower() not in TEXT_EXTENSIONS | {".pdf"}:
                raise UnsupportedDocument("Inventory item has no supported text extractor (images/XBRL/binary files).")
            rel = layout.raw_document(doc["cik"], doc["accession"], filename)
            if storage.exists(rel):
                with storage.open(rel) as stream:
                    raw = stream.read(MAX_BYTES + 1)
            elif client is not None:
                raw = client.get(doc["source_url"]).content
                if len(raw) <= MAX_BYTES:
                    storage.write_bytes(rel, raw)
            else:
                index.document_status(document_id, "pending", "Source bytes are not cached; run indexing with --fetch.")
                counts["pending"] += 1
                continue
            text, pages = extract(raw, filename)
            index.add_version(storage, document_id, raw, text, pages)
            counts["indexed"] += 1
        except UnsupportedDocument as exc:
            index.document_status(document_id, "unsupported", str(exc))
            counts["unsupported"] += 1
        except Exception as exc:
            message = str(exc) if isinstance(exc, ExtractionError) else f"Extraction failed ({type(exc).__name__})."
            index.document_status(document_id, "failed", message)
            counts["failed"] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filings", type=int, default=25, help="maximum filings to discover in this batch (1–500)")
    parser.add_argument("--documents", type=int, default=100, help="maximum documents to extract (1–500)")
    parser.add_argument("--cik", type=int)
    parser.add_argument("--fetch", action="store_true", help="explicitly fetch SEC indexes and uncached documents")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--recheck-indexed", action="store_true", help="check cached source bytes for new versions")
    args = parser.parse_args()
    from filings_hub.config import get_settings
    from filings_hub.ingest.edgar_client import client_from_settings

    settings = get_settings()
    storage = Storage(settings.resolved_lake_root())
    database = Database(settings.database_url, storage)
    index = open_index(storage, settings.database_url or "")
    client = client_from_settings() if args.fetch else None
    try:
        discovery = discover_batch(database, storage, index, limit=args.filings, cik=args.cik, client=client)
        extraction = index_documents_batch(
            storage,
            index,
            limit=args.documents,
            cik=args.cik,
            client=client,
            retry_failed=args.retry_failed,
            recheck_indexed=args.recheck_indexed,
        )
        print(json.dumps({"discovery": discovery, "extraction": extraction, "coverage": index.coverage(cik=args.cik)}))
    finally:
        if client:
            client.close()
        index.close()
        database.close()


if __name__ == "__main__":
    main()
