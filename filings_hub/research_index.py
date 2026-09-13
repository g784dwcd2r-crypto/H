"""Durable lexical search: Postgres in production, SQLite with identical postings locally.

Search never contacts EDGAR or reads lake documents. All content enters through the explicit worker.
Only public sec-edgar rows are eligible, before matching, pagination, evidence lookup and counts.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from filings_hub.lake.storage import Storage
from filings_hub.platform.contracts import content_version_id, sec_document_id
from filings_hub.research_query import compile_query, parse_query, snippet, words

MIGRATION = Path(__file__).parent / "db" / "migrations" / "0009_research_index.sql"
PUBLIC = "source_id='sec-edgar' AND visibility='public'"
EXTRACTOR_VERSION = "disclosure-text-v1"


def now() -> str:
    return datetime.now(UTC).isoformat()


class ResearchIndex:
    def __init__(self, *, database_url: str = "", path: str | Path | None = None):
        self._lock = threading.RLock()
        self.postgres = database_url.startswith(("postgresql://", "postgres://"))
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row

            self.conn = psycopg.connect(database_url, autocommit=True, row_factory=dict_row)
            self.conn.execute(MIGRATION.read_text())
        else:
            if path is None:
                raise ValueError("A durable local index path is required without Postgres.")
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=30)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript(MIGRATION.read_text())

    @contextmanager
    def transaction(self, *, read_only: bool = False):
        with self._lock:
            if self.postgres:
                with self.conn.transaction():
                    if read_only:
                        self.conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                    yield
            else:
                self.conn.execute("BEGIN" if read_only else "BEGIN IMMEDIATE")
                try:
                    yield
                    self.conn.execute("COMMIT")
                except BaseException:
                    self.conn.execute("ROLLBACK")
                    raise

    def execute(self, sql: str, params=()) -> None:
        with self._lock:
            self.conn.execute(sql.replace("?", "%s") if self.postgres else sql, params)

    def query(self, sql: str, params=()) -> list[dict[str, Any]]:
        with self._lock:
            cur = self.conn.execute(sql.replace("?", "%s") if self.postgres else sql, params)
            return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def meta(self, key: str, value: Any = None) -> Any:
        if value is not None:
            self.execute(
                "INSERT INTO research_index_meta(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                [key, json.dumps(value)],
            )
            return value
        rows = self.query("SELECT value FROM research_index_meta WHERE key=?", [key])
        return json.loads(rows[0]["value"]) if rows else None

    def register_filing(self, filing: dict[str, Any]) -> None:
        self.execute(
            "INSERT INTO research_filings(cik,accession,form,filed_date,company_name) VALUES(?,?,?,?,?) "
            "ON CONFLICT(cik,accession) DO UPDATE SET form=excluded.form,filed_date=excluded.filed_date,"
            "company_name=excluded.company_name",
            [
                filing["cik"],
                filing["accession"],
                filing.get("form"),
                str(filing.get("filed_date") or ""),
                filing.get("company_name"),
            ],
        )

    def inventory_status(self, cik: int, accession: str, status: str, error: str | None = None) -> None:
        self.execute(
            "UPDATE research_filings SET inventory_status=?,inventory_error=?,checked_at=? WHERE cik=? AND accession=?",
            [status, error, now(), cik, accession],
        )

    def register_document(self, filing: dict[str, Any], document: dict[str, Any]) -> str:
        # No private/provider ingestion path exists in this release.
        if document.get("source_id", "sec-edgar") != "sec-edgar" or document.get("visibility", "public") != "public":
            raise ValueError("This index only accepts public SEC documents.")
        from filings_hub.ingest.documents import document_url

        cik, accession, filename = int(filing["cik"]), filing["accession"], document["filename"]
        document_id = sec_document_id(cik, accession, filename)
        self.execute(
            "INSERT INTO research_documents(document_id,cik,accession,filename,title,company_name,form,filed_date,"
            "source_url,discovered_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET "
            "title=excluded.title,company_name=excluded.company_name,form=excluded.form,filed_date=excluded.filed_date",
            [
                document_id,
                cik,
                accession,
                filename,
                document.get("label") or document.get("description") or filename,
                filing.get("company_name"),
                filing.get("form"),
                str(filing.get("filed_date") or ""),
                document_url(cik, accession, filename),
                now(),
            ],
        )
        return document_id

    def document_status(self, document_id: str, status: str, error: str | None = None) -> None:
        if status not in ("pending", "failed", "unsupported", "indexed"):
            raise ValueError("Unknown document index status")
        self.execute(
            "UPDATE research_documents SET status=?,error=?,attempted_at=? WHERE document_id=?",
            [status, error, now(), document_id],
        )

    def add_version(self, storage: Storage, document_id: str, raw: bytes, text: str, pages=None) -> str:
        docs = self.query(f"SELECT * FROM research_documents WHERE document_id=? AND {PUBLIC}", [document_id])
        if not docs:
            raise ValueError("Register an eligible public SEC document before extracting it.")
        doc = docs[0]
        version_id = content_version_id(document_id, raw)
        raw_path = f"research/versions/{version_id.split(':', 1)[1]}.bin"
        if not storage.exists(raw_path):
            storage.write_bytes(raw_path, raw)
        timestamp = now()
        metadata = {
            key: doc[key]
            for key in (
                "document_id",
                "cik",
                "accession",
                "filename",
                "title",
                "company_name",
                "form",
                "filed_date",
                "source_url",
                "source_id",
                "visibility",
                "discovered_at",
            )
        }
        metadata["pages"] = pages or []
        with self.transaction():
            if self.postgres:
                self.query("SELECT document_id FROM research_documents WHERE document_id=? FOR UPDATE", [document_id])
            exists = self.query("SELECT version_id FROM research_versions WHERE version_id=?", [version_id])
            if not exists:
                self.execute(
                    "INSERT INTO research_versions(version_id,document_id,content_sha256,raw_path,text_content,"
                    "source_metadata,indexed_at,extractor_version,content_bytes) VALUES(?,?,?,?,?,?,?,?,?)",
                    [
                        version_id,
                        document_id,
                        hashlib.sha256(raw).hexdigest(),
                        raw_path,
                        text,
                        json.dumps(metadata),
                        timestamp,
                        EXTRACTOR_VERSION,
                        len(raw),
                    ],
                )
                terms = words(text)
                sql = "INSERT INTO research_terms(version_id,term,position) VALUES(?,?,?)"
                for start in range(0, len(terms), 1000):
                    batch = [(version_id, term, i) for i, term in enumerate(terms[start : start + 1000], start)]
                    with self.conn.cursor() if self.postgres else _sqlite_cursor(self.conn) as cur:
                        cur.executemany(sql.replace("?", "%s") if self.postgres else sql, batch)
            self.execute(
                "UPDATE research_documents SET current_version_id=?,status='indexed',error=NULL,attempted_at=? "
                "WHERE document_id=?",
                [version_id, timestamp, document_id],
            )
        return version_id

    @staticmethod
    def _filters(cik=None, form=None, from_date=None, to_date=None, prefix="d") -> tuple[str, list]:
        conditions = [f"{prefix}.source_id='sec-edgar'", f"{prefix}.visibility='public'"]
        params = []
        for field, op, value in (
            ("cik", "=", cik),
            ("form", "=", form),
            ("filed_date", ">=", from_date),
            ("filed_date", "<=", to_date),
        ):
            if value is not None:
                conditions.append(f"{prefix}.{field}{op}?")
                params.append(str(value) if isinstance(value, date) else value)
        return " AND ".join(conditions), params

    def coverage(self, *, cik=None, form=None, from_date=None, to_date=None) -> dict[str, Any]:
        where, params = self._filters(cik, form, from_date, to_date)
        counts = {
            r["status"]: int(r["n"])
            for r in self.query(
                f"SELECT d.status,count(*) n FROM research_documents d WHERE {where} GROUP BY d.status",
                params,
            )
        }
        fw, fp = self._filters(cik, form, from_date, to_date, "f")
        inventories = {
            r["inventory_status"]: int(r["n"])
            for r in self.query(
                f"SELECT f.inventory_status,count(*) n FROM research_filings f WHERE {fw} GROUP BY f.inventory_status",
                fp,
            )
        }
        stamp = self.query(
            "SELECT max(v.indexed_at) stamp FROM research_versions v JOIN research_documents d "
            f"ON d.current_version_id=v.version_id WHERE {where}",
            params,
        )[0]["stamp"]
        complete = self.meta("discovery:all:complete") is True or (
            cik is not None and self.meta(f"discovery:{cik}:complete") is True
        )
        out = {status: counts.get(status, 0) for status in ("indexed", "failed", "pending", "unsupported")}
        out.update(
            total=sum(counts.values()),
            filings_known=sum(inventories.values()),
            inventories_complete=inventories.get("complete", 0),
            inventories_failed=inventories.get("failed", 0),
            inventories_pending=inventories.get("pending", 0),
            discovery_complete=complete,
            scope="public SEC documents registered with this index",
            last_indexed_at=stamp,
            last_discovery_at=self.meta(f"discovery:{cik if cik is not None else 'all'}:at")
            or self.meta("discovery:all:at"),
        )
        out["partial"] = not complete or any(
            out[k]
            for k in (
                "failed",
                "pending",
                "unsupported",
                "inventories_failed",
                "inventories_pending",
            )
        )
        return out

    def search(
        self, query: str = "", *, cik=None, form=None, from_date=None, to_date=None, limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        with self.transaction(read_only=True):
            return self._search(
                query, cik=cik, form=form, from_date=from_date, to_date=to_date, limit=limit, offset=offset
            )

    def _search(
        self,
        query: str,
        *,
        cik=None,
        form=None,
        from_date=None,
        to_date=None,
        limit=20,
        offset=0,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("limit must be 1–100 and offset must be nonnegative")
        node = parse_query(query)
        coverage = self.coverage(cik=cik, form=form, from_date=from_date, to_date=to_date)
        result = dict(
            query=query,
            syntax="lexical-v1",
            results=[],
            total=0,
            limit=limit,
            offset=offset,
            next_offset=None,
            coverage=coverage,
        )
        if node is None:
            return result
        where, params = self._filters(cik, form, from_date, to_date)
        expression, query_params = compile_query(node)
        joins = "FROM research_documents d JOIN research_versions v ON d.current_version_id=v.version_id"
        where += " AND d.status='indexed' AND (" + expression + ")"
        values = params + query_params
        total = int(self.query(f"SELECT count(*) n {joins} WHERE {where}", values)[0]["n"])
        rows = self.query(
            f"SELECT v.version_id,v.source_metadata,v.text_content {joins} WHERE {where} "
            "ORDER BY d.filed_date DESC,d.cik,d.document_id LIMIT ? OFFSET ?",
            [*values, limit, offset],
        )
        hits = []
        for row in rows:
            metadata = json.loads(row["source_metadata"])
            hit = {key: value for key, value in metadata.items() if key not in ("pages", "discovered_at")}
            hit.update(version_id=row["version_id"], snippet=snippet(row["text_content"], node))
            hits.append(hit)
        result.update(results=hits, total=total, next_offset=offset + len(rows) if offset + len(rows) < total else None)
        return result

    def version(self, version_id: str) -> dict[str, Any] | None:
        # A later restriction applies even to old immutable versions; content-addressing does not grant access.
        rows = self.query(
            "SELECT v.* FROM research_versions v JOIN research_documents d ON d.document_id=v.document_id "
            "WHERE v.version_id=? AND d.source_id='sec-edgar' AND d.visibility='public' AND "
            + self._public_version_sql(),
            [version_id],
        )
        if not rows:
            return None
        row = rows[0]
        metadata = json.loads(row.pop("source_metadata"))
        row.pop("raw_path")  # internal object layout is not a public source URL
        return {**metadata, **row}

    def _public_version_sql(self) -> str:
        # A newly public document does not retroactively release a formerly private capture.
        if self.postgres:
            return (
                "v.source_metadata::jsonb->>'source_id'='sec-edgar' "
                "AND v.source_metadata::jsonb->>'visibility'='public'"
            )
        return (
            "json_extract(v.source_metadata,'$.source_id')='sec-edgar' "
            "AND json_extract(v.source_metadata,'$.visibility')='public'"
        )

    def history(self, version_id: str, *, limit: int = 20, offset: int = 0) -> dict[str, Any] | None:
        from filings_hub.research_compare import version_metadata

        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("limit must be 1–100 and offset must be nonnegative")
        with self.transaction(read_only=True):
            selected = self.version(version_id)
            if selected is None:
                return None
            document_where = "d.document_id=? AND d.source_id='sec-edgar' AND d.visibility='public'"
            where = document_where + " AND " + self._public_version_sql()
            joins = "FROM research_versions v JOIN research_documents d ON d.document_id=v.document_id"
            params = [selected["document_id"]]
            total = int(self.query(f"SELECT count(*) n {joins} WHERE {where}", params)[0]["n"])
            rows = self.query(
                "SELECT v.version_id,v.content_sha256,v.indexed_at,v.extractor_version,"
                "v.content_bytes,v.source_metadata "
                f"{joins} WHERE {where} "
                "ORDER BY v.indexed_at DESC,v.version_id DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            )
            current = self.query(f"SELECT current_version_id FROM research_documents d WHERE {document_where}", params)[
                0
            ]
            current_id = current["current_version_id"]
            if current_id is not None and self.version(current_id) is None:
                current_id = None
            versions = []
            for row in rows:
                versions.append(version_metadata({**json.loads(row["source_metadata"]), **row}))
            return {
                "document_id": selected["document_id"],
                "current_version_id": current_id,
                "versions": versions,
                "total": total,
                "limit": limit,
                "offset": offset,
                "next_offset": offset + len(rows) if offset + len(rows) < total else None,
            }

    def compare(
        self, before: str, after: str, *, context: int = 3, max_hunks: int = 20, max_lines: int = 600
    ) -> dict[str, Any] | None:
        from filings_hub.research_compare import compare_texts

        with self.transaction(read_only=True):
            left, right = self.version(before), self.version(after)
            # Fail alike for absent and currently restricted versions, before comparing their identities.
            if left is None or right is None:
                return None
            return compare_texts(left, right, context=context, max_hunks=max_hunks, max_lines=max_lines)


@contextmanager
def _sqlite_cursor(conn):
    cur = conn.cursor()
    try:
        yield cur
    finally:
        cur.close()


def open_index(storage: Storage, database_url: str = "") -> ResearchIndex:
    if database_url.startswith(("postgresql://", "postgres://")):
        return ResearchIndex(database_url=database_url)
    if storage.is_remote:
        raise ValueError("A remote lake requires Postgres for its durable research index.")
    return ResearchIndex(path=storage.full("research/search.sqlite3"))
