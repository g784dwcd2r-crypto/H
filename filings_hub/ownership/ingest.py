"""Bounded, replayable forward ingestion. Discovery and successful parsing are separate checkpoints."""

from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import urlsplit

from filings_hub.ingest.documents import parse_filing_index
from filings_hub.ingest.edgar_client import EdgarClient, EdgarMissing
from filings_hub.ownership.parse import normalize_form, parse_filing

FORMS = frozenset(
    f + suffix
    for f in ("3", "4", "5", "13F-HR", "13F-NT", "SC 13D", "SC 13G", "SCHEDULE 13D", "SCHEDULE 13G")
    for suffix in ("", "/A")
)
MAX_DOCUMENT_BYTES = 12 * 1024 * 1024
MAX_FILING_BYTES = 32 * 1024 * 1024
MAX_DOCUMENTS = 24
ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")
FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,220}$")


def filing_metadata(filer_cik: int, accession: str, form: str, filed_date: str) -> dict:
    """Accept identifiers, never a caller-supplied fetch URL."""
    if not 0 < int(filer_cik) < 10**10 or not ACCESSION.fullmatch(accession):
        raise ValueError("A valid filer CIK and dashed SEC accession are required")
    form = " ".join(form.upper().split())
    if form not in FORMS:
        raise ValueError("Unsupported ownership form")
    return {
        "filer_cik": int(filer_cik),
        "accession": accession,
        "form": normalize_form(form),
        "filed_date": date.fromisoformat(filed_date).isoformat(),
        "source_url": EdgarClient.filing_index_url(int(filer_cik), accession),
    }


def parse_index(text: str) -> list[dict]:
    """Master indexes use both ISO and compact dates. Do not checkpoint malformed ownership rows."""
    if "CIK|Company Name|Form Type|Date Filed|Filename" not in text:
        raise ValueError("Not a SEC daily master index")
    rows = {}
    for line in text.splitlines():
        parts = line.strip().split("|")
        if len(parts) < 3 or " ".join(parts[2].upper().split()) not in FORMS:
            continue
        if len(parts) != 5:
            raise ValueError("Malformed ownership daily-index row")
        cik, name, form, filed, path = parts
        match = re.fullmatch(r"edgar/data/(\d+)/(\d{10}-\d{2}-\d{6})\.txt", path)
        if not match or match[1] != str(int(cik)):
            raise ValueError("Invalid SEC ownership filing path")
        row = filing_metadata(int(cik), match[2], form, date.fromisoformat(filed).isoformat())
        row["filer_name"] = name.strip()
        rows[(row["filer_cik"], row["accession"])] = row
    return list(rows.values())


def _download(client: EdgarClient, url: str, max_bytes: int) -> bytes:
    with client.stream(url) as response:
        target = urlsplit(str(response.url))
        if target.scheme != "https" or target.hostname != "www.sec.gov":
            raise ValueError("Unexpected SEC document redirect")
        data = bytearray()
        for chunk in response.iter_bytes():
            data.extend(chunk)
            if len(data) > max_bytes:
                raise ValueError("Ownership document exceeds the bounded download limit")
        return bytes(data)


def fetch_documents(client: EdgarClient, metadata: dict) -> list[dict]:
    meta = filing_metadata(metadata["filer_cik"], metadata["accession"], metadata["form"], str(metadata["filed_date"]))
    html = _download(client, meta["source_url"], 2 * 1024 * 1024).decode("utf-8", errors="replace")
    inventory = parse_filing_index(html)
    selected = []
    seen = set()
    for item in inventory:
        filename = item.get("filename") or ""
        if not FILENAME.fullmatch(filename) or ".." in filename or filename in seen:
            continue
        doc_type = (item.get("doc_type") or "").upper()
        primary = normalize_form(doc_type) == meta["form"]
        is_xml = filename.lower().endswith(".xml") and not filename.lower().startswith("filingsummary")
        exhibit = doc_type.startswith("EX-") and filename.lower().endswith((".htm", ".html", ".txt", ".pdf"))
        if is_xml or primary or exhibit:
            selected.append(item)
            seen.add(filename)
    if len(selected) > MAX_DOCUMENTS:
        raise ValueError("Ownership filing exceeds the document-count limit; operator review required")
    if not any(item["filename"].lower().endswith(".xml") for item in selected):
        if any(
            normalize_form(item.get("doc_type") or "") == meta["form"]
            and item["filename"].lower().endswith((".htm", ".html", ".txt"))
            for item in selected
        ):
            raise UnsupportedFiling("Identified non-XML primary filing; legacy text retained in coverage")
        raise ValueError("Incomplete ownership document inventory; retained for retry")
    documents = []
    total = 0
    for item in selected:
        filename = item["filename"]
        url = EdgarClient.primary_doc_url(meta["filer_cik"], meta["accession"], filename)
        content = _download(client, url, min(MAX_DOCUMENT_BYTES, MAX_FILING_BYTES - total))
        total += len(content)
        documents.append({**item, "content": content, "source_url": url})
    return documents


