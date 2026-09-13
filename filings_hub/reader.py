"""Filing reader and in-filing text search.

* `fetch_document` gets a filing document from the SEC once and keeps it: in memory (bounded) and,
  when the lake is writable, under raw/edgar/documents/.
* `render_document` rebuilds the document's HTML from an allow-list of tags and attributes (no
  scripts, frames, forms or event handlers), rewrites relative links and images to the filing's folder
  on sec.gov, and anchors the section headings (Part/Item lines of a 10-K or 10-Q, the financial
  statement titles) so a table of contents can jump to them. The page shows the result in a sandboxed
  frame, so the filer's own stylesheet cannot leak into the site.
* `html_to_text` / `search_text` power "where did they last mention buybacks": plain text per
  paragraph, phrase matches with context.
"""

from __future__ import annotations

import logging
import re
import threading
from collections import OrderedDict
from html import escape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from filings_hub.ingest.edgar_client import EdgarClient
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage

log = logging.getLogger(__name__)

ALLOWED_TAGS = frozenset(
    [
        "a",
        "abbr",
        "b",
        "big",
        "blockquote",
        "br",
        "caption",
        "center",
        "code",
        "col",
        "colgroup",
        "dd",
        "del",
        "div",
        "dl",
        "dt",
        "em",
        "font",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "i",
        "img",
        "ins",
        "li",
        "ol",
        "p",
        "pre",
        "s",
        "small",
        "span",
        "strike",
        "strong",
        "sub",
        "sup",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "tt",
        "u",
        "ul",
        "style",
        "title",
    ]
)
VOID_TAGS = frozenset(["br", "hr", "img", "col"])
BLOCK_TAGS = frozenset(
    [
        "p",
        "div",
        "td",
        "th",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "tr",
        "table",
        "blockquote",
        "pre",
        "dd",
        "dt",
        "caption",
        "center",
    ]
)
ALLOWED_ATTRS = frozenset(
    [
        "style",
        "class",
        "id",
        "colspan",
        "rowspan",
        "align",
        "valign",
        "width",
        "height",
        "border",
        "cellpadding",
        "cellspacing",
        "bgcolor",
        "color",
        "face",
        "size",
        "nowrap",
        "alt",
        "title",
        "href",
        "src",
        "name",
        "start",
        "type",
    ]
)
DROP_CONTENT_TAGS = frozenset(
    ["script", "noscript", "iframe", "object", "embed", "applet", "form", "input", "button", "select", "textarea"]
)

HEADING_RE = re.compile(
    r"^(part\s+[ivx]+\b|item\s+\d{1,2}[a-c]?\b\.?|"
    r"(consolidated\s+|condensed\s+consolidated\s+)?(balance\s+sheets?|statements?\s+of\s+(operations|income|earnings|"
    r"comprehensive\s+(income|loss)|cash\s+flows?|(changes\s+in\s+)?(shareholders'?|stockholders'?|share\s+owners'?)\s+equity|"
    r"financial\s+(position|condition))|notes?\s+to\s+(the\s+)?(condensed\s+)?consolidated\s+financial\s+statements))",
    re.IGNORECASE,
)
MAX_HEADING_CHARS = 160


