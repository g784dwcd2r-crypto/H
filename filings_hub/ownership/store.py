"""Immutable ownership observations, conservative comparisons and issuer-scoped public reads.

The caller owns the ResearchIndex connection. SQL publication is atomic; content-addressed files
written before a failed transaction may remain unreferenced, but are never exposed by read routes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from filings_hub.research_index import ResearchIndex, now

KINDS = {"insiders", "institutions", "events"}
MIGRATION = Path(__file__).parents[1] / "db/migrations/0016_ownership.sql"
NOTE = (
    "Partial observed SEC coverage. Filing dates differ from transaction/report "
    "dates; undisclosed and unprocessed holdings are unknown."
)


class SourceIntegrityError(RuntimeError):
    """Persisted bytes cannot substantiate the source version they are labelled with."""


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def cik_value(value):
    if isinstance(value, bool) or not str(value).isdigit() or not 0 < int(value) < 10**10:
        raise ValueError("A positive SEC CIK is required.")
    return int(value)


def iso(value):
    return date.fromisoformat(str(value)).isoformat()


def kind_for(form):
    normalized = re.sub(r"\s+", "", str(form).upper())
    if normalized.removesuffix("/A") in {"3", "4", "5"}:
        return "insiders"
    if normalized.startswith("13F-"):
        return "institutions"
    if normalized.removesuffix("/A") in {"SC13D", "SC13G", "SCHEDULE13D", "SCHEDULE13G"}:
        return "events"
    raise ValueError("Unsupported ownership filing form.")


def source_url(value):
    parsed = urlsplit(str(value))
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"www.sec.gov", "sec.gov"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or not parsed.path.startswith("/Archives/edgar/data/")
        or parsed.query
        or parsed.fragment
        or "/../" in parsed.path
    ):
        raise ValueError("Ownership provenance must be an HTTPS SEC archive document URL.")
    return str(value)


def cusip_value(value):
    result = re.sub(r"\s", "", str(value or "")).upper()
    if not re.fullmatch(r"[0-9A-Z*@#]{9}", result):
        raise ValueError("An explicit nine-character CUSIP is required.")
    return result


def number(value):
    if value is None or isinstance(value, (float, bool)):
        return None
    try:
        parsed = Decimal(str(value))
        return parsed if parsed.is_finite() else None
    except InvalidOperation:
        return None


def quantity(value):
    return format(value, "f") if value is not None else None


def percent(row):
    shares, after = number(row.get("shares")), number(row.get("owned_after"))
    if row.get("is_holding") or row.get("footnotes") or shares is None or after is None or shares < 0 or after < 0:
        return None
    direction = row.get("acquired_disposed")
    if direction not in {"A", "D"}:
        return None
    before = after - shares if direction == "A" else after + shares
    if before <= 0:
        return None
    value = shares / before * 100 * (1 if direction == "A" else -1)
    return quantity(value.quantize(Decimal("0.0001")))


def previous_quarter(period):
    try:
        value = date.fromisoformat(period)
    except (ValueError, TypeError):
        return None
    ends = {
        (3, 31): (value.year - 1, 12, 31),
        (6, 30): (value.year, 3, 31),
        (9, 30): (value.year, 6, 30),
        (12, 31): (value.year, 9, 30),
    }
    return date(*ends[(value.month, value.day)]).isoformat() if (value.month, value.day) in ends else None


class OwnershipStore:
    def __init__(self, index: ResearchIndex, storage, *, initialize=True):
        self.index, self.storage = index, storage
        if initialize:
            if index.postgres:
                index.conn.execute(MIGRATION.read_text())
            else:
                with index._lock:
                    index.conn.executescript(MIGRATION.read_text())
        else:
            index.query("SELECT id FROM ownership_ingest_state LIMIT 0")

    def close(self):
        """The injected index belongs to the caller; no shared connection is closed here."""

    def get_state(self, key):
        if not isinstance(key, str) or not 1 <= len(key) <= 150:
            raise ValueError("Invalid ownership state key.")
        return self.index.meta("ownership:" + key)

    def set_state(self, key, value):
        if not isinstance(key, str) or not 1 <= len(key) <= 150:
            raise ValueError("Invalid ownership state key.")
        if len(encode(value)) > 100_000:
            raise ValueError("Ownership state is too large.")
        with self.index.transaction():
            self.index.execute(
                "INSERT INTO research_index_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO "
                "UPDATE SET value=excluded.value",
                ["ownership:" + key, encode(value)],
            )

    def _lock(self):
        if self.index.postgres:
            self.index.execute("SELECT pg_advisory_xact_lock(71894216700516)")

    def _persist_content(self, path, content):
        expected = hashlib.sha256(content).hexdigest()
        if self.storage.exists(path):
            with self.storage.open(path) as stream:
                actual = stream.read(len(content) + 1)
            if len(actual) == len(content) and hashlib.sha256(actual).hexdigest() == expected:
                return
        if self.storage.is_remote:
            self.storage.write_bytes(path, content)
        else:
            target = Path(self.storage.full(path))
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                    temporary = stream.name
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
        with self.storage.open(path) as stream:
            actual = stream.read(len(content) + 1)
        if len(actual) != len(content) or hashlib.sha256(actual).hexdigest() != expected:
            raise SourceIntegrityError("Ownership source storage did not retain the expected bytes.")

    def _metadata(self, metadata):
        from filings_hub.ownership.parse import normalize_form

        result = dict(metadata)
        for key in ("id", "status", "discovery_sources", "source_aliases"):
            result.pop(key, None)
        result["form"] = normalize_form(result["form"])
        result["filer_cik"] = cik_value(result["filer_cik"])
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", str(result.get("accession", ""))):
            raise ValueError("A canonical SEC accession number is required.")
        result["filed_date"] = iso(result["filed_date"])
        result["source_url"] = source_url(result["source_url"])
        result["kind"] = kind_for(result["form"])
        if result.get("issuer_cik") is not None:
            result["issuer_cik"] = cik_value(result["issuer_cik"])
        return result

    def register_filing(self, metadata):
        data = self._metadata(metadata)
        ident = digest(data["accession"])
        with self.index.transaction():
            self._lock()
            prior = self.index.query("SELECT * FROM ownership_ingest_state WHERE id=?", [ident])
            if prior:
                old = json.loads(prior[0]["metadata"])
                if any(old[key] != data[key] for key in ("accession", "form", "filed_date")):
                    raise ValueError("Conflicting filing metadata cannot replace existing provenance.")
                alias = {"filer_cik": data["filer_cik"], "source_url": data["source_url"]}
                aliases = old.get(
                    "discovery_sources", [{"filer_cik": old["filer_cik"], "source_url": old["source_url"]}]
                )
                if alias not in aliases:
                    old["discovery_sources"] = [*aliases, alias]
                    self.index.execute("UPDATE ownership_ingest_state SET metadata=? WHERE id=?", [encode(old), ident])
                return {**prior[0], "metadata": old}
            self.index.execute(
                "INSERT INTO ownership_ingest_state(id,accession,filer_cik,issuer_cik,kind,status,metadata,updated_at) "
                "VALUES(?,?,?,?,?,'pending',?,?)",
                [
                    ident,
                    data["accession"],
                    data["filer_cik"],
                    data.get("issuer_cik"),
                    data["kind"],
                    encode(data),
                    now(),
                ],
            )
            return {"id": ident, "status": "pending", "metadata": data}

    def pending(self, limit=50):
        if not 1 <= limit <= 500:
            raise ValueError("Pending batch limit must be 1–500.")
        return [
            {**json.loads(row["metadata"]), "id": row["id"], "status": row["status"]}
            for row in self.index.query(
                "SELECT id,status,metadata FROM ownership_ingest_state WHERE status IN ('pending','failed') "
                "ORDER BY updated_at,id LIMIT ?",
                [limit],
            )
        ]

    def record_failure(self, metadata, message, status="failed"):
        if status not in {"failed", "unsupported", "pending"}:
            raise ValueError("Unknown ownership processing status.")
        with self.index.transaction():
            self._lock()
            registered = self.register_filing(metadata)
            self.index.execute(
                "UPDATE ownership_ingest_state SET status=?,error=?,updated_at=? WHERE id=?",
                [status, str(message)[:1000], now(), registered["id"]],
            )
        return {"id": registered["id"], "status": status}

    def map_security(self, cusip, cik, security_title, source_url):
        # No names, ticker similarity or filer identity participate in matching.
        code, issuer = cusip_value(cusip), cik_value(cik)
        provenance = globals()["source_url"](source_url)
        title = str(security_title or "").strip()
        if not title or len(title) > 500:
            raise ValueError("A verified security title is required.")
        mapping = {"cusip": code, "issuer_cik": issuer, "security_title": title, "source_url": provenance}
        with self.index.transaction():
            self._lock()
            prior = self.index.query("SELECT * FROM ownership_security_mappings WHERE cusip=?", [code])
            if prior:
                if prior[0]["issuer_cik"] != issuer or prior[0]["security_title"].casefold() != title.casefold():
                    raise ValueError("Conflicting CUSIP mapping requires explicit investigation; no mapping changed.")
                return prior[0]
            self.index.execute(
                "INSERT INTO ownership_security_mappings(cusip,issuer_cik,security_title,sou"
                "rce_url,created_at) VALUES(?,?,?,?,?)",
                [code, issuer, title, provenance, now()],
            )
        return mapping

    def ingest(self, parsed, documents):
        parsed = json.loads(encode(parsed))
        filing = self._metadata(parsed["filing"])
        kind = parsed["kind"]
        if kind not in KINDS or filing["kind"] != kind or str(filing["form"]).startswith("13F-NT"):
            raise ValueError("Parsed flow does not match an eligible position/disclosure filing.")
        if not isinstance(documents, list) or not documents or len(documents) > 50:
            raise ValueError("An ownership filing requires 1–50 retained source documents.")
        retained, total_bytes = [], 0
        for document in documents:
            raw, filename = document["content"], str(document["filename"])
            if not isinstance(raw, bytes) or not raw or len(raw) > 25_000_000:
                raise ValueError("Each retained document must contain 1–25,000,000 bytes.")
            total_bytes += len(raw)
            if total_bytes > 50_000_000 or not re.fullmatch(r"[A-Za-z0-9_.-]{1,255}", filename):
                raise ValueError("Ownership source size or filename is invalid.")
            retained.append(
                {
                    "filename": filename,
                    "source_url": source_url(document["source_url"]),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "content_bytes": len(raw),
                    "raw": raw,
                }
            )
        if len({row["filename"] for row in retained}) != len(retained):
            raise ValueError("Duplicate document filenames are ambiguous.")
        retained.sort(key=lambda row: row["filename"])
        timestamp = now()
        with self.index.transaction():
            self._lock()
            registered = self.register_filing(filing)
            for key in ("filer_cik", "source_url"):
                filing[key] = registered["metadata"][key]
            parsed["filing"] = filing
            version = digest(
                [parsed, [{key: row[key] for key in ("filename", "sha256", "content_bytes")} for row in retained]]
            )
            provenance = registered["metadata"]
            aliases = provenance.get("source_aliases", [])
            for row in retained:
                alias = {
                    "filing_id": version,
                    "filename": row["filename"],
                    "source_url": row["source_url"],
                    "sha256": row["sha256"],
                }
                if alias not in aliases:
                    aliases.append(alias)
            provenance["source_aliases"] = aliases
            self.index.execute(
                "UPDATE ownership_ingest_state SET metadata=? WHERE id=?", [encode(provenance), registered["id"]]
            )
            for row in retained:
                self._persist_content(f"ownership/raw/{row['sha256']}.bin", row["raw"])
            existing = self.index.query("SELECT id,documents FROM ownership_filings WHERE id=?", [version])
            if existing:
                # A replay of an old version must never move the current pointer backwards.
                if registered.get("current_filing_id") == version:
                    self.index.execute(
                        "UPDATE ownership_ingest_state SET status='parsed',error=NULL,updated_at=? WHERE id=?",
                        [timestamp, registered["id"]],
                    )
                return {
                    "id": registered["id"],
                    "filing_id": version,
                    "status": "parsed",
                    "inserted": False,
                    "documents": json.loads(existing[0]["documents"]),
                    "warnings": filing.get("warnings", []),
                }
            if registered.get("current_filing_id"):
                filing["warnings"] = [
                    *filing.get("warnings", []),
                    "Revised source content observed for this accession.",
                ]
                filing["source_revision_observed"] = True
            issuer = filing.get("issuer_cik")
            if kind in {"insiders", "events"}:
                issuer = cik_value(issuer or (parsed.get("event") or {}).get("issuer_cik"))
                filing["issuer_cik"] = issuer
            manager = cik_value(filing.get("manager_cik") or filing["filer_cik"]) if kind == "institutions" else None
            sources = []
            for row in retained:
                document_id = digest([version, row["filename"], row["sha256"]])
                raw_path = f"ownership/raw/{row['sha256']}.bin"
                sources.append(
                    {
                        "document_id": document_id,
                        "accession": filing["accession"],
                        "form": filing["form"],
                        "filed_date": filing["filed_date"],
                        "filename": row["filename"],
                        "source_url": row["source_url"],
                        "raw_path": raw_path,
                        "sha256": row["sha256"],
                        "content_bytes": row["content_bytes"],
                    }
                )
            self.index.execute(
                "INSERT INTO ownership_filings(id,state_id,kind,filer_cik,issuer_cik,manager"
                "_cik,accession,form,filed_date,"
                "report_period,record,documents,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    version,
                    registered["id"],
                    kind,
                    filing["filer_cik"],
                    issuer,
                    manager,
                    filing["accession"],
                    filing["form"],
                    filing["filed_date"],
                    filing.get("report_period"),
                    encode(filing),
                    encode(sources),
                    timestamp,
                ],
            )
            if kind == "insiders":
                for position, row in enumerate(parsed["insiders"]):
                    if cik_value(row["issuer_cik"]) != issuer:
                        raise ValueError("Insider row issuer does not match the structured filing issuer.")
                    owner = (
                        f"cik:{cik_value(row['owner_cik'])}"
                        if row.get("owner_cik")
                        else f"unresolved:{version}:{position}"
                    )
                    self.index.execute(
                        "INSERT INTO ownership_insiders(id,filing_id,issuer_cik,owner_key,record) VALUES(?,?,?,?,?)",
                        [digest([version, position]), version, issuer, owner, encode(row)],
                    )
            elif kind == "institutions":
                for position, row in enumerate(parsed["positions"]):
                    code = cusip_value(row["cusip"])
                    self.index.execute(
                        "INSERT INTO ownership_institutions(id,filing_id,manager_cik,cusip,record) VALUES(?,?,?,?,?)",
                        [digest([version, position]), version, manager, code, encode(row)],
                    )
            else:
                event = parsed["event"]
                if cik_value(event["issuer_cik"]) != issuer:
                    raise ValueError("Event subject issuer does not match the structured filing issuer.")
                self.index.execute(
                    "INSERT INTO ownership_events(id,filing_id,issuer_cik,record) VALUES(?,?,?,?)",
                    [digest([version, "event"]), version, issuer, encode(event)],
                )
                for code in event.get("cusips") or ([event["cusip"]] if event.get("cusip") else []):
                    self.map_security(code, issuer, event.get("security_title"), filing["source_url"])
            normalized = f"ownership/{kind}/{version}.json"
            self._persist_content(normalized, encode({**parsed, "filing": filing, "documents": sources}).encode())
            self.index.execute(
                "UPDATE ownership_ingest_state SET status='parsed',issuer_cik=?,error=NULL,current_filing_id=?,"
                "last_successful_at=?,updated_at=? WHERE id=?",
                [issuer, version, timestamp, timestamp, registered["id"]],
            )
        return {
            "id": registered["id"],
            "filing_id": version,
            "status": "parsed",
            "inserted": True,
            "documents": sources,
            "warnings": filing.get("warnings", []),
        }

    def _filings(self, kind=None, cik=None, managers=None):
        clauses, args = [], []
        if kind:
            clauses.append("f.kind=?")
            args.append(kind)
        if cik is not None:
            clauses.append("f.issuer_cik=?")
            args.append(cik)
        if managers is not None:
            if not managers:
                return []
            clauses.append("f.manager_cik IN (" + ",".join("?" for _ in managers) + ")")
            args.extend(managers)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return self.index.query(
            "SELECT f.*,s.status AS processing_status FROM ownership_filings f JOIN owne"
            "rship_ingest_state s ON s.current_filing_id=f.id" + where,
            args,
        )

    def coverage(self, cik=None):
        issuer = cik_value(cik) if cik is not None else None
        with self.index.transaction(read_only=True):
            scope = (
                ""
                if issuer is None
                else " WHERE s.issuer_cik=? OR s.current_filing_id IN (SELECT p.filing_id FROM ow"
                "nership_institutions p JOIN ownership_security_mappings m ON m.cusip=p.cusi"
                "p WHERE m.issuer_cik=?)"
            )
            args = [] if issuer is None else [issuer, issuer]
            counts = {
                row["status"]: row["n"]
                for row in self.index.query(
                    "SELECT s.status,count(*) n FROM ownership_ingest_state s" + scope + " GROUP BY s.status", args
                )
            }
            observed = self.index.query(
                "SELECT max(s.last_successful_at) latest,count(s.current_filing_id) parsed F"
                "ROM ownership_ingest_state s" + scope,
                args,
            )[0]
            unresolved = self.index.query(
                "SELECT count(*) n FROM ownership_institutions p JOIN ownership_ingest_state"
                " s ON s.current_filing_id=p.filing_id LEFT JOIN ownership_security_mappings"
                " m ON m.cusip=p.cusip WHERE m.cusip IS NULL"
            )[0]["n"]
            unassigned = self.index.query(
                "SELECT count(*) n FROM ownership_ingest_state WHERE issuer_cik IS NULL AND current_filing_id IS NULL"
            )[0]["n"]
            return {
                "status": "partial",
                "parsed_filings": observed["parsed"],
                "pending": counts.get("pending", 0),
                "failed": counts.get("failed", 0),
                "unsupported": counts.get("unsupported", 0),
                "last_successful_at": observed["latest"],
                "unmatched_positions": unresolved,
                "unmatched_positions_scope": "global_unassignable_to_company",
                "unassigned_filings": unassigned,
                "note": NOTE + " Unmatched CUSIPs cannot be assigned to this company.",
            }

    @staticmethod
    def _documents(filing, cik):
        return [
            {key: row[key] for key in ("document_id", "accession", "form", "filed_date", "filename", "source_url")}
            | {"reader_url": f"/companies/{cik}/ownership/documents/{row['document_id']}"}
            for row in json.loads(filing["documents"])
        ]

    @staticmethod
    def _uncertain(filing):
        record = json.loads(filing["record"])
        return bool(
            record.get("is_amendment")
            or record.get("confidential_omitted")
            or record.get("source_revision_observed")
            or filing.get("processing_status", "parsed") != "parsed"
            or (filing["kind"] == "institutions" and record.get("confidential_omitted") is not False)
        )

    def _insider_cards(self, cik, direction="all", from_date=None, to_date=None):
        filings = {row["id"]: row for row in self._filings("insiders", cik=cik)}
        grouped = defaultdict(list)
        for row in self.index.query("SELECT * FROM ownership_insiders WHERE issuer_cik=?", [cik]):
            if row["filing_id"] in filings:
                grouped[row["owner_key"]].append((json.loads(row["record"]), filings[row["filing_id"]]))
        cards = []
        for owner, observations in grouped.items():
            observations.sort(
                key=lambda pair: (
                    pair[0].get("transaction_date") or pair[1]["report_period"] or "",
                    pair[1]["filed_date"],
                    pair[0].get("id", ""),
                ),
                reverse=True,
            )
            eligible = [
                (row, source)
                for row, source in observations
                if (not from_date or source["filed_date"] >= from_date)
                and (not to_date or source["filed_date"] <= to_date)
                and (
                    direction == "all"
                    or (
                        not row.get("is_holding")
                        and row.get("transaction_code") == ("P" if direction == "buys" else "S")
                        and row.get("acquired_disposed") == ("A" if direction == "buys" else "D")
                    )
                )
            ]
            if not eligible:
                continue
            latest, filing = eligible[0]

            def bucket(row):
                return (
                    row.get("security_title"),
                    row.get("is_derivative"),
                    row.get("ownership_form"),
                    row.get("nature_of_ownership"),
                )

            selected = bucket(latest)
            series_key = digest([cik, owner, selected])
            series, transactions, docs, seen = [], [], [], set()
            label = " · ".join(
                str(value)
                for value in (selected[0], "derivative" if selected[1] else "non-derivative", selected[2], selected[3])
                if value
            )
            for row, source in observations:
                point_date = row.get("transaction_date") or source["report_period"]
                if (
                    (not to_date or source["filed_date"] <= to_date)
                    and bucket(row) == selected
                    and not self._uncertain(source)
                    and not row.get("footnotes")
                    and number(row.get("owned_after")) is not None
                    and point_date
                ):
                    series.append(
                        {"date": point_date, "value": str(row["owned_after"]), "label": label, "series_key": series_key}
                    )
            for row, source in eligible:
                if len(transactions) < 50:
                    transactions.append(
                        {
                            **row,
                            "accession": source["accession"],
                            "form": source["form"],
                            "filed_date": source["filed_date"],
                            "change_percent": None if self._uncertain(source) else percent(row),
                        }
                    )
                for doc in self._documents(source, cik):
                    if doc["document_id"] not in seen and len(docs) < 20:
                        docs.append(doc)
                        seen.add(doc["document_id"])
            by_date = defaultdict(set)
            for point in series:
                by_date[point["date"]].add(point["value"])
            history = [
                {"date": day, "value": next(iter(values)), "label": label, "series_key": series_key}
                for day, values in sorted(by_date.items())
                if len(values) == 1
            ][-50:]
            if len(history) < 2 or owner.startswith("unresolved:") or self._uncertain(filing):
                history = []
            code, ad = latest.get("transaction_code"), latest.get("acquired_disposed")
            action = (
                "Reported holding"
                if latest.get("is_holding")
                else "Purchase"
                if code == "P" and ad == "A"
                else "Sale"
                if code == "S" and ad == "D"
                else {
                    "A": "Award or grant",
                    "M": "Exercise or conversion",
                    "F": "Shares withheld or delivered for exercise or tax",
                    "G": "Gift",
                    "D": "Disposition to issuer",
                    "J": "Other transaction; read explanation",
                }.get(code, f"Reported transaction ({code or 'code unavailable'})")
            )
            badges = ["Partial history"]
            if self._uncertain(filing):
                badges.append("Amendment or revised source — comparison unknown")
            if latest.get("is_10b5_1"):
                badges.append("Filing indicates a 10b5-1 plan")
            if latest.get("footnotes"):
                badges.append("Read filing footnotes")
            cards.append(
                {
                    "id": digest([cik, owner]),
                    "name": latest.get("owner_name") or "Reporting owner unavailable",
                    "role": latest.get("officer_title")
                    or (
                        "Director"
                        if latest.get("is_director")
                        else "10% beneficial owner"
                        if latest.get("is_ten_percent_owner")
                        else "Reporting owner; role unspecified"
                    ),
                    "summary": action,
                    "date": latest.get("transaction_date") or filing["report_period"] or filing["filed_date"],
                    "reported_date": filing["filed_date"],
                    "badges": badges,
                    "history": history,
                    "history_note": label + ". Reported bucket balances; not the person's total holdings."
                    if history
                    else "Insufficient compatible balance observations. No person-total holding is inferred.",
                    "metrics": [
                        {
                            "label": "Reported transaction shares"
                            if not latest.get("is_holding")
                            else "Reported bucket shares",
                            "value": str(
                                (latest.get("owned_after") if latest.get("is_holding") else latest.get("shares"))
                                if (latest.get("owned_after") if latest.get("is_holding") else latest.get("shares"))
                                is not None
                                else "Unknown"
                            ),
                        },
                        {
                            "label": "Reported price per share",
                            "value": str(latest.get("price") if latest.get("price") is not None else "Unknown"),
                        },
                        {
                            "label": "Change / preceding bucket balance",
                            "value": (percent(latest) + "%")
                            if percent(latest) is not None and not self._uncertain(filing)
                            else "Unknown",
                        },
                    ],
                    "documents": docs,
                    "transactions": transactions,
                }
            )
        return cards

    def _institution_cards(self, cik, to_date=None):
        mapped = {
            row["cusip"]
            for row in self.index.query("SELECT cusip FROM ownership_security_mappings WHERE issuer_cik=?", [cik])
        }
        if not mapped:
            return []
        managers = {
            row["manager_cik"]
            for row in self.index.query(
                "SELECT DISTINCT p.manager_cik FROM ownership_institutions p JOIN ownership_"
                "ingest_state s ON s.current_filing_id=p.filing_id JOIN ownership_security_m"
                "appings m ON m.cusip=p.cusip WHERE m.issuer_cik=?",
                [cik],
            )
        }
        filings = {
            row["id"]: row
            for row in self._filings("institutions", managers=managers)
            if not to_date or row["filed_date"] <= to_date
        }
        rows = defaultdict(list)
        for row in self.index.query(
            "SELECT p.* FROM ownership_institutions p JOIN ownership_ingest_state s ON s"
            ".current_filing_id=p.filing_id JOIN ownership_security_mappings m ON m.cusi"
            "p=p.cusip WHERE m.issuer_cik=?",
            [cik],
        ):
            if row["filing_id"] in filings:
                item = json.loads(row["record"])
                item["cusip"] = row["cusip"]
                rows[row["filing_id"]].append(item)
                if row["cusip"] in mapped:
                    managers.add(row["manager_cik"])
        cards = []

        def key_for(row):
            return (
                row["cusip"],
                row.get("security_title"),
                row.get("share_type"),
                row.get("put_call") or "",
            )

        for manager in managers:
            periods = defaultdict(list)
            for filing in filings.values():
                if filing["manager_cik"] == manager and filing["report_period"]:
                    periods[filing["report_period"]].append(filing)
            if not periods:
                continue
            period = max(periods)
            latest = max(periods[period], key=lambda item: (item["filed_date"], item["id"]))
            prior_period = previous_quarter(period)
            prior_candidates = periods.get(prior_period, [])
            prior = (
                max(prior_candidates, key=lambda item: (item["filed_date"], item["id"])) if prior_candidates else None
            )
            latest_rows, prior_rows = defaultdict(list), defaultdict(list)
            for row in rows[latest["id"]]:
                if row["cusip"] in mapped:
                    latest_rows[key_for(row)].append(row)
            if prior:
                for row in rows[prior["id"]]:
                    if row["cusip"] in mapped:
                        prior_rows[key_for(row)].append(row)
            safe = (
                len(periods[period]) == 1
                and not self._uncertain(latest)
                and bool(prior)
                and len(prior_candidates) == 1
                and not self._uncertain(prior)
            )
            for key in latest_rows.keys() | prior_rows.keys():
                current, earlier = latest_rows[key], prior_rows[key]
                value = number(current[0].get("shares")) if len(current) == 1 else None
                before = number(earlier[0].get("shares")) if len(earlier) == 1 else None
                summary = "First observed position; comparison unavailable"
                if not current:
                    summary = (
                        "No longer reported; not a confirmed exit"
                        if safe and before is not None
                        else "Current position unknown; comparison unavailable"
                    )
                elif safe and value is not None and before is not None:
                    summary = (
                        "Increased reported position"
                        if value > before
                        else "Reduced reported position"
                        if value < before
                        else "Unchanged reported position"
                    )
                elif self._uncertain(latest) or len(periods[period]) != 1:
                    summary = "Amendment or confidential omission; comparison unknown"
                elif len(current) > 1:
                    summary = "Multiple reported rows; shares not combined"
                elif prior and not earlier:
                    summary = (
                        "Newly reported position; purchase timing unknown"
                        if safe
                        else "Reported position; baseline uncertain"
                    )
                record = json.loads(latest["record"])
                label = f"{key[1]} · {key[2] or 'unit unknown'} · {key[3] or 'non-option'} · CUSIP {key[0]}"
                history = []
                if safe and value is not None and before is not None:
                    series = digest([manager, key])
                    history = [
                        {"date": prior_period, "value": quantity(before), "label": label, "series_key": series},
                        {"date": period, "value": quantity(value), "label": label, "series_key": series},
                    ]
                documents = self._documents(latest, cik) + (self._documents(prior, cik) if prior else [])
                cards.append(
                    {
                        "id": digest([manager, key]),
                        "name": record.get("manager_name") or f"Manager CIK {manager}",
                        "role": "13F reporting manager",
                        "summary": summary,
                        "date": period,
                        "reported_date": latest["filed_date"],
                        "badges": ["Reported quarter-end holdings", "Partial history"],
                        "history": history,
                        "history_note": label + ". Adjacent reported quarters only; not trading activity."
                        if history
                        else "A compatible adjacent-quarter baseline is unavailable or uncertain.",
                        "metrics": [
                            {
                                "label": "Reported shares"
                                if key[2] == "SH"
                                else f"Reported amount ({key[2] or 'unit unknown'})",
                                "value": quantity(value) if value is not None else "Not combined / unknown",
                            },
                            {
                                "label": "Reported value (USD)",
                                "value": str(current[0].get("value_usd"))
                                if len(current) == 1 and current[0].get("value_usd") is not None
                                else "Unknown",
                            },
                        ],
                        "documents": documents,
                        "transactions": [],
                    }
                )
        return cards

    def _event_cards(self, cik):
        filings = {row["id"]: row for row in self._filings("events", cik=cik)}
        cards = []
        for row in self.index.query("SELECT * FROM ownership_events WHERE issuer_cik=?", [cik]):
            if row["filing_id"] not in filings:
                continue
            event, filing = json.loads(row["record"]), filings[row["filing_id"]]
            people = event.get("reporting_people") or []
            metrics = []
            for person in people:
                name = person.get("name") or "Reporting person"
                for field, label in (("shares", "reported shares"), ("percent", "reported percentage")):
                    if person.get(field) is not None:
                        metrics.append(
                            {
                                "label": f"{name} — {label}",
                                "value": str(person[field]) + ("%" if field == "percent" else ""),
                            }
                        )
            cards.append(
                {
                    "id": row["id"],
                    "name": "; ".join(person.get("name") or "Unnamed reporting person" for person in people)
                    or "Reporting persons unavailable",
                    "role": event.get("filing_category") or "Beneficial ownership reporting group",
                    "summary": f"Beneficial ownership disclosure ({filing['form']})",
                    "date": event.get("event_date") or filing["filed_date"],
                    "reported_date": filing["filed_date"],
                    "badges": ["Amendment — inspect original context"]
                    if self._uncertain(filing)
                    else ["Disclosed beneficial ownership"],
                    "history": [],
                    "history_note": "Separate reporting-person disclosures; percentages are not summed into a gr"
                    "oup stake.",
                    "metrics": metrics,
                    "documents": self._documents(filing, cik),
                    "transactions": [],
                }
            )
        return cards

    def _cards(self, cik, kind, direction, from_date, to_date):
        if (
            kind not in KINDS
            or direction not in {"all", "buys", "sales"}
            or (kind != "insiders" and direction != "all")
        ):
            raise ValueError("Choose a separate ownership flow and an eligible insider direction.")
        if from_date:
            from_date = iso(from_date)
        if to_date:
            to_date = iso(to_date)
        if from_date and to_date and from_date > to_date:
            raise ValueError("The from date must not be after the to date.")
        if kind == "insiders":
            cards = self._insider_cards(cik, direction, from_date, to_date)
        elif kind == "institutions":
            cards = self._institution_cards(cik, to_date)
        else:
            cards = self._event_cards(cik)
        cards = [
            card
            for card in cards
            if (not from_date or card["reported_date"] >= from_date)
            and (not to_date or card["reported_date"] <= to_date)
        ]
        return sorted(cards, key=lambda card: (card["reported_date"], card["date"], card["id"]), reverse=True)

    def flow(self, cik, kind, limit=20, offset=0, direction="all", from_date=None, to_date=None):
        cik = cik_value(cik)
        if not 1 <= limit <= 50 or not 0 <= offset <= 1_000_000:
            raise ValueError("Invalid ownership pagination.")
        with self.index.transaction(read_only=True):
            cards = self._cards(cik, kind, direction, from_date, to_date)
            result = {
                "flow": kind,
                "cik": cik,
                "items": cards[offset : offset + limit],
                "total": len(cards),
                "limit": limit,
                "offset": offset,
                "next_offset": offset + limit if offset + limit < len(cards) else None,
                "coverage": self.coverage(cik),
            }
            if kind == "insiders":
                result["purchase_cluster"] = self.purchase_cluster(cik, from_date, to_date)
            return result

    def purchase_cluster(self, cik, from_date=None, to_date=None):
        end = iso(to_date) if to_date else date.today().isoformat()
        start = iso(from_date) if from_date else (date.fromisoformat(end) - timedelta(days=30)).isoformat()
        identities = set()
        for row in self.index.query(
            "SELECT i.record,i.owner_key,i.filing_id,f.record filing_record FROM ownersh"
            "ip_insiders i JOIN ownership_filings f ON f.id=i.filing_id JOIN ownership_i"
            "ngest_state s ON s.current_filing_id=f.id WHERE i.issuer_cik=? AND f.filed_"
            "date>=? AND f.filed_date<=?",
            [cik, start, end],
        ):
            item, filing = json.loads(row["record"]), json.loads(row["filing_record"])
            if (
                item.get("is_holding")
                or item.get("transaction_code") != "P"
                or item.get("acquired_disposed") != "A"
                or filing.get("is_amendment")
                or filing.get("source_revision_observed")
            ):
                continue
            if item.get("joint_reporting"):
                # A jointly reported trade does not become an independent multi-person cluster.
                identity = "joint:" + row["filing_id"]
            elif row["owner_key"].startswith("cik:"):
                identity = row["owner_key"]
            else:
                continue
            identities.add(identity)
        return {
            "unique_reporting_identities": len(identities),
            "from": start,
            "to": end,
            "note": "Observed P acquisitions filed in this window. Joint reporting copies count "
            "as one group; grants and exercises are excluded. Partial coverage.",
        }

    def _comparison_link(self, filing, cik):
        if filing["kind"] != "institutions" or self._uncertain(filing):
            return None
        current = self._filings("institutions", managers=[filing["manager_cik"]])
        period = filing["report_period"]
        same = [row for row in current if row["report_period"] == period]
        previous = [row for row in current if row["report_period"] == previous_quarter(period)]
        if len(same) != 1 or same[0]["id"] != filing["id"] or len(previous) != 1 or self._uncertain(previous[0]):
            return None
        rows = self.index.query(
            "SELECT p.id FROM ownership_institutions p JOIN ownership_security_mappings "
            "m ON m.cusip=p.cusip WHERE p.filing_id=? AND m.issuer_cik=? LIMIT 1",
            [previous[0]["id"], cik],
        )
        return (
            {
                "type": "adjacent_quarter_comparison",
                "prior_accession": previous[0]["accession"],
                "note": "The preceding quarter contains a verified issuer position. This filing cont"
                "ains no mapped issuer row; absence is not a confirmed exit.",
            }
            if rows
            else None
        )

    def document(self, cik, document_id):
        cik = cik_value(cik)
        if not re.fullmatch(r"[0-9a-f]{64}", str(document_id)):
            return None
        with self.index.transaction(read_only=True):
            for filing in self.index.query(
                "SELECT * FROM ownership_filings WHERE documents LIKE ?", ["%" + document_id + "%"]
            ):
                source = next(
                    (row for row in json.loads(filing["documents"]) if row["document_id"] == document_id), None
                )
                if not source:
                    continue
                if filing["kind"] == "institutions":
                    rows = self.index.query(
                        "SELECT p.record FROM ownership_institutions p JOIN ownership_security_mappi"
                        "ngs m ON m.cusip=p.cusip WHERE p.filing_id=? AND m.issuer_cik=?",
                        [filing["id"], cik],
                    )
                    linkage = {"type": "verified_cusip_position"} if rows else self._comparison_link(filing, cik)
                    if not linkage:
                        continue
                else:
                    if filing["issuer_cik"] != cik:
                        continue
                    linkage = {"type": "structured_subject_issuer"}
                    table = "ownership_insiders" if filing["kind"] == "insiders" else "ownership_events"
                    rows = self.index.query(
                        f"SELECT record FROM {table} WHERE filing_id=? AND issuer_cik=?", [filing["id"], cik]
                    )
                records = [json.loads(row["record"]) for row in rows]
                with self.storage.open(source["raw_path"], "rb") as stream:
                    raw = stream.read(25_000_001)
                if len(raw) != source["content_bytes"] or hashlib.sha256(raw).hexdigest() != source["sha256"]:
                    raise SourceIntegrityError(
                        "Stored ownership source failed integrity verification; reingest the source."
                    )
                metadata = next(row for row in self._documents(filing, cik) if row["document_id"] == document_id)
                return {
                    "document": metadata,
                    "filing": json.loads(filing["record"]),
                    "kind": filing["kind"],
                    "rows": records if filing["kind"] != "events" else [],
                    "event": records[0] if filing["kind"] == "events" else None,
                    "linkage": linkage,
                    "raw_text": raw[:1_000_000].decode("utf-8", errors="replace"),
                    "raw_truncated": len(raw) > 1_000_000,
                }
        return None

    def feed(self, ciks, since, kind, limit=50):
        issuers = list(dict.fromkeys(cik_value(value) for value in ciks))
        if not issuers or len(issuers) > 200 or not 1 <= limit <= 100 or kind not in KINDS:
            raise ValueError("Choose 1–200 companies and a separate ownership flow.")
        since = iso(str(since)[:10]) if since else None
        with self.index.transaction(read_only=True):
            items = [
                dict(card, issuer_cik=cik) for cik in issuers for card in self._cards(cik, kind, "all", since, None)
            ]
            items.sort(key=lambda card: (card["reported_date"], card["date"], card["id"]), reverse=True)
            return {
                "flow": kind,
                "items": items[:limit],
                "total": len(items),
                "coverage": {**self.coverage(), "companies": [{"cik": cik, **self.coverage(cik)} for cik in issuers]},
            }

    def notification_events(self, ciks, since, kind, limit=100, offset=0):
        issuers = list(dict.fromkeys(cik_value(value) for value in ciks))
        if not issuers or len(issuers) > 200 or kind not in KINDS or not 1 <= limit <= 500 or offset < 0:
            raise ValueError("Invalid ownership notification scope.")
        since = iso(str(since)[:10]) if since else None
        events = []
        with self.index.transaction(read_only=True):
            for cik in issuers:
                if kind == "institutions":
                    managers = [
                        row["manager_cik"]
                        for row in self.index.query(
                            "SELECT DISTINCT p.manager_cik FROM ownership_institutions p JOIN ownership_"
                            "ingest_state s ON s.current_filing_id=p.filing_id JOIN ownership_security_m"
                            "appings m ON m.cusip=p.cusip WHERE m.issuer_cik=?",
                            [cik],
                        )
                    ]
                    filings = self._filings(kind, managers=managers)
                else:
                    filings = self._filings(kind, cik=cik)
                for filing in filings:
                    if since and filing["filed_date"] < since:
                        continue
                    if kind == "institutions":
                        direct = self.index.query(
                            "SELECT p.id FROM ownership_institutions p JOIN ownership_security_mappings "
                            "m ON m.cusip=p.cusip WHERE p.filing_id=? AND m.issuer_cik=? LIMIT 1",
                            [filing["id"], cik],
                        )
                        if not direct and not self._comparison_link(filing, cik):
                            continue
                    record = json.loads(filing["record"])
                    events.append(
                        {
                            "id": digest([filing["id"], cik, kind]),
                            "cik": cik,
                            "accession": filing["accession"],
                            "form": filing["form"],
                            "filed_date": filing["filed_date"],
                            "name": record.get("manager_name") or record.get("issuer_name") or "Ownership disclosure",
                            "summary": f"{filing['form']} ownership filing observed; "
                            "inspect its reported date and source context.",
                            "source_url": record["source_url"],
                        }
                    )
            return sorted(events, key=lambda row: (row["filed_date"], row["accession"], row["id"]))[
                offset : offset + limit
            ]

    def export_rows(self, cik, kind, direction="all", from_date=None, to_date=None):
        cik = cik_value(cik)
        if (
            kind not in KINDS
            or direction not in {"all", "buys", "sales"}
            or (kind != "insiders" and direction != "all")
        ):
            raise ValueError("Invalid ownership export flow/filter.")
        if from_date:
            from_date = iso(from_date)
        if to_date:
            to_date = iso(to_date)
        if from_date and to_date and from_date > to_date:
            raise ValueError("Invalid date range.")
        table = {
            "insiders": "ownership_insiders",
            "institutions": "ownership_institutions",
            "events": "ownership_events",
        }[kind]
        join = " JOIN ownership_security_mappings m ON m.cusip=r.cusip" if kind == "institutions" else ""
        scope = "m.issuer_cik=?" if kind == "institutions" else "r.issuer_cik=?"
        args = [cik]
        for key, operator, value in (("filed_date", ">=", from_date), ("filed_date", "<=", to_date)):
            if value:
                scope += f" AND f.{key}{operator}?"
                args.append(value)
        output = []
        with self.index.transaction(read_only=True):
            # Bounded row retrieval is separate from the deliberately bounded card expanders.
            records = self.index.query(
                f"SELECT r.record row_record,f.record filing_record FROM {table} r "
                "JOIN ownership_filings f ON f.id=r.filing_id "
                "JOIN ownership_ingest_state s ON s.current_filing_id=f.id"
                + join
                + " WHERE "
                + scope
                + " ORDER BY f.filed_date,f.accession,r.id LIMIT 10001",
                args,
            )
            if len(records) > 10000:
                raise ValueError(
                    "More than 10,000 ownership rows match. Narrow the filing-date range before exporting."
                )
            for item in records:
                row, filing = json.loads(item["row_record"]), json.loads(item["filing_record"])
                if (
                    kind == "insiders"
                    and direction != "all"
                    and (
                        row.get("is_holding")
                        or row.get("transaction_code") != ("P" if direction == "buys" else "S")
                        or row.get("acquired_disposed") != ("A" if direction == "buys" else "D")
                    )
                ):
                    continue
                base = {
                    "issuer_cik": cik,
                    "accession": filing["accession"],
                    "form": filing["form"],
                    "filed_date": filing["filed_date"],
                    "source_url": filing["source_url"],
                }
                if kind == "events":
                    for person in row.get("reporting_people") or [{}]:
                        output.append(
                            {
                                **base,
                                "event_date": row.get("event_date"),
                                "category": row.get("filing_category"),
                                "cusips": encode(row.get("cusips") or []),
                                "reporting_person_cik": person.get("cik"),
                                "reporting_person": person.get("name"),
                                "shares": person.get("shares"),
                                "percent": person.get("percent"),
                                "purpose": row.get("purpose"),
                            }
                        )
                else:
                    fields = (
                        (
                            "owner_cik",
                            "owner_name",
                            "transaction_group_id",
                            "security_title",
                            "ownership_form",
                            "nature_of_ownership",
                            "is_derivative",
                            "transaction_date",
                            "transaction_code",
                            "acquired_disposed",
                            "shares",
                            "price",
                            "owned_after",
                            "is_holding",
                            "footnotes",
                        )
                        if kind == "insiders"
                        else (
                            "cusip",
                            "security_title",
                            "shares",
                            "share_type",
                            "put_call",
                            "value_usd",
                            "discretion",
                            "other_managers",
                            "voting_sole",
                            "voting_shared",
                            "voting_none",
                        )
                    )
                    output.append(
                        {
                            **base,
                            **{
                                key: encode(row.get(key)) if isinstance(row.get(key), (list, dict)) else row.get(key)
                                for key in fields
                            },
                            **(
                                {
                                    "report_period": filing.get("report_period"),
                                    "manager_cik": filing.get("manager_cik"),
                                    "manager_name": filing.get("manager_name"),
                                }
                                if kind == "institutions"
                                else {}
                            ),
                        }
                    )
                if len(output) > 10000:
                    raise ValueError(
                        "More than 10,000 ownership rows match. Narrow the filing-date range before exporting."
                    )
        return output
