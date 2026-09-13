"""Exhibit-level contents of a filing, with plain names.

A 10-K or an 8-K is a bundle. The thing an analyst opens is the annual report, the press release
exhibit (EX-99.1 inside the 8-K), the investor presentation, the proxy. EDGAR lists the bundle on the
filing's index page (`{accession}-index.htm`, one table row per document: seq, description, file,
type, size); this module parses that page, names each document in plain words, and keeps the result
in `documents/cik={cik}/` so a filing is fetched from the SEC once.

Fetching is lazy (the API asks for a company's recent filings when the page is opened) and eager for
the daily refresh (new results filings and 8-Ks). Both go through `ensure_documents`.
"""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from filings_hub.ingest.edgar_client import WWW, EdgarClient, EdgarError
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage

log = logging.getLogger(__name__)

DOCUMENTS_SCHEMA = pa.schema(
    [
        ("cik", pa.int64()),
        ("accession", pa.string()),
        ("seq", pa.int32()),
        ("doc_type", pa.string()),  # EDGAR type: 10-K, EX-99.1, GRAPHIC, ...
        ("description", pa.string()),  # filer's own description
        ("filename", pa.string()),
        ("url", pa.string()),
        ("size", pa.int64()),
        ("label", pa.string()),  # plain name
        ("kind", pa.string()),  # primary | release | presentation | letter | supplement | exhibit | support
        ("is_primary", pa.bool_()),
        ("rank", pa.int32()),  # display order: what an analyst opens first
    ]
)

HIDDEN_TYPES = ("GRAPHIC", "ZIP", "XML", "JSON", "EX-101", "EX-104", "EXCEL", "PDF")  # XBRL plumbing, images
PRIMARY_LABELS = {
    "10-K": "Annual report",
    "10-KT": "Transition report",
    "10-Q": "Quarterly report",
    "10-QT": "Transition report",
    "20-F": "Annual report",
    "40-F": "Annual report",
    "6-K": "Interim report",
    "8-K": "8-K cover",
    "DEF 14A": "Proxy statement",
    "DEFA14A": "Proxy materials",
    "ARS": "Annual report to shareholders",
    "S-1": "Registration statement",
    "S-3": "Shelf registration",
    "424B4": "Prospectus",
    "424B5": "Prospectus supplement",
}
EXHIBIT_LABELS = {
    "EX-1": "Underwriting agreement",
    "EX-2": "Merger or acquisition agreement",
    "EX-3": "Charter and bylaws",
    "EX-4": "Debt and securities instruments",
    "EX-10": "Material contract",
    "EX-13": "Annual report to shareholders",
    "EX-19": "Insider trading policy",
    "EX-21": "Subsidiaries",
    "EX-23": "Auditor consent",
    "EX-24": "Power of attorney",
    "EX-31": "Officer certifications",
    "EX-32": "Officer certifications",
    "EX-95": "Mine safety disclosure",
    "EX-96": "Technical report summary",
    "EX-97": "Clawback policy",
}


def filing_index_url(cik: int, accession: str) -> str:
    return f"{WWW}/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}-index.htm"


def document_url(cik: int, accession: str, filename: str) -> str:
    return f"{WWW}/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{filename}"


