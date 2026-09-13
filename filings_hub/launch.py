"""Verified individual launch reservations and reviewed demo enquiries.

One campaign transaction serializes allocations across Postgres processes. The existing lake
adapter supports a single API process only; production allocations require Postgres. Regional
preferences never partition the twenty places or assert data residency.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from filings_hub.admin_operations import page, pagination
from filings_hub.platform_admin import AdminStore
from filings_hub.projects import revision_matches
from filings_hub.tenancy import SecurityError, SecurityStore, stamp

CAMPAIGN_ID = "founding-members-2026"
CAPACITY = 20
STARTS = datetime(2026, 11, 1, tzinfo=UTC)
ENDS = datetime(2027, 5, 1, tzinfo=UTC)
REGIONS = Literal["US", "UK", "EU", "AU", "ROW"]
DEMO_STATUSES = frozenset({"new", "contacted", "scheduled", "completed"})
AI_ALLOWANCE = "Optional AI is subject to configured availability and usage limits; unlimited AI is not included."


class ReservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region: REGIONS
    accept_terms: StrictBool


class DemoInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    organisation: str = Field(default="", max_length=160)
    region: REGIONS
    workflow: str = Field(min_length=10, max_length=3000)

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value):
        return value.lower()

    @field_validator("name", "organisation", "email", "workflow")
    @classmethod
    def printable_text(cls, value):
        if any(ord(char) < 32 and char not in "\n\t" for char in value):
            raise ValueError("Control characters are not accepted.")
        return value


class LaunchStore:
    def __init__(self, security: SecurityStore, *, identity_secret: str = "", clock=time.time):
        self.security, self.identity_secret, self.clock = security, identity_secret, clock

    @staticmethod
    def _counts(tx) -> tuple[int, int]:
        if hasattr(tx, "conn"):
            row = tx.conn.execute(
                "SELECT count(*) FILTER (WHERE status = 'reserved'), count(*) "
                "FROM launch_memberships WHERE campaign_id = %s",
                (CAMPAIGN_ID,),
            ).fetchone()
            return int(row[0]), int(row[1])
        rows = tx.find("launch_memberships", campaign_id=CAMPAIGN_ID)
        return sum(row["status"] == "reserved" for row in rows), len(rows)

    def _campaign(self, tx) -> dict:
        allocated, _ = self._counts(tx)
        return {
            "id": CAMPAIGN_ID,
            "opens_at": STARTS.isoformat(),
            "registration_closes_at": STARTS.isoformat(),
            "benefit_starts_at": STARTS.isoformat(),
            "benefit_ends_at": ENDS.isoformat(),
            "capacity": CAPACITY,
            "allocated": allocated,
            "remaining": max(0, CAPACITY - allocated),
            "state": "closed" if self.clock() >= STARTS.timestamp() else "full" if allocated >= CAPACITY else "open",
            "individual_accounts": True,
            "auto_charge": False,
            "ai_allowance": AI_ALLOWANCE,
        }

    def campaign(self) -> dict:
        with self.security.transaction() as tx:
            return {"campaign": self._campaign(tx)}

    def _membership_response(self, tx, actor: str) -> dict:
        entry = tx.get("launch_memberships", f"{CAMPAIGN_ID}:{actor}")
        reserved = bool(entry and entry["status"] == "reserved")
        now = self.clock()
        active = reserved and STARTS.timestamp() <= now < ENDS.timestamp()
        return {
            "campaign": self._campaign(tx),
            "membership": {
                key: entry[key]
                for key in ("status", "position", "region", "joined_at", "benefit_starts_at", "benefit_ends_at")
            }
            if entry
            else None,
            "entitlement": {
                "active": active,
                "phase": "none"
                if not reserved
                else "upcoming"
                if now < STARTS.timestamp()
                else "active"
                if active
                else "expired",
                "plan": "launch" if active else None,
                "starts_at": STARTS.isoformat() if reserved else None,
                "ends_at": ENDS.isoformat() if reserved else None,
            },
        }

    def membership(self, actor: str) -> dict:
        with self.security.transaction() as tx:
            return self._membership_response(tx, actor)

    def reserve(self, actor: str, payload: ReservationInput) -> dict:
        if not payload.accept_terms:
            raise SecurityError(422, "Accept the founding-member terms before reserving an individual place.")
        with self.security.transaction("launch:" + CAMPAIGN_ID) as tx:
            if not self.security.users.get_user(actor):
                raise SecurityError(401, "Sign in with a verified account before joining early access.")
            if (tx.get("platform_controls", actor) or {}).get("status") == "suspended":
                raise SecurityError(403, "This account is suspended; contact support.")
            ident = f"{CAMPAIGN_ID}:{actor}"
            # Retries, another device and a different selected region retain the original place.
            if tx.get("launch_memberships", ident):
                return self._membership_response(tx, actor)
            if self.clock() >= STARTS.timestamp():
                raise SecurityError(409, "Founding-member registration closed on 1 November 2026.")
            allocated, joined = self._counts(tx)
            status = "reserved" if allocated < CAPACITY else "waitlisted"
            entry = {
                "id": ident,
                "campaign_id": CAMPAIGN_ID,
                "user_id": actor,
                "status": status,
                "position": joined + 1,
                "region": payload.region,
                "joined_at": stamp(self.clock()),
                "terms_version": "founding-members-2026-v1",
                "terms_accepted_at": stamp(self.clock()),
                "benefit_starts_at": STARTS.isoformat() if status == "reserved" else None,
                "benefit_ends_at": ENDS.isoformat() if status == "reserved" else None,
            }
            tx.put("launch_memberships", entry)
            self.security.audit(tx, actor, "launch." + status, ident, campaign_id=CAMPAIGN_ID)
            return self._membership_response(tx, actor)

    def submit_demo(self, payload: DemoInput, identity: str) -> dict:
        values = payload.model_dump(mode="json", exclude={"request_id"})
        content_hash = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
        caller_hash = hmac.new(self.identity_secret.encode(), identity.encode(), hashlib.sha256).hexdigest()
        ident = str(payload.request_id)
        with self.security.transaction("launch:demo-intake") as tx:
            previous = tx.get("demo_requests", ident)
            if previous:
                if previous["content_hash"] != content_hash:
                    raise SecurityError(409, "This request reference was already used. Start a new request.")
                return {"received": True, "reference": ident}
            cutoff = stamp(self.clock() - 3600)
            # These durable limits apply across workers, devices and service restarts. No IP address
            # or visitor identifier is retained in enquiry records, only its keyed fingerprint.
            if hasattr(tx, "conn"):
                counts = tx.conn.execute(
                    "SELECT count(*) FILTER (WHERE email = %s), count(*) FILTER (WHERE caller_hash = %s) "
                    "FROM demo_requests WHERE created_at > %s AND (email = %s OR caller_hash = %s)",
                    (values["email"], caller_hash, cutoff, values["email"], caller_hash),
                ).fetchone()
            else:
                rows = [r for r in tx.find("demo_requests") if r["created_at"] > cutoff]
                counts = (
                    sum(r["email"] == values["email"] for r in rows),
                    sum(r["caller_hash"] == caller_hash for r in rows),
                )
            if counts[0] >= 3 or counts[1] >= 5:
                raise HTTPException(
                    429, "Please wait before sending another demo request.", headers={"Retry-After": "3600"}
                )
            now = stamp(self.clock())
            tx.put(
                "demo_requests",
                {
                    "id": ident,
                    **values,
                    "status": "new",
                    "revision": 1,
                    "created_at": now,
                    "updated_at": now,
                    "content_hash": content_hash,
                    "caller_hash": caller_hash,
                },
            )
            return {"received": True, "reference": ident}

    @staticmethod
    def public_lead(row: dict) -> dict:
        return {key: value for key, value in row.items() if key not in {"content_hash", "caller_hash"}}

    def launch_memberships(self, admin: AdminStore, token: str, q="", status="", limit=25, offset=0) -> dict:
        pagination(q, limit, offset)
        if status and status not in {"reserved", "waitlisted"}:
            raise SecurityError(422, "Status must be reserved or waitlisted.")

        def item(row: dict, email: str, first_name: str, last_name: str) -> dict:
            return {
                **{
                    key: row[key]
                    for key in (
                        "id",
                        "user_id",
                        "position",
                        "region",
                        "status",
                        "joined_at",
                        "benefit_starts_at",
                        "benefit_ends_at",
                    )
                },
                "email": email,
                "name": " ".join(part for part in (first_name, last_name) if part),
            }

        with admin.transaction() as tx:
            admin.authorize(tx, token)
            campaign = self._campaign(tx)
            if hasattr(tx, "conn"):
                pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                clause = (
                    "m.campaign_id = %s AND (%s = '' OR m.status = %s) AND "
                    "lower(u.email || ' ' || coalesce(u.first_name,'') || ' ' || coalesce(u.last_name,'') "
                    "|| ' ' || m.user_id) LIKE lower(%s)"
                )
                params = (CAMPAIGN_ID, status, status, pattern)
                source = "launch_memberships m JOIN users u ON u.id = m.user_id"
                total = tx.conn.execute(f"SELECT count(*) FROM {source} WHERE {clause}", params).fetchone()[0]
                rows = tx.conn.execute(
                    f"SELECT m.record,u.email,u.first_name,u.last_name FROM {source} WHERE {clause} "
                    "ORDER BY m.position LIMIT %s OFFSET %s",
                    (*params, limit, offset),
                ).fetchall()
                return {
                    "campaign": campaign,
                    "items": [item(*row) for row in rows],
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }
            rows = []
            for row in tx.find("launch_memberships", campaign_id=CAMPAIGN_ID):
                if status and row["status"] != status:
                    continue
                user = self.security.users.get_user(row["user_id"])
                if user:
                    rows.append(item(row, user.email, user.first_name, user.last_name))
            rows.sort(key=lambda row: row["position"])
            return {"campaign": campaign, **page(rows, q, limit, offset, ("email", "name", "user_id"))}

    def demo_requests(self, admin: AdminStore, token: str, q="", status="", limit=25, offset=0) -> dict:
        pagination(q, limit, offset)
        if status and status not in DEMO_STATUSES:
            raise SecurityError(422, "Unknown demo request status.")
        with admin.transaction() as tx:
            admin.authorize(tx, token)
            if hasattr(tx, "conn"):
                pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                clause = (
                    "(%s = '' OR status = %s) AND lower(record->>'name' || ' ' || email || ' ' || "
                    "coalesce(record->>'organisation','') || ' ' || id) LIKE lower(%s)"
                )
                params = (status, status, pattern)
                total = tx.conn.execute(f"SELECT count(*) FROM demo_requests WHERE {clause}", params).fetchone()[0]
                rows = tx.conn.execute(
                    f"SELECT record FROM demo_requests WHERE {clause} ORDER BY created_at DESC,id LIMIT %s OFFSET %s",
                    (*params, limit, offset),
                ).fetchall()
                return {
                    "items": [self.public_lead(row[0]) for row in rows],
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }
            rows = sorted(
                (self.public_lead(row) for row in tx.find("demo_requests") if not status or row["status"] == status),
                key=lambda row: (row["created_at"], row["id"]),
                reverse=True,
            )
            return page(rows, q, limit, offset, ("name", "email", "organisation", "id"))

    def demo_status(self, admin: AdminStore, token: str, ident: str, payload: dict[str, Any]) -> dict:
        reason = admin.review(payload, "demo.status", ident)
        status = payload.get("status")
        if not isinstance(status, str) or status not in DEMO_STATUSES:
            raise SecurityError(422, "Status must be new, contacted, scheduled or completed.")
        if set(payload) - {"status", "expected_revision", "reason", "confirmation"}:
            raise SecurityError(422, "Only the request status can be changed here.")
        with admin.transaction() as tx:
            actor, _ = admin.authorize(tx, token, fresh=True)
            previous = tx.get("demo_requests", ident)
            if not previous:
                raise SecurityError(404, "Demo request not found.")
            revision_matches(previous, payload.get("expected_revision"))
            updated = {
                **previous,
                "status": status,
                "revision": previous["revision"] + 1,
                "updated_at": stamp(self.clock()),
            }
            tx.put("demo_requests", updated)
            admin.audit(
                tx,
                actor["id"],
                "demo.status",
                ident,
                reason=reason,
                previous_status=previous["status"],
                status=status,
                revision=updated["revision"],
            )
            return {"request": self.public_lead(updated)}


def launch_router(store: LaunchStore, auth, current_user) -> APIRouter:
    router = APIRouter()

    def no_cache(response: Response):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Pragma"] = "no-cache"

    @router.get("/launch/campaign", dependencies=[Depends(auth), Depends(no_cache)])
    def campaign():
        return store.campaign()

    @router.get("/me/early-access", dependencies=[Depends(no_cache)])
    def membership(user=Depends(current_user)):
        return store.membership(user.id)

    @router.post("/me/early-access", dependencies=[Depends(no_cache)])
    def reserve(payload: ReservationInput, user=Depends(current_user)):
        return store.reserve(user.id, payload)

    @router.post("/demo-requests", status_code=201, dependencies=[Depends(no_cache)])
    def demo(payload: DemoInput, identity: str = Depends(auth)):
        return store.submit_demo(payload, identity)

    return router