class _Sanitizer(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=False)
        self.base = base_url
        self.out: list[str] = []
        self.drop_depth = 0
        self.title: list[str] = []
        self._in_title = False
        # block-level elements currently open: (chunk index of their start tag, text pieces)
        self._blocks: list[tuple[int, list[str]]] = []
        self.headings: list[tuple[int, str]] = []  # (chunk index, text)

    # -- helpers
    def _attr_ok(self, tag: str, name: str, value: str | None) -> str | None:
        if name.startswith("on") or name not in ALLOWED_ATTRS:
            return None
        v = value or ""
        if name in ("href", "src"):
            low = v.strip().lower()
            if low.startswith(("javascript:", "data:", "vbscript:")):
                return None
            if name == "href" and low.startswith("#"):
                return v
            return urljoin(self.base, v.strip())
        if name == "style" and ("expression(" in v.lower() or ("url(" in v.lower() and "http" not in v.lower())):
            return None
        return v

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.drop_depth:
            if tag in DROP_CONTENT_TAGS and tag not in VOID_TAGS:
                self.drop_depth += 1
            return
        if tag in DROP_CONTENT_TAGS:
            self.drop_depth = 1
            return
        if tag == "title":
            self._in_title = True
            return
        if tag not in ALLOWED_TAGS:
            return  # unknown (inline XBRL wrappers etc.): keep the content, drop the tag
        parts = []
        for name, value in attrs:
            v = self._attr_ok(tag, name, value)
            if v is not None:
                parts.append(f' {name}="{escape(v, quote=True)}"')
        self.out.append(f"<{tag}{''.join(parts)}>")
        if tag in BLOCK_TAGS:
            self._blocks.append((len(self.out) - 1, []))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS and tag in ALLOWED_TAGS and not self.drop_depth:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.drop_depth:
            if tag in DROP_CONTENT_TAGS:
                self.drop_depth -= 1
            return
        if tag == "title":
            self._in_title = False
            return
        if tag not in ALLOWED_TAGS or tag in VOID_TAGS:
            return
        if tag in BLOCK_TAGS and self._blocks:
            idx, pieces = self._blocks.pop()
            text = " ".join("".join(pieces).split())
            if 0 < len(text) <= MAX_HEADING_CHARS and HEADING_RE.match(text):
                self.headings.append((idx, text))
            if self._blocks:  # a block's text also counts towards its parent (table rows, cells)
                self._blocks[-1][1].append(" " + text + " ")
        self.out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self.drop_depth:
            return
        if self._in_title:
            self.title.append(data)
            return
        self.out.append(data)
        if self._blocks:
            self._blocks[-1][1].append(data)

    def handle_entityref(self, name: str) -> None:
        self.handle_data(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.handle_data(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        return


def _dedupe_headings(headings: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """A 10-K lists its Items in a table of contents before the sections themselves, and text refers
    to 'Item 7' in passing: keep the last short occurrence of each heading, which is the section."""
    by_key: OrderedDict[str, tuple[int, str]] = OrderedDict()
    for idx, text in headings:
        key = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
        m = re.match(r"^(part [ivx]+|item \d{1,2}[a-c]?)", key)
        key = m.group(1) if m else key
        by_key.pop(key, None)
        by_key[key] = (idx, text)
    return sorted(by_key.values(), key=lambda h: h[0])


def render_document(html: str, base_url: str) -> dict[str, Any]:
    """{html, toc: [{id, title}], title} with the headings anchored as id="fh-N"."""
    s = _Sanitizer(base_url)
    s.feed(html)
    s.close()
    toc = []
    for n, (idx, text) in enumerate(_dedupe_headings(s.headings)):
        anchor = f"fh-{n}"
        start = s.out[idx]
        s.out[idx] = start[:-1] + f' id="{anchor}">' if 'id="' not in start else start
        toc.append({"id": anchor, "title": text[:120]})
    title = " ".join("".join(s.title).split())
    return {"html": "".join(s.out), "toc": toc, "title": title}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.drop = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in DROP_CONTENT_TAGS or tag == "style":
            self.drop += 1
        elif tag in BLOCK_TAGS or tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in DROP_CONTENT_TAGS or tag == "style":
            self.drop = max(0, self.drop - 1)
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.drop:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Plain text with one paragraph per line, whitespace collapsed."""
    p = _TextExtractor()
    p.feed(html)
    p.close()
    text = "".join(p.parts).replace("\xa0", " ")
    lines = [" ".join(ln.split()) for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def search_text(text: str, query: str, context: int = 160, max_hits: int = 5) -> list[dict[str, Any]]:
    """Case-insensitive phrase matches with surrounding context, at most `max_hits` per document."""
    q = " ".join(query.split())
    if not q:
        return []
    hits = []
    for m in re.finditer(re.escape(q), text, re.IGNORECASE):
        a, b = max(0, m.start() - context), min(len(text), m.end() + context)
        snippet = text[a:b].replace("\n", " ")
        hits.append(
            {
                "before": ("…" if a > 0 else "") + text[a : m.start()].replace("\n", " "),
                "match": text[m.start() : m.end()],
                "after": text[m.end() : b].replace("\n", " ") + ("…" if b < len(text) else ""),
                "snippet": snippet,
            }
        )
        if len(hits) >= max_hits:
            break
    return hits


class DocumentCache:
    """Bounded in-memory cache of fetched documents, with a best-effort copy in the lake."""

    def __init__(self, storage: Storage, client: EdgarClient | None, max_bytes: int = 256 * 1024 * 1024):
        self.storage = storage
        self.client = client
        self.max_bytes = max_bytes
        self._mem: OrderedDict[str, bytes] = OrderedDict()
        self._size = 0
        self._lock = threading.Lock()

    def _put(self, key: str, data: bytes) -> None:
        with self._lock:
            if key in self._mem:
                self._size -= len(self._mem.pop(key))
            self._mem[key] = data
            self._size += len(data)
            while self._size > self.max_bytes and self._mem:
                _, old = self._mem.popitem(last=False)
                self._size -= len(old)

    def _get(self, key: str) -> bytes | None:
        with self._lock:
            data = self._mem.get(key)
            if data is not None:
                self._mem.move_to_end(key)
            return data

    def fetch_document(self, cik: int, accession: str, filename: str) -> bytes:
        key = f"{cik}/{accession}/{filename}"
        data = self._get(key)
        if data is not None:
            return data
        rel = layout.raw_document(cik, accession, filename)
        if self.storage.exists(rel):
            data = self.storage.read_bytes(rel)
        else:
            if self.client is None:
                raise RuntimeError("no EDGAR client configured (SEC_USER_AGENT)")
            from filings_hub.ingest.documents import document_url

            data = self.client.get(document_url(cik, accession, filename)).content
            try:
                self.storage.write_bytes(rel, data)
            except Exception as e:  # read-only lake
                log.debug("document %s not persisted: %s", rel, e)
        self._put(key, data)
        return data

    def fetch_text(self, cik: int, accession: str, filename: str) -> str:
        key = f"text:{cik}/{accession}/{filename}"
        data = self._get(key)
        if data is not None:
            return data.decode("utf-8")
        rel = layout.text_cache(cik, accession, filename)
        if self.storage.exists(rel):
            text = self.storage.read_text(rel)
        else:
            raw = self.fetch_document(cik, accession, filename)
            text = html_to_text(raw.decode("utf-8", errors="replace"))
            try:
                self.storage.write_text(rel, text)
            except Exception as e:
                log.debug("text %s not persisted: %s", rel, e)
        self._put(key, text.encode("utf-8"))
        return text


__all__ = ["DocumentCache", "html_to_text", "render_document", "search_text"]