class _IndexTableParser(HTMLParser):
    """Rows of the `tableFile` table on an EDGAR filing index page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.hrefs: list[str | None] = []
        self._in_table = False
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._href: str | None = None
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "table" and "tableFile" in (a.get("class") or ""):
            self._in_table = True
            return
        if not self._in_table:
            return
        if tag == "tr":
            self._row, self._href = [], None
        elif tag == "td" and self._row is not None:
            self._cell = []
        elif tag == "a" and self._cell is not None and a.get("href"):
            self._href = a["href"]

    def handle_endtag(self, tag: str) -> None:
        if not self._in_table:
            return
        if tag == "td" and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
                self.hrefs.append(self._href)
            self._row = None
        elif tag == "table":
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def parse_filing_index(html: str) -> list[dict[str, Any]]:
    """[{seq, description, filename, doc_type, size}] from a filing index page; empty if unparsable."""
    p = _IndexTableParser()
    p.feed(html)
    out = []
    for row, href in zip(p.rows, p.hrefs, strict=True):
        if len(row) < 4:
            continue
        seq, description, filename, doc_type = row[0], row[1], row[2], row[3]
        size = row[4] if len(row) > 4 else ""
        if href:
            # inline XBRL viewer links look like /ix?doc=/Archives/.../file.htm
            m = re.search(r"doc=([^&]+)", href)
            target = m.group(1) if m else href
            filename = target.rsplit("/", 1)[-1]
        if not filename or filename.lower().endswith("-index.htm"):
            continue
        try:
            seq_n = int(seq)
        except ValueError:
            seq_n = 0
        try:
            size_n = int(re.sub(r"\D", "", size)) if size else 0
        except ValueError:
            size_n = 0
        out.append(
            {"seq": seq_n, "description": description, "filename": filename, "doc_type": doc_type, "size": size_n}
        )
    return out


def _exhibit_family(doc_type: str) -> str:
    """EX-99.1 -> EX-99; EX-10.2 -> EX-10; 10-K -> 10-K."""
    m = re.match(r"(EX-\d+)", doc_type.upper())
    return m.group(1) if m else doc_type.upper()


def label_document(
    form: str, items: list[str] | None, doc_type: str, description: str, is_primary: bool
) -> tuple[str, str, int]:
    """(label, kind, rank) in plain words. Rank orders what an analyst opens first (lower first)."""
    form_u = (form or "").upper().split("/")[0]
    amended = (form or "").upper().endswith("/A")
    d = (description or "").lower()
    t = doc_type.upper()
    fam = _exhibit_family(t)
    items = items or []
    is_results_8k = form_u == "8-K" and any(i.startswith("2.02") for i in items)
    is_reg_fd_8k = form_u == "8-K" and any(i.startswith("7.01") for i in items)

    if is_primary:
        base = PRIMARY_LABELS.get(form_u, form_u or "Filing")
        if amended:
            base += " (amended)"
        rank = 10 if form_u == "8-K" else 0  # the 8-K cover itself is rarely what you want
        return base, "primary", rank

    if fam == "EX-99":
        if "presentation" in d or "slides" in d or "deck" in d:
            return "Investor presentation", "presentation", 2
        if "supplement" in d or "financial data" in d or "fact sheet" in d:
            return "Financial supplement", "supplement", 3
        if "letter" in d:
            return "Shareholder letter", "letter", 2
        if "transcript" in d:
            return "Call transcript", "transcript", 2
        if is_results_8k and t in ("EX-99.1", "EX-99"):
            return "Earnings release", "release", 1
        if is_results_8k:
            return "Earnings materials", "release", 2
        if is_reg_fd_8k or "press release" in d or "news release" in d:
            return "Press release", "release", 2
        return "Exhibit " + t.replace("EX-", ""), "exhibit", 5
    if fam in EXHIBIT_LABELS:
        return EXHIBIT_LABELS[fam], "exhibit", 6
    if fam in ("EX-101", "EX-104") or t in HIDDEN_TYPES:
        return t, "support", 9
    return ("Exhibit " + t.replace("EX-", "")) if t.startswith("EX-") else t, "exhibit", 7


def documents_table(
    cik: int, accession: str, form: str, items: list[str] | None, primary_doc: str | None, rows: list[dict[str, Any]]
) -> pa.Table:
    recs = []
    for r in rows:
        is_primary = bool(primary_doc) and r["filename"] == primary_doc
        if not is_primary and r["seq"] == 1 and not primary_doc and not r["doc_type"].upper().startswith("EX-"):
            is_primary = True
        label, kind, rank = label_document(form, items, r["doc_type"], r["description"], is_primary)
        recs.append(
            {
                "cik": cik,
                "accession": accession,
                "seq": r["seq"],
                "doc_type": r["doc_type"],
                "description": r["description"],
                "filename": r["filename"],
                "url": document_url(cik, accession, r["filename"]),
                "size": r["size"],
                "label": label,
                "kind": kind,
                "is_primary": is_primary,
                "rank": rank,
            }
        )
    return pa.Table.from_pylist(recs, schema=DOCUMENTS_SCHEMA)


def fetch_filing_documents(
    client: EdgarClient, cik: int, accession: str, form: str, items: list[str] | None, primary_doc: str | None
) -> pa.Table:
    html = client.get(filing_index_url(cik, accession)).text
    rows = parse_filing_index(html)
    return documents_table(cik, accession, form, items, primary_doc, rows)


def read_documents(storage: Storage, cik: int) -> pa.Table:
    rel = f"{layout.documents_cik_dir(cik)}/part-0.parquet"
    if not storage.exists(rel):
        return DOCUMENTS_SCHEMA.empty_table()
    return storage.read_parquet(rel).cast(DOCUMENTS_SCHEMA)


def write_documents(storage: Storage, cik: int, table: pa.Table) -> None:
    storage.replace_dir_with_parquet(
        layout.documents_cik_dir(cik), table.sort_by([("accession", "ascending"), ("seq", "ascending")])
    )


def ensure_documents(
    storage: Storage,
    client: EdgarClient | None,
    cik: int,
    filings: list[dict[str, Any]],
    persist: bool = True,
    max_fetch: int = 40,
) -> tuple[pa.Table, list[str]]:
    """Documents for `filings` ([{accession, form, items, primary_doc}]), fetching the ones the lake
    lacks (at most `max_fetch` per call, newest first as given). Returns (table, failures).

    Writing back is best-effort: an API serving from a read-only lake keeps working from memory."""
    have = read_documents(storage, cik)
    known = set(have.column("accession").to_pylist()) if have.num_rows else set()
    wanted = [f for f in filings if f["accession"] not in known]
    failures: list[str] = []
    fetched: list[pa.Table] = []
    if client is not None and wanted:
        for f in wanted[:max_fetch]:
            try:
                t = fetch_filing_documents(
                    client, cik, f["accession"], f.get("form") or "", f.get("items"), f.get("primary_doc")
                )
            except EdgarError as e:
                failures.append(f"{f['accession']}: {e}")
                continue
            if t.num_rows == 0:  # index page unparsable: remember the primary document at least
                t = documents_table(
                    cik,
                    f["accession"],
                    f.get("form") or "",
                    f.get("items"),
                    f.get("primary_doc"),
                    [
                        {
                            "seq": 1,
                            "description": "",
                            "filename": f.get("primary_doc") or "",
                            "doc_type": f.get("form") or "",
                            "size": 0,
                        }
                    ]
                    if f.get("primary_doc")
                    else [],
                )
            fetched.append(t)
    if fetched:
        merged = pa.concat_tables([have, *fetched]) if have.num_rows else pa.concat_tables(fetched)
        if persist:
            try:
                write_documents(storage, cik, merged)
            except Exception as e:  # read-only lake: serve from memory
                log.debug("documents for CIK %s not persisted: %s", cik, e)
        have = merged
    accs = pa.array([f["accession"] for f in filings], pa.string())
    if have.num_rows:
        have = have.filter(pc.is_in(have.column("accession"), value_set=accs))
    return have, failures


__all__ = [
    "DOCUMENTS_SCHEMA",
    "document_url",
    "documents_table",
    "ensure_documents",
    "fetch_filing_documents",
    "filing_index_url",
    "label_document",
    "parse_filing_index",
    "read_documents",
]
