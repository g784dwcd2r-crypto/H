"""Separate, explicitly bootstrapped platform operators and auditable management controls."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import secrets
import time
import uuid
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlsplit

from filings_hub import accounts
from filings_hub.config import Settings
from filings_hub.projects import revision_matches
from filings_hub.tenancy import ROLES, SecurityError, SecurityStore, stamp

ADMIN_ID = "disclosure"
SCRYPT_N = 2**17
LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def strong_password(value: Any) -> str:
    if not isinstance(value, str) or not 16 <= len(value) <= 256 or len(set(value.casefold())) < 8:
        raise SecurityError(
            422, "Use a unique password or passphrase of 16–256 characters with at least 8 distinct characters."
        )
    if value.casefold() in {"disclosure123456789", "password123456789!", "1234567890abcdef"}:
        raise SecurityError(422, "Choose a less predictable password.")
    return value


def password_hash(value: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(value.encode(), salt=salt, n=SCRYPT_N, r=8, p=1, maxmem=256 * 1024 * 1024)
    return f"scrypt-v1${salt.hex()}${derived.hex()}"


def password_matches(value: Any, encoded: str) -> bool:
    if not isinstance(value, str) or len(value) > 256:
        return False
    try:
        scheme, salt, expected = encoded.split("$")
        if scheme != "scrypt-v1":
            return False
        derived = hashlib.scrypt(
            value.encode(), salt=bytes.fromhex(salt), n=SCRYPT_N, r=8, p=1, maxmem=256 * 1024 * 1024
        )
        return hmac.compare_digest(derived.hex(), expected)
    except (ValueError, TypeError):
        return False


def fingerprint(row: dict | None) -> str:
    return (
        hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest() if row else "absent"
    )


def csrf_for(token: str) -> str:
    return hmac.new(token.encode(), b"disclosure-platform-admin-csrf-v1", hashlib.sha256).hexdigest()


def validate_configuration(settings: Settings) -> None:
    if not settings.platform_admin_enabled:
        if settings.platform_admin_local_bootstrap:
            raise ValueError("Local admin bootstrap requires PLATFORM_ADMIN_ENABLED.")
        return
    origin = urlsplit(settings.platform_admin_origin)
    if (
        origin.scheme not in {"http", "https"}
        or not origin.hostname
        or origin.path
        or origin.query
        or origin.fragment
        or origin.username
    ):
        raise ValueError("PLATFORM_ADMIN_ORIGIN must be an exact web origin without a path or credentials.")
    if settings.platform_admin_environment == "development":
        if origin.hostname not in LOOPBACK:
            raise ValueError("Development admin configuration must use a loopback web origin.")
    elif settings.platform_admin_local_bootstrap or origin.scheme != "https" or origin.hostname in LOOPBACK:
        raise ValueError("Production admin requires HTTPS and rejects local/default bootstrap configuration.")
    elif len(settings.api_key) < 32 or not settings.database_url.startswith(("postgres://", "postgresql://")):
        raise ValueError("Production admin requires Postgres and a service API key of at least 32 characters.")


class AdminStore:
    def __init__(self, security: SecurityStore, settings: Settings, clock=time.time):
        validate_configuration(settings)
        self.security, self.settings, self.clock = security, settings, clock

    @contextmanager
    def transaction(self, scope: str | None = None):
        with self.security.transaction("platform-admin") as tx:
            if scope and self.security.database_url:
                tx.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("security:" + scope,))
            yield tx

    def audit(self, tx, actor: str, action: str, target: str, **metadata):
        tx.put(
            "platform_admin_audit",
            {
                "id": uuid.uuid4().hex,
                "actor_id": actor,
                "action": action,
                "target_id": target,
                "at": stamp(self.clock()),
                "metadata": metadata,
            },
        )

    def bootstrap(self, username: str, password: str, *, local: bool = False, recover: bool = False):
        if not self.settings.platform_admin_enabled or username != ADMIN_ID:
            raise SecurityError(422, "Enable the admin service explicitly and use the dedicated disclosure username.")
        if local:
            db_host = urlsplit(self.security.database_url).hostname
            if (
                not self.settings.platform_admin_local_bootstrap
                or self.settings.platform_admin_environment != "development"
                or self.security.storage.is_remote
                or (db_host and db_host not in LOOPBACK)
            ):
                raise SecurityError(
                    403, "Local bootstrap requires explicit development mode, loopback origin and local stores."
                )
            if password != "1234":
                strong_password(password)
        else:
            strong_password(password)
        encoded = password_hash(password)
        with self.transaction() as tx:
            previous = tx.get("platform_admins", ADMIN_ID)
            if previous and not recover:
                raise SecurityError(409, "The operator already exists; use the explicit recovery command.")
            if recover and not previous:
                raise SecurityError(404, "No operator exists to recover.")
            record = {
                "id": ADMIN_ID,
                "password_hash": encoded,
                "must_change_password": True,
                "local_bootstrap": local,
                "created_at": previous["created_at"] if previous else stamp(self.clock()),
                "updated_at": stamp(self.clock()),
                "failed_attempts": 0,
                "locked_until": 0,
            }
            tx.put("platform_admins", record)
            self._revoke_admin_sessions(tx)
            self.audit(
                tx,
                "local-operator",
                "admin.recovered" if recover else "admin.bootstrapped",
                ADMIN_ID,
                local_bootstrap=local,
            )

    def _revoke_admin_sessions(self, tx):
        for session in tx.find("platform_admin_sessions", admin_id=ADMIN_ID):
            if not session.get("revoked_at"):
                tx.put("platform_admin_sessions", {**session, "revoked_at": stamp(self.clock())})

    def _issue(self, tx, admin: dict, *, reauthenticated: bool = False) -> dict:
        token = uuid.uuid4().hex + "." + secrets.token_urlsafe(48)
        issued = self.clock()
        session = {
            "id": token.split(".")[0],
            "admin_id": admin["id"],
            "token_hash": accounts.token_hash(token),
            "created_at": stamp(issued),
            "expires_at": stamp(issued + self.settings.platform_admin_session_minutes * 60),
            "reauthenticated_at": issued if reauthenticated else 0,
        }
        tx.put("platform_admin_sessions", session)
        return {
            "token": token,
            "csrf": csrf_for(token),
            "username": admin["id"],
            "must_change_password": admin["must_change_password"],
            "expires_at": session["expires_at"],
            "mfa": "not_configured",
        }

    def _check_password(self, tx, admin: dict, password: Any) -> SecurityError | None:
        if admin.get("locked_until", 0) > self.clock():
            return SecurityError(429, "Administrator authentication is temporarily locked. Try again later.")
        if not password_matches(password, admin["password_hash"]):
            failures = admin.get("failed_attempts", 0) + 1
            until = self.clock() + min(900, 60 * 2 ** min(4, failures - 5)) if failures >= 5 else 0
            tx.put("platform_admins", {**admin, "failed_attempts": failures, "locked_until": until})
            self.audit(tx, "anonymous", "admin.authentication_failed", ADMIN_ID)
            return SecurityError(401, "Invalid administrator credentials.")
        tx.put("platform_admins", {**admin, "failed_attempts": 0, "locked_until": 0})
        return None

    def login(self, username: Any, password: Any, *, peer: str) -> dict:
        error, result = None, None
        with self.transaction() as tx:
            admin = tx.get("platform_admins", ADMIN_ID)
            if not admin:
                raise SecurityError(401, "Invalid administrator credentials.")
            if admin["local_bootstrap"] and (
                self.settings.platform_admin_environment != "development"
                or not self.settings.platform_admin_local_bootstrap
                or peer not in LOOPBACK
            ):
                raise SecurityError(403, "This local bootstrap cannot authenticate on this deployment.")
            # Invalid usernames spend the same password work and share the durable operator lockout.
            error = self._check_password(tx, admin, password if username == ADMIN_ID else "")
            if error is None:
                result = self._issue(tx, admin)
                self.audit(tx, ADMIN_ID, "admin.signed_in", ADMIN_ID)
        if error:
            raise error
        return result

    def authorize(self, tx, token: str | None, *, allow_change: bool = False, fresh: bool = False) -> tuple[dict, dict]:
        if not isinstance(token, str) or len(token) > 200 or token.count(".") != 1:
            raise SecurityError(401, "Platform administrator sign-in required.")
        session = tx.get("platform_admin_sessions", token.split(".")[0])
        if not self.security.active(session, self.clock()) or not hmac.compare_digest(
            session["token_hash"], accounts.token_hash(token)
        ):
            raise SecurityError(401, "Platform administrator session expired or revoked.")
        admin = tx.get("platform_admins", session["admin_id"])
        if not admin or (admin["local_bootstrap"] and self.settings.platform_admin_environment != "development"):
            raise SecurityError(401, "Administrator credentials must be recovered for this deployment.")
        if admin["must_change_password"] and not allow_change:
            raise SecurityError(403, "Change the initial administrator password before opening platform management.")
        if fresh and (not session["reauthenticated_at"] or self.clock() - session["reauthenticated_at"] > 300):
            raise SecurityError(403, "Reauthenticate before this privileged change (valid for five minutes).")
        return admin, session

    def me(self, token: str) -> dict:
        with self.transaction() as tx:
            admin, session = self.authorize(tx, token, allow_change=True)
            return {
                "username": admin["id"],
                "must_change_password": admin["must_change_password"],
                "expires_at": session["expires_at"],
                "csrf": csrf_for(token),
                "mfa": "not_configured",
            }

    def password(self, token: str, current: Any, replacement: Any = None) -> dict:
        if replacement is not None:
            strong_password(replacement)
            if replacement == current:
                raise SecurityError(422, "Choose a different replacement password.")
        error, result = None, None
        with self.transaction() as tx:
            admin, session = self.authorize(tx, token, allow_change=replacement is not None)
            error = self._check_password(tx, admin, current)
            if error is None:
                if replacement is not None:
                    admin = {
                        **admin,
                        "password_hash": password_hash(replacement),
                        "must_change_password": False,
                        "local_bootstrap": False,
                        "updated_at": stamp(self.clock()),
                        "failed_attempts": 0,
                        "locked_until": 0,
                    }
                    tx.put("platform_admins", admin)
                    self._revoke_admin_sessions(tx)
                else:
                    tx.put("platform_admin_sessions", {**session, "revoked_at": stamp(self.clock())})
                result = self._issue(tx, admin, reauthenticated=True)
                self.audit(
                    tx,
                    ADMIN_ID,
                    "admin.password_changed" if replacement is not None else "admin.reauthenticated",
                    ADMIN_ID,
                )
        if error:
            raise error
        return result

    def logout(self, token: str):
        with self.transaction() as tx:
            admin, session = self.authorize(tx, token, allow_change=True)
            tx.put("platform_admin_sessions", {**session, "revoked_at": stamp(self.clock())})
            self.audit(tx, admin["id"], "admin.signed_out", session["id"])
        return {"revoked": True}

    @staticmethod
    def review(payload: dict, action: str, target: str):
        reason = payload.get("reason")
        if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 500:
            raise SecurityError(422, "Provide an operational reason of 8–500 characters.")
        if payload.get("confirmation") != f"{action}:{target}":
            raise SecurityError(422, "Review the exact action and target before confirming.")
        return reason.strip()

    @staticmethod
    def control(tx, uid: str) -> dict:
        return tx.get("platform_controls", uid) or {"id": uid, "status": "active", "revision": 1}

    def user_action(self, token: str, uid: str, payload: dict, *, revoke: bool = False) -> dict:
        action = "sessions.revoke" if revoke else "account.status"
        reason = self.review(payload, action, uid)
        if not revoke and payload.get("status") not in {"active", "suspended"}:
            raise SecurityError(422, "status must be active or suspended")
        with self.transaction("user:" + uid) as tx:
            admin, _ = self.authorize(tx, token, fresh=True)
            if not self.security.users.get_user(uid):
                raise SecurityError(404, "Account not found.")
            control = self.control(tx, uid)
            revision_matches(control, payload.get("expected_revision"))
            status = control["status"] if revoke else payload["status"]
            updated = {
                **control,
                "status": status,
                "revision": control["revision"] + 1,
                "updated_at": stamp(self.clock()),
            }
            tx.put("platform_controls", updated)
            revoked = 0
            if revoke or status == "suspended":
                for session in tx.find("sessions", user_id=uid):
                    if self.security.active(session, self.clock()):
                        tx.put("sessions", {**session, "revoked_at": stamp(self.clock())})
                        revoked += 1
            self.audit(
                tx,
                admin["id"],
                action,
                uid,
                reason=reason,
                previous_status=control["status"],
                status=status,
                sessions_revoked=revoked,
                revision=updated["revision"],
            )
            return {"control": updated, "sessions_revoked": revoked}

    def member_action(self, token: str, org: str, uid: str, payload: dict) -> dict:
        reason = self.review(payload, "membership.change", f"{org}:{uid}")
        role = payload.get("role")
        if role is not None and role not in ROLES:
            raise SecurityError(422, "role must be owner, admin, member or null to remove")
        with self.transaction("org:" + org) as tx:
            admin, _ = self.authorize(tx, token, fresh=True)
            if not tx.get("organizations", org) or not self.security.users.get_user(uid):
                raise SecurityError(404, "Organization or account not found.")
            ident = self.security.membership_id(org, uid)
            previous = tx.get("memberships", ident)
            if payload.get("expected_version") != fingerprint(previous):
                raise SecurityError(409, "Membership changed; reload and review it again.")
            if (
                previous
                and previous["role"] == "owner"
                and role != "owner"
                and len(tx.find("memberships", organization_id=org, role="owner")) <= 1
            ):
                raise SecurityError(409, "An organization must retain at least one owner.")
            if role is None:
                if not previous:
                    raise SecurityError(404, "Membership not found.")
                tx.delete("memberships", ident)
                updated = None
            else:
                updated = {
                    "id": ident,
                    "organization_id": org,
                    "user_id": uid,
                    "role": role,
                    "created_at": previous["created_at"] if previous else stamp(self.clock()),
                    "updated_at": stamp(self.clock()),
                }
                tx.put("memberships", updated)
            self.audit(
                tx,
                admin["id"],
                "membership.change",
                ident,
                reason=reason,
                previous_role=previous["role"] if previous else None,
                role=role,
            )
            return {"membership": updated, "version": fingerprint(updated)}

    def configuration(self, tx=None) -> dict:
        if tx is None:
            with self.security.transaction() as tx:
                return self.configuration(tx)
        return tx.get("platform_settings", "registration") or {
            "id": "registration",
            "revision": 1,
            "new_registration_enabled": True,
            "business_email_only": self.settings.signup_business_email_only,
        }

    def configure(self, token: str, payload: dict) -> dict:
        reason = self.review(payload, "configuration.change", "registration")
        values = {key: payload[key] for key in ("new_registration_enabled", "business_email_only") if key in payload}
        if not values or not all(type(value) is bool for value in values.values()):
            raise SecurityError(422, "Supply boolean registration controls.")
        if set(payload) - {"reason", "confirmation", "expected_revision", *values}:
            raise SecurityError(422, "Only documented registration controls can be changed here.")
        with self.transaction() as tx:
            admin, _ = self.authorize(tx, token, fresh=True)
            previous = self.configuration(tx)
            revision_matches(previous, payload.get("expected_revision"))
            updated = {**previous, **values, "revision": previous["revision"] + 1, "updated_at": stamp(self.clock())}
            tx.put("platform_settings", updated)
            self.audit(
                tx,
                admin["id"],
                "configuration.change",
                "registration",
                reason=reason,
                previous={key: previous[key] for key in values},
                values=values,
                revision=updated["revision"],
            )
            return updated

    def registration_policy(self, email: str):
        if self.security.users.get_user_by_email(email):
            return
        policy = self.configuration()
        if not policy["new_registration_enabled"]:
            raise SecurityError(403, "New account registration is paused. Existing accounts can still sign in.")
        if policy["business_email_only"] and not accounts.is_business_email(email):
            raise SecurityError(422, "A business email address is required for new accounts.")


def main():
    parser = argparse.ArgumentParser(
        description="Explicit operator bootstrap/recovery; passwords are entered privately."
    )
    parser.add_argument("command", choices=["bootstrap", "recover"])
    parser.add_argument("--username", default=ADMIN_ID)
    parser.add_argument("--local-bootstrap", action="store_true")
    args = parser.parse_args()
    from filings_hub.config import get_settings
    from filings_hub.lake.storage import Storage

    settings = get_settings()
    storage = Storage(settings.resolved_lake_root())
    users = accounts.store_from_settings(storage, settings.database_url)
    store = AdminStore(SecurityStore(users, storage, settings.database_url), settings)
    password = getpass.getpass("Initial administrator password: ")
    if password != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords did not match.")
    store.bootstrap(args.username, password, local=args.local_bootstrap, recover=args.command == "recover")
    print("Administrator stored. Sign in at /admin and change the initial password before management access.")


if __name__ == "__main__":
    main()
