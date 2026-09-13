"""Durable session records, tenant membership policy and security audit.

Postgres mutations authorize and write in the same transaction, serialized by tenant/user advisory
locks across processes. The lake development adapter commits one JSON state under a process lock;
it is intentionally unsupported for multiple API processes. No caller-provided tenant header grants
access. Personal preferences remain personal; this module does not migrate them into an organization.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query

from filings_hub import accounts
from filings_hub.lake.storage import Storage

STATE_PATH = "account_security/state.json"
TABLES = {
    "sessions": ("account_sessions", ("user_id",)),
    "organizations": ("organizations", ()),
    "memberships": ("organization_memberships", ("organization_id", "user_id", "role")),
    "audit": ("account_security_audit", ("organization_id", "actor_id")),
    "projects": ("research_projects", ("owner_id", "organization_id")),
    "notes": ("research_notes", ("project_id",)),
    "platform_admins": ("platform_admins", ()),
    "platform_admin_sessions": ("platform_admin_sessions", ("admin_id",)),
    "platform_admin_audit": ("platform_admin_audit", ("actor_id", "action", "target_id")),
    "platform_controls": ("platform_account_controls", ()),
    "platform_settings": ("platform_admin_settings", ()),
    "platform_job_commands": ("platform_admin_job_commands", ("job_id", "status")),
}
ROLES = frozenset({"owner", "admin", "member"})


def stamp(now: float | None = None) -> str:
    return datetime.fromtimestamp(now, UTC).isoformat() if now is not None else datetime.now(UTC).isoformat()


class SecurityError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail
        super().__init__(detail)


class LakeTransaction:
    def __init__(self, state: dict[str, Any]):
        self.state = state
        self.changed = False

    def get(self, kind: str, ident: str) -> dict[str, Any] | None:
        return self.state[kind].get(ident)

    def find(self, kind: str, **filters) -> list[dict[str, Any]]:
        return [r for r in self.state[kind].values() if all(r.get(k) == v for k, v in filters.items())]

    def put(self, kind: str, row: dict[str, Any]) -> None:
        self.state[kind][row["id"]] = row
        self.changed = True

    def delete(self, kind: str, ident: str) -> None:
        del self.state[kind][ident]
        self.changed = True


class PostgresTransaction:
    def __init__(self, conn):
        self.conn = conn

    def get(self, kind: str, ident: str) -> dict[str, Any] | None:
        rows = self.find(kind, id=ident)
        return rows[0] if rows else None

    def find(self, kind: str, **filters) -> list[dict[str, Any]]:
        table, columns = TABLES[kind]
        if not set(filters) <= {"id", *columns}:
            raise ValueError("unsupported security filter")
        where = " AND ".join(f"{key} IS NOT DISTINCT FROM %s" for key in filters) or "true"
        return [r[0] for r in self.conn.execute(f"SELECT record FROM {table} WHERE {where}", tuple(filters.values()))]

    def put(self, kind: str, row: dict[str, Any]) -> None:
        from psycopg.types.json import Jsonb

        table, indexed = TABLES[kind]
        columns = ("id", *indexed, "record")
        updates = ", ".join(f"{key} = EXCLUDED.{key}" for key in (*indexed, "record"))
        self.conn.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('%s' for _ in columns)}) "
            f"ON CONFLICT (id) DO UPDATE SET {updates}",
            (row["id"], *(row.get(key) for key in indexed), Jsonb(row)),
        )

    def delete(self, kind: str, ident: str) -> None:
        self.conn.execute(f"DELETE FROM {TABLES[kind][0]} WHERE id = %s", (ident,))


class SecurityStore:
    def __init__(self, users: accounts.UserStore, storage: Storage, database_url: str = ""):
        self.users, self.storage = users, storage
        self.database_url = database_url if database_url.startswith(("postgresql://", "postgres://")) else ""
        with accounts._LAKE_LOCKS_GUARD:
            self._lock = accounts._LAKE_LOCKS.setdefault(storage.root, threading.RLock())

    @contextmanager
    def transaction(self, scope: str = ""):
        if self.database_url:
            import psycopg

            # Dedicated connection/transaction: unrelated account operations on the legacy shared
            # connection cannot accidentally commit or join a membership authorization transaction.
            with psycopg.connect(self.database_url) as conn:
                if scope:
                    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("security:" + scope,))
                yield PostgresTransaction(conn)
            return
        with self._lock:
            state = (
                json.loads(self.storage.read_text(STATE_PATH))
                if self.storage.exists(STATE_PATH)
                else {kind: {} for kind in TABLES}
            )
            for kind in TABLES:
                state.setdefault(kind, {})
            tx = LakeTransaction(state)
            yield tx
            if tx.changed:
                encoded = json.dumps(state)
                if self.storage.is_remote:
                    self.storage.write_text(STATE_PATH, encoded)
                else:
                    target = Path(self.storage.full(STATE_PATH))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    fd, temporary = tempfile.mkstemp(dir=target.parent)
                    try:
                        with os.fdopen(fd, "w") as handle:
                            handle.write(encoded)
                            handle.flush()
                            os.fsync(handle.fileno())
                        os.replace(temporary, target)
                    finally:
                        if os.path.exists(temporary):
                            os.unlink(temporary)

    @staticmethod
    def audit(tx, actor: str, action: str, target: str, org: str | None = None, **metadata) -> None:
        tx.put(
            "audit",
            {
                "id": uuid.uuid4().hex,
                "organization_id": org,
                "actor_id": actor,
                "action": action,
                "target_id": target,
                "at": stamp(),
                "metadata": metadata,
            },
        )

    def create_session(self, record: dict[str, Any]) -> None:
        if self.users.get_user(record["user_id"]) is None:
            raise SecurityError(401, "sign in required")
        with self.transaction("user:" + record["user_id"]) as tx:
            if (tx.get("platform_controls", record["user_id"]) or {}).get("status") == "suspended":
                raise SecurityError(403, "this account is suspended; contact support")
            tx.put("sessions", record)
            self.audit(tx, record["user_id"], "session.created", record["id"])

    @staticmethod
    def active(record: dict[str, Any] | None, now: float) -> bool:
        return bool(
            record and not record.get("revoked_at") and datetime.fromisoformat(record["expires_at"]).timestamp() > now
        )

    def session(self, ident: str, user_id: str, now: float) -> dict[str, Any] | None:
        with self.transaction("user:" + user_id) as tx:
            if (tx.get("platform_controls", user_id) or {}).get("status") == "suspended":
                return None
            record = tx.get("sessions", ident)
            if not self.active(record, now) or record["user_id"] != user_id:
                return None
            if now - datetime.fromisoformat(record["last_seen_at"]).timestamp() >= 300:
                record = {**record, "last_seen_at": stamp(now)}
                tx.put("sessions", record)
            return record

    def sessions(self, user_id: str, now: float) -> list[dict[str, Any]]:
        with self.transaction() as tx:
            return sorted(
                (r for r in tx.find("sessions", user_id=user_id) if self.active(r, now)),
                key=lambda r: r["created_at"],
                reverse=True,
            )

    def revoke(self, user_id: str, ident: str, now: float) -> bool:
        with self.transaction("user:" + user_id) as tx:
            record = tx.get("sessions", ident)
            if not record or record["user_id"] != user_id:
                raise SecurityError(404, "session not found")
            if record.get("revoked_at"):
                return False
            tx.put("sessions", {**record, "revoked_at": stamp(now)})
            self.audit(tx, user_id, "session.revoked", ident)
            return True

    def revoke_others(self, user_id: str, current: str, now: float) -> int:
        with self.transaction("user:" + user_id) as tx:
            keep = tx.get("sessions", current)
            if not self.active(keep, now) or keep["user_id"] != user_id:
                raise SecurityError(401, "sign in required")
            revoked = 0
            for row in tx.find("sessions", user_id=user_id):
                if row["id"] != current and self.active(row, now):
                    tx.put("sessions", {**row, "revoked_at": stamp(now)})
                    self.audit(tx, user_id, "session.revoked", row["id"], reason="revoke_others")
                    revoked += 1
            return revoked

    @staticmethod
    def membership_id(org: str, user: str) -> str:
        return f"{org}:{user}"

    def authorize(self, tx, org: str, actor: str, roles=ROLES) -> tuple[dict[str, Any], dict[str, Any]]:
        organization = tx.get("organizations", org)
        member = tx.get("memberships", self.membership_id(org, actor))
        if not organization or not member or member["role"] not in ROLES:
            raise SecurityError(404, "organization not found")
        if member["role"] not in roles:
            raise SecurityError(403, "organization role does not allow this action")
        return organization, member

    def organizations(self, actor: str) -> list[dict[str, Any]]:
        with self.transaction() as tx:
            out = []
            for member in tx.find("memberships", user_id=actor):
                org = tx.get("organizations", member["organization_id"])
                if org and member["role"] in ROLES:
                    out.append({**org, "role": member["role"]})
            return sorted(out, key=lambda r: (r["created_at"], r["id"]))

    def create_organization(self, actor: str, name: Any) -> dict[str, Any]:
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            raise SecurityError(422, "name must contain 1 to 120 characters")
        org = {"id": uuid.uuid4().hex, "name": name.strip(), "created_at": stamp()}
        with self.transaction("user:" + actor) as tx:
            if self.users.get_user(actor) is None:
                raise SecurityError(401, "sign in required")
            tx.put("organizations", org)
            tx.put(
                "memberships",
                {
                    "id": self.membership_id(org["id"], actor),
                    "organization_id": org["id"],
                    "user_id": actor,
                    "role": "owner",
                    "created_at": org["created_at"],
                },
            )
            self.audit(tx, actor, "organization.created", org["id"], org["id"])
        return {**org, "role": "owner"}

    def organization(self, org: str, actor: str) -> dict[str, Any]:
        with self.transaction() as tx:
            organization, member = self.authorize(tx, org, actor)
            return {**organization, "role": member["role"]}

    def members(self, org: str, actor: str) -> list[dict[str, Any]]:
        with self.transaction() as tx:
            self.authorize(tx, org, actor)
            return sorted(tx.find("memberships", organization_id=org), key=lambda r: r["created_at"])

    def change_member(self, org: str, actor: str, target: Any, role: Any = None, action: str = "add") -> dict[str, Any]:
        with self.transaction("org:" + org) as tx:
            _, member = self.authorize(tx, org, actor, {"owner", "admin"})
            if not isinstance(target, str) or len(target) > 100 or not target:
                raise SecurityError(422, "a valid user_id is required")
            ident = self.membership_id(org, target)
            previous = tx.get("memberships", ident)
            if action != "remove" and (not isinstance(role, str) or role not in ROLES):
                raise SecurityError(422, "role must be owner, admin or member")
            if member["role"] == "admin" and (
                role in ("owner", "admin") or (previous and previous["role"] != "member")
            ):
                raise SecurityError(403, "only an owner can manage owners or administrators")
            if action == "add" and previous:
                raise SecurityError(409, "user is already a member")
            if action != "add" and not previous:
                raise SecurityError(404, "membership not found")
            if previous and previous["role"] == "owner" and (action == "remove" or role != "owner"):
                owners = tx.find("memberships", organization_id=org, role="owner")
                if len(owners) <= 1:
                    raise SecurityError(409, "an organization must retain at least one owner")
            if action == "remove":
                tx.delete("memberships", ident)
                self.audit(tx, actor, "membership.removed", target, org, previous_role=previous["role"])
                return {"removed": True}
            if self.users.get_user(target) is None:
                raise SecurityError(422, "user_id must identify an existing account")
            updated = {
                "id": ident,
                "organization_id": org,
                "user_id": target,
                "role": role,
                "created_at": previous["created_at"] if previous else stamp(),
                "updated_at": stamp(),
            }
            tx.put("memberships", updated)
            self.audit(
                tx,
                actor,
                "membership.added" if action == "add" else "membership.role_changed",
                target,
                org,
                role=role,
                previous_role=previous["role"] if previous else None,
            )
            return updated

    def audit_records(self, actor: str, org: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.transaction() as tx:
            if org is not None:
                self.authorize(tx, org, actor, {"owner", "admin"})
                rows = tx.find("audit", organization_id=org)
            else:
                rows = tx.find("audit", actor_id=actor, organization_id=None)
            return sorted(rows, key=lambda r: (r["at"], r["id"]), reverse=True)[:limit]


def security_router(store: SecurityStore, signer: accounts.SessionSigner, current_user) -> APIRouter:
    import time

    router = APIRouter()

    def invoke(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SecurityError as error:
            raise HTTPException(error.status, error.detail) from error

    def session_context(user=Depends(current_user), token: str | None = Header(default=None, alias="X-Session")):
        record = signer.session(token)
        if not record or record["user_id"] != user.id:
            raise HTTPException(401, "sign in required")
        return user, record

    @router.get("/me/sessions")
    def list_sessions(context=Depends(session_context)):
        user, current = context
        rows = store.sessions(user.id, time.time())
        return {
            "current_session_id": current["id"],
            "sessions": [
                {key: row[key] for key in ("id", "created_at", "expires_at", "last_seen_at", "device_label")}
                | {"current": row["id"] == current["id"]}
                for row in rows
            ],
        }

    @router.post("/me/sessions/revoke-others")
    def revoke_others(context=Depends(session_context)):
        user, current = context
        return {"revoked": invoke(store.revoke_others, user.id, current["id"], time.time())}

    @router.delete("/me/sessions/{session_id}")
    def revoke_session(session_id: str, context=Depends(session_context)):
        user, current = context
        ident = current["id"] if session_id == "current" else session_id
        invoke(store.revoke, user.id, ident, time.time())
        return {"revoked": True, "current": ident == current["id"]}

    @router.post("/auth/logout")
    def logout(context=Depends(session_context)):
        user, current = context
        invoke(store.revoke, user.id, current["id"], time.time())
        return {"revoked": True}

    @router.get("/me/security-audit")
    def personal_audit(limit: int = Query(100, ge=1, le=500), user=Depends(current_user)):
        return {"events": store.audit_records(user.id, limit=limit)}

    @router.get("/organizations")
    def list_organizations(user=Depends(current_user)):
        return {"organizations": store.organizations(user.id)}

    @router.post("/organizations", status_code=201)
    def create_organization(payload: dict[str, Any] = Body(...), user=Depends(current_user)):
        return {"organization": invoke(store.create_organization, user.id, payload.get("name"))}

    @router.get("/organizations/{organization_id}")
    def get_organization(organization_id: str, user=Depends(current_user)):
        return {"organization": invoke(store.organization, organization_id, user.id)}

    @router.get("/organizations/{organization_id}/members")
    def list_members(organization_id: str, user=Depends(current_user)):
        return {"members": invoke(store.members, organization_id, user.id)}

    @router.post("/organizations/{organization_id}/members", status_code=201)
    def add_member(organization_id: str, payload: dict[str, Any] = Body(...), user=Depends(current_user)):
        return {
            "membership": invoke(
                store.change_member,
                organization_id,
                user.id,
                payload.get("user_id"),
                payload.get("role", "member"),
                "add",
            )
        }

    @router.patch("/organizations/{organization_id}/members/{user_id}")
    def change_member(
        organization_id: str, user_id: str, payload: dict[str, Any] = Body(...), user=Depends(current_user)
    ):
        return {
            "membership": invoke(store.change_member, organization_id, user.id, user_id, payload.get("role"), "update")
        }

    @router.delete("/organizations/{organization_id}/members/{user_id}")
    def remove_member(organization_id: str, user_id: str, user=Depends(current_user)):
        return invoke(store.change_member, organization_id, user.id, user_id, action="remove")

    @router.get("/organizations/{organization_id}/audit")
    def organization_audit(organization_id: str, limit: int = Query(100, ge=1, le=500), user=Depends(current_user)):
        return {"events": invoke(store.audit_records, user.id, organization_id, limit)}

    return router