class UnsupportedFiling(ValueError):
    """An observation that is explicitly outside this XML pipeline, not an empty portfolio."""


def process_filing(store, client: EdgarClient, metadata: dict) -> dict:
    metadata = filing_metadata(
        metadata["filer_cik"], metadata["accession"], metadata["form"], str(metadata["filed_date"])
    )
    store.register_filing(metadata)
    try:
        if metadata["form"].startswith("13F-NT"):
            raise UnsupportedFiling("13F notice filing: no position table, not a zero portfolio")
        documents = fetch_documents(client, metadata)
        parsed = parse_filing(metadata["form"], documents, metadata)
        return store.ingest(parsed, documents)
    except UnsupportedFiling as exc:
        store.record_failure(metadata, str(exc), status="unsupported")
        return {"status": "unsupported", "accession": metadata["accession"]}
    except Exception as exc:
        # Queue retention is the retry mechanism. One bad filing cannot discard the rest of a date.
        store.record_failure(metadata, str(exc)[:1000])
        return {"status": "failed", "accession": metadata["accession"], "error": str(exc)[:1000]}


def sync_ownership(
    store,
    client: EdgarClient,
    *,
    since: date | None = None,
    until: date | None = None,
    index_date: date | None = None,
    max_days: int = 7,
    max_filings: int = 50,
) -> dict:
    """A repeatable worker invocation. Dates are complete only after every row is durably queued.

    Without --since the first run begins yesterday, with no historical backfill. Subsequent runs
    advance the same cursor. Explicit --date safely replays one daily index without moving it.
    Run a single scheduler for discovery; store ingestion itself is idempotent.
    """
    if not 1 <= max_days <= 31 or not 1 <= max_filings <= 500:
        raise ValueError("max_days must be 1..31 and max_filings must be 1..500")
    if index_date and since:
        raise ValueError("Use either index_date or since")
    end = until or (date.today() - timedelta(days=1))
    if (since and since > end) or (index_date and index_date > end):
        raise ValueError("Ownership discovery requires a completed index date")
    key = "discovery:" + (since.isoformat() if since else "forward")
    state = store.get_state(key) or {}
    day = index_date or date.fromisoformat(state.get("next_date") or (since or end).isoformat())
    if not index_date and not state:
        store.set_state(key, {"next_date": day.isoformat()})
    result = {"discovered": 0, "parsed": 0, "failed": 0, "unsupported": 0, "dates": [], "errors": []}
    for _ in range(1 if index_date else max_days):
        if day > end:
            break
        if day.weekday() < 5 and not store.get_state(f"skip-date:{day}"):
            try:
                try:
                    text = client.fetch_daily_index(day)
                except EdgarMissing:
                    text = None
                if text is None:
                    result["errors"].append(f"{day}: daily index unavailable; retained for retry")
                    break
                for metadata in parse_index(text):
                    store.register_filing(metadata)
                    result["discovered"] += 1
            except Exception as exc:
                result["errors"].append(f"{day}: {str(exc)[:500]}")
                break
        result["dates"].append(day.isoformat())
        day += timedelta(days=1)
        if not index_date:
            store.set_state(key, {"next_date": day.isoformat()})
    for metadata in store.pending(limit=max_filings):
        record = process_filing(store, client, metadata)
        result[record["status"]] += 1
        if record.get("error"):
            result["errors"].append(f"{record['accession']}: {record['error']}")
    result["coverage"] = store.coverage()
    result["status"] = "partial" if result["errors"] else "ok"
    return result
