"""Bounded operational metadata for platform operators; no private research bodies."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from filings_hub.platform.catalog import SOURCE_REGISTER
from filings_hub.platform_admin import AdminStore, fingerprint
from filings_hub.tenancy import SecurityError, stamp


def pagination(q: str, limit: int, offset: int):
    if len(q) > 150 or not 1 <= limit <= 100 or not 0 <= offset <= 1_000_000:
        raise SecurityError(422, "Search is limited to 150 characters, page size 1–100 and offset 0–1,000,000.")


def page(rows: list[dict], q: str, limit: int, offset: int, fields: tuple[str, ...]) -> dict:
    pagination(q, limit, offset)
    matched = [row for row in rows if q.casefold() in " ".join(str(row.get(key) or "") for key in fields).casefold()]
    return {"items": matched[offset : offset + limit], "total": len(matched), "limit": limit, "offset": offset}


class Operations:
    def __init__(self, admin: AdminStore, database):
        self.admin, self.security, self.database = admin, admin.security, database

    def _user(self, tx, user) -> dict:
        control = self.admin.control(tx, user.id)
        return {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "company": user.company,
            "created_at": user.created_at,
            "plan": user.plan,
            "status": control["status"],
            "revision": control["revision"],
        }

    def users(self, token: str, q="", limit=25, offset=0):
        pagination(q, limit, offset)
        with self.admin.transaction() as tx:
            self.admin.authorize(tx, token)
            if self.security.database_url:
                pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                clause = (
                    "lower(email || ' ' || coalesce(first_name,'') || ' ' || "
                    "coalesce(last_name,'') || ' ' || id) LIKE lower(%s)"
                )
                total = tx.conn.execute(f"SELECT count(*) FROM users WHERE {clause}", (pattern,)).fetchone()[0]
                ids = tx.conn.execute(
                    f"SELECT id FROM users WHERE {clause} ORDER BY created_at DESC,id LIMIT %s OFFSET %s",
                    (pattern, limit, offset),
                ).fetchall()
                return {
                    "items": [self._user(tx, self.security.users.get_user(row[0])) for row in ids],
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }
            rows = []
            for rel in self.security.storage.ls("users"):
                name = rel.rsplit("/", 1)[-1]
                if name.endswith(".json"):
                    user = self.security.users.get_user(name[:-5])
                    if user:
                        rows.append(self._user(tx, user))
            rows.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
            return page(rows, q, limit, offset, ("email", "first_name", "last_name", "id"))

    def user(self, token: str, uid: str):
        with self.admin.transaction("user:" + uid) as tx:
            self.admin.authorize(tx, token)
            user = self.security.users.get_user(uid)
            if not user:
                raise SecurityError(404, "Account not found.")
            sessions = [
                {key: row[key] for key in ("id", "created_at", "expires_at", "last_seen_at", "device_label")}
                for row in tx.find("sessions", user_id=uid)
                if self.security.active(row, self.admin.clock())
            ]
            memberships = [{**row, "version": fingerprint(row)} for row in tx.find("memberships", user_id=uid)]
            return {
                "user": self._user(tx, user),
                "sessions": sessions,
                "memberships": memberships,
                "note": "Operational metadata only. Private notes, preferences and research exports are not exposed.",
            }

    def organizations(self, token: str, q="", limit=25, offset=0):
        pagination(q, limit, offset)
        with self.admin.transaction() as tx:
            self.admin.authorize(tx, token)
            if self.security.database_url:
                pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                where = "lower(record->>'name' || ' ' || id) LIKE lower(%s)"
                total = tx.conn.execute(f"SELECT count(*) FROM organizations WHERE {where}", (pattern,)).fetchone()[0]
                rows = [
                    row[0]
                    for row in tx.conn.execute(
                        f"SELECT record FROM organizations WHERE {where} "
                        "ORDER BY record->>'created_at' DESC,id LIMIT %s OFFSET %s",
                        (pattern, limit, offset),
                    )
                ]
                return {"items": rows, "total": total, "limit": limit, "offset": offset}
            rows = sorted(tx.find("organizations"), key=lambda row: (row["created_at"], row["id"]), reverse=True)
            return page(rows, q, limit, offset, ("id", "name"))

    def organization(self, token: str, org: str):
        with self.admin.transaction("org:" + org) as tx:
            self.admin.authorize(tx, token)
            row = tx.get("organizations", org)
            if not row:
                raise SecurityError(404, "Organization not found.")
            members = []
            for member in tx.find("memberships", organization_id=org):
                user = self.security.users.get_user(member["user_id"])
                members.append({**member, "email": user.email if user else None, "version": fingerprint(member)})
            return {
                "organization": row,
                "members": members,
                "note": "Organization roles control team access; they never grant platform administrator access.",
            }

    def audit(self, token: str, q="", limit=25, offset=0):
        pagination(q, limit, offset)
        with self.admin.transaction() as tx:
            self.admin.authorize(tx, token)
            if self.security.database_url:
                pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                where = "lower(actor_id || ' ' || action || ' ' || target_id) LIKE lower(%s)"
                total = tx.conn.execute(
                    f"SELECT count(*) FROM platform_admin_audit WHERE {where}", (pattern,)
                ).fetchone()[0]
                rows = [
                    row[0]
                    for row in tx.conn.execute(
                        f"SELECT record FROM platform_admin_audit WHERE {where} "
                        "ORDER BY record->>'at' DESC,id DESC LIMIT %s OFFSET %s",
                        (pattern, limit, offset),
                    )
                ]
                return {"items": rows, "total": total, "limit": limit, "offset": offset}
            rows = sorted(tx.find("platform_admin_audit"), key=lambda row: (row["at"], row["id"]), reverse=True)
            return page(rows, q, limit, offset, ("actor_id", "action", "target_id"))

    def research(self, token: str, *, q="", limit=25, offset=0):
        pagination(q, limit, offset)
        with self.admin.transaction() as tx:
            self.admin.authorize(tx, token)
        from filings_hub.research_index import open_index

        index = None
        try:
            index = open_index(self.security.storage, self.security.database_url)
            with index.transaction(read_only=True):
                coverage = index.coverage()
                pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                where = (
                    "source_id='sec-edgar' AND visibility='public' AND status IN ('failed','unsupported','pending') "
                    "AND lower(document_id || ' ' || filename) LIKE lower(?) ESCAPE '\\'"
                )
                total = int(index.query(f"SELECT count(*) n FROM research_documents WHERE {where}", [pattern])[0]["n"])
                failures = index.query(
                    "SELECT document_id,filename,cik,accession,status,error,attempted_at FROM research_documents WHERE "
                    + where
                    + " ORDER BY document_id LIMIT ? OFFSET ?",
                    [pattern, limit, offset],
                )
                inventories = index.query(
                    "SELECT cik,accession,inventory_status,inventory_error,checked_at FROM research_filings "
                    "WHERE inventory_status!='complete' ORDER BY cik,accession LIMIT 100"
                )
            last = coverage.get("last_discovery_at")
            age = max(0, int(self.admin.clock() - datetime.fromisoformat(last).timestamp())) if last else None
            return {
                "state": "available",
                "coverage": coverage,
                "discovery_age_seconds": age,
                "freshness": "unknown" if age is None else "stale" if age > 86400 else "observed_recently",
                "freshness_note": "24-hour operational threshold; this is not a provider delivery guarantee.",
                "failures": {"items": failures, "total": total, "limit": limit, "offset": offset},
                "incomplete_inventories": inventories,
                "inventory_list_limit": 100,
            }
        except Exception as error:
            return {"state": "unavailable", "reason": f"Research index cannot be inspected ({type(error).__name__})."}
        finally:
            if index:
                index.close()

    def overview(self, token: str):
        users = self.users(token, limit=1)
        organizations = self.organizations(token, limit=1)
        publication: dict[str, Any] = {"state": "not_applicable", "backend": self.database.backend}
        try:
            runs = self.database.query(
                "SELECT run_id,status,started_at,finished_at FROM run_log ORDER BY started_at DESC LIMIT 5"
            )
            if self.database.backend == "postgres":
                rows = self.database.query(
                    "SELECT publication_id,kind,published_at,counts FROM serving_publications "
                    "ORDER BY published_at DESC LIMIT 1"
                )
                publication = {
                    "state": "available" if rows else "not_observed",
                    "publication": rows[0] if rows else None,
                }
        except Exception as error:
            runs = []
            publication = {"state": "unavailable", "reason": type(error).__name__}
        return {
            "observed_at": stamp(self.admin.clock()),
            "users": users["total"],
            "organizations": organizations["total"],
            "backend": "postgres" if self.security.database_url else "single_process_lake_development",
            "publication": publication,
            "recent_ingest_runs": runs,
            "research": self.research(token),
            "assurance": "Production availability, licensing and independent security assurance are separate gates.",
        }

    def sources(self, token: str):
        with self.admin.transaction() as tx:
            self.admin.authorize(tx, token)
        return {
            "sources": SOURCE_REGISTER,
            "editable": False,
            "note": (
                "This register describes implemented software and unconnected providers. "
                "Rights and credentials cannot be granted by a toggle."
            ),
        }

    def jobs(self, token: str, *, q="", limit=25, offset=0):
        pagination(q, limit, offset)
        with self.admin.transaction() as tx:
            self.admin.authorize(tx, token)
            if self.security.database_url:
                unresolved = [
                    row[0]
                    for row in tx.conn.execute(
                        "SELECT record FROM platform_admin_job_commands WHERE status IN ('pending','unknown') "
                        "ORDER BY record->>'created_at' DESC LIMIT 25"
                    )
                ]
            else:
                unresolved = sorted(
                    (row for row in tx.find("platform_job_commands") if row["status"] in {"pending", "unknown"}),
                    key=lambda row: row["created_at"],
                    reverse=True,
                )[:25]
        try:
            with self.job_engine() as engine:
                if q:
                    pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                    where = "lower(id || ' ' || status) LIKE lower(?) ESCAPE '\\'"
                    total = int(
                        engine.index.query(f"SELECT count(*) n FROM research_jobs WHERE {where}", [pattern])[0]["n"]
                    )
                    rows = engine.index.query(
                        f"SELECT record FROM research_jobs WHERE {where} ORDER BY id LIMIT ? OFFSET ?",
                        [pattern, limit, offset],
                    )
                    jobs = [json.loads(row["record"]) for row in rows]
                else:
                    result = engine.list(limit=limit, offset=offset)
                    jobs, total = result["jobs"], result["total"]
                return {
                    "state": "available",
                    "jobs": [self.public_job(job) for job in jobs],
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "health": engine.health(),
                    "unresolved_commands": unresolved,
                }
        except Exception as error:
            return {
                "state": "unavailable",
                "jobs": [],
                "total": None,
                "unresolved_commands": unresolved,
                "reason": f"Durable job operations are unavailable in this deployment ({type(error).__name__}).",
            }

    @staticmethod
    def public_job(job):
        fields = (
            "id",
            "kind",
            "cik",
            "status",
            "revision",
            "created_at",
            "updated_at",
            "attempts",
            "max_attempts",
            "batches_completed",
            "max_batches",
            "batch_size",
            "fetch",
            "lease_expires_at",
            "not_before",
            "error",
        )
        return {key: job.get(key) for key in fields}

    @contextmanager
    def job_engine(self):
        # Optional integration: the separately delivered engine owns scheduling and worker authority.
        # Never return internal claim tokens, worker IDs, idempotency keys or raw engine records.
        from filings_hub.research_index import open_index
        from filings_hub.research_jobs import ResearchJobs

        index = open_index(self.security.storage, self.security.database_url)
        try:
            yield ResearchJobs(index)
        finally:
            index.close()

    def job_action(self, token: str, job_id: str, action: str, payload: dict):
        if action not in {"retry", "cancel"}:
            raise SecurityError(422, "Only reviewed retry or cancellation is available.")
        reason = self.admin.review(payload, f"job.{action}", job_id)
        expected = payload.get("expected_revision")
        if type(expected) is not int or expected < 1:
            raise SecurityError(422, "A positive expected job revision is required.")
        with self.admin.transaction() as tx:
            admin, _ = self.admin.authorize(tx, token, fresh=True)
        try:
            with self.job_engine() as engine:
                command = {
                    "id": uuid.uuid4().hex,
                    "job_id": job_id,
                    "action": action,
                    "status": "pending",
                    "created_at": stamp(self.admin.clock()),
                    "expected_revision": expected,
                }
                with self.admin.transaction() as tx:
                    self.admin.authorize(tx, token, fresh=True)
                    tx.put("platform_job_commands", command)
                    self.admin.audit(
                        tx,
                        admin["id"],
                        f"job.{action}.requested",
                        job_id,
                        reason=reason,
                        command_id=command["id"],
                        expected_revision=expected,
                    )
                try:
                    result = getattr(engine, action)(job_id, expected)
                except ValueError as error:
                    with self.admin.transaction() as tx:
                        tx.put("platform_job_commands", {**command, "status": "rejected"})
                        self.admin.audit(tx, admin["id"], f"job.{action}.rejected", job_id, command_id=command["id"])
                    raise SecurityError(
                        409, "The job changed or cannot accept that action; reload and review it again."
                    ) from error
                with self.admin.transaction() as tx:
                    tx.put(
                        "platform_job_commands",
                        {**command, "status": "confirmed", "result_revision": result["revision"]},
                    )
                    self.admin.audit(
                        tx,
                        admin["id"],
                        f"job.{action}.confirmed",
                        job_id,
                        command_id=command["id"],
                        result_revision=result["revision"],
                    )
                return {"job": self.public_job(result), "command_id": command["id"], "status": "confirmed"}
        except SecurityError:
            raise
        except Exception as error:
            raise SecurityError(
                503,
                "Job action was not confirmed. Inspect the job and unresolved command before retrying; "
                "no scheduler was started.",
            ) from error
