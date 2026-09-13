"""Accounts and the preference spine.

Users sign in with an email link (or Google when a client is configured) and get a signed session
token the site keeps in an httpOnly cookie. Preferences are the product's memory: one record per
(scope, scope_key, key), resolved statement -> company -> sector -> global -> system default, and the
resolution says which scope answered so the UI can show "for this company" / "everywhere".

Two stores, mirroring the serving data: Postgres when DATABASE_URL is set, JSON documents in the lake
otherwise (users/, prefs/, auth_tokens/, pref_events/), so the free layout works with a writable lake.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from filings_hub.lake.storage import Storage

log = logging.getLogger(__name__)

SCOPES = ("global", "sector", "company", "statement", "export")
RESOLUTION = ("statement", "company", "sector", "global")  # most specific first
SOURCES = ("explicit", "inferred", "preset")
DEFAULTS: dict[str, Any] = {
    "scale": "millions",  # units | thousands | millions | billions (per-share never scaled)
    "statement": "IS",  # which statement opens first
    "periods_shown": 8,
    "negative_style": "parentheses",
    "column_order": "newest_right",
}
MAGIC_LINK_MINUTES = 15
USERS = "users"
PREFS = "prefs"
TOKENS = "auth_tokens"
EVENTS = "pref_events"


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(d: datetime) -> str:
    return d.isoformat()


@dataclass
class User:
    id: str
    email: str
    plan: str = "free"
    locale: str = ""
    timezone: str = ""
    created_at: str = field(default_factory=lambda: _iso(_now()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Pref:
    scope: str
    scope_key: str  # "" for global
    key: str
    value: Any
    source: str = "explicit"
    updated_at: str = field(default_factory=lambda: _iso(_now()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def ident(self) -> tuple[str, str, str]:
        return (self.scope, self.scope_key, self.key)


def scope_key_for(scope: str, cik: int | None, sic: str | None, statement: str | None) -> str | None:
    """The scope_key a (cik, sic, statement) context has at `scope`; None when the context lacks it."""
    if scope == "global":
        return ""
    if scope == "sector":
        return sic or None
    if scope == "company":
        return str(cik) if cik is not None else None
    if scope == "statement":
        return f"{cik}:{statement}" if cik is not None and statement else None
    return None


def resolve(
    prefs: list[Pref], cik: int | None = None, sic: str | None = None, statement: str | None = None
) -> dict[str, dict[str, Any]]:
    """{key: {value, scope, scope_key, source}} for every default and every key the user has set,
    most specific applicable scope first, system default last."""
    by_ident = {p.ident: p for p in prefs}
    keys = set(DEFAULTS) | {p.key for p in prefs}
    out: dict[str, dict[str, Any]] = {}
    for key in sorted(keys):
        chosen: dict[str, Any] | None = None
        for scope in RESOLUTION:
            sk = scope_key_for(scope, cik, sic, statement)
            if sk is None:
                continue
            p = by_ident.get((scope, sk, key))
            if p is not None:
                chosen = {"value": p.value, "scope": scope, "scope_key": sk, "source": p.source}
                break
        if chosen is None:
            if key not in DEFAULTS:
                continue  # set somewhere that does not apply here, and no default: nothing to say
            chosen = {"value": DEFAULTS[key], "scope": "default", "scope_key": "", "source": "default"}
        out[key] = chosen
    return out


# ---------------------------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------------------------
class UserStore(Protocol):
    def get_user(self, user_id: str) -> User | None: ...
    def get_user_by_email(self, email: str) -> User | None: ...
    def create_user(self, email: str) -> User: ...
    def put_token(self, token_hash: str, record: dict[str, Any]) -> None: ...
    def pop_token(self, token_hash: str) -> dict[str, Any] | None: ...
    def list_prefs(self, user_id: str) -> list[Pref]: ...
    def put_pref(self, user_id: str, pref: Pref) -> None: ...
    def delete_pref(self, user_id: str, scope: str, scope_key: str, key: str) -> bool: ...
    def delete_all_prefs(self, user_id: str) -> int: ...
    def add_event(self, user_id: str, event: dict[str, Any]) -> None: ...


def _email_key(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:24]


class LakeUserStore:
    """JSON documents in the lake. Fine for a small user base behind one API process."""

    def __init__(self, storage: Storage):
        self.storage = storage

    def _read(self, rel: str) -> dict[str, Any] | None:
        if not self.storage.exists(rel):
            return None
        return json.loads(self.storage.read_text(rel))

    def _write(self, rel: str, doc: dict[str, Any]) -> None:
        self.storage.write_text(rel, json.dumps(doc))

    def get_user(self, user_id: str) -> User | None:
        d = self._read(f"{USERS}/{user_id}.json")
        return User(**d) if d else None

    def get_user_by_email(self, email: str) -> User | None:
        d = self._read(f"{USERS}/by_email/{_email_key(email)}.json")
        return self.get_user(d["id"]) if d else None

    def create_user(self, email: str) -> User:
        user = User(id=uuid.uuid4().hex, email=email.strip().lower())
        self._write(f"{USERS}/{user.id}.json", user.to_dict())
        self._write(f"{USERS}/by_email/{_email_key(email)}.json", {"id": user.id})
        return user

    def put_token(self, token_hash: str, record: dict[str, Any]) -> None:
        self._write(f"{TOKENS}/{token_hash}.json", record)

    def pop_token(self, token_hash: str) -> dict[str, Any] | None:
        rel = f"{TOKENS}/{token_hash}.json"
        d = self._read(rel)
        if d is not None:
            self.storage.delete(rel)
        return d

    def list_prefs(self, user_id: str) -> list[Pref]:
        d = self._read(f"{PREFS}/{user_id}.json")
        return [Pref(**p) for p in (d or {}).get("prefs", [])]

    def _save_prefs(self, user_id: str, prefs: list[Pref]) -> None:
        self._write(f"{PREFS}/{user_id}.json", {"prefs": [p.to_dict() for p in prefs]})

    def put_pref(self, user_id: str, pref: Pref) -> None:
        prefs = [p for p in self.list_prefs(user_id) if p.ident != pref.ident]
        prefs.append(pref)
        self._save_prefs(user_id, prefs)

    def delete_pref(self, user_id: str, scope: str, scope_key: str, key: str) -> bool:
        prefs = self.list_prefs(user_id)
        kept = [p for p in prefs if p.ident != (scope, scope_key, key)]
        if len(kept) == len(prefs):
            return False
        self._save_prefs(user_id, kept)
        return True

    def delete_all_prefs(self, user_id: str) -> int:
        n = len(self.list_prefs(user_id))
        self._save_prefs(user_id, [])
        return n

    def add_event(self, user_id: str, event: dict[str, Any]) -> None:
        self._write(f"{EVENTS}/{user_id}/{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}.json", event)


class PostgresUserStore:
    def __init__(self, url: str):
        import psycopg

        from filings_hub.db.load import apply_migrations

        self.conn = psycopg.connect(url, autocommit=True)
        apply_migrations(self.conn)

    def _one(self, sql: str, params: tuple) -> dict[str, Any] | None:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            if row is None or cur.description is None:
                return None
            return dict(zip([d.name for d in cur.description], row, strict=True))

    def _all(self, sql: str, params: tuple) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    @staticmethod
    def _user(row: dict[str, Any] | None) -> User | None:
        if not row:
            return None
        return User(
            id=row["id"],
            email=row["email"],
            plan=row["plan"],
            locale=row["locale"] or "",
            timezone=row["timezone"] or "",
            created_at=_iso(row["created_at"]) if isinstance(row["created_at"], datetime) else str(row["created_at"]),
        )

    def get_user(self, user_id: str) -> User | None:
        return self._user(self._one("SELECT * FROM users WHERE id = %s", (user_id,)))

    def get_user_by_email(self, email: str) -> User | None:
        return self._user(self._one("SELECT * FROM users WHERE email = %s", (email.strip().lower(),)))

    def create_user(self, email: str) -> User:
        user = User(id=uuid.uuid4().hex, email=email.strip().lower())
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (id, email, plan, locale, timezone, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (user.id, user.email, user.plan, user.locale, user.timezone, datetime.fromisoformat(user.created_at)),
            )
        return user

    def put_token(self, token_hash: str, record: dict[str, Any]) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO auth_tokens (token_hash, record, expires_at) VALUES (%s, %s, %s) "
                "ON CONFLICT (token_hash) DO UPDATE SET record = EXCLUDED.record, expires_at = EXCLUDED.expires_at",
                (token_hash, json.dumps(record), datetime.fromisoformat(record["expires_at"])),
            )

    def pop_token(self, token_hash: str) -> dict[str, Any] | None:
        row = self._one("DELETE FROM auth_tokens WHERE token_hash = %s RETURNING record", (token_hash,))
        if not row:
            return None
        rec = row["record"]
        return rec if isinstance(rec, dict) else json.loads(rec)

    def list_prefs(self, user_id: str) -> list[Pref]:
        rows = self._all(
            "SELECT scope, scope_key, key, value, source, updated_at FROM user_prefs WHERE user_id = %s", (user_id,)
        )
        out = []
        for r in rows:
            v = r["value"]
            out.append(
                Pref(
                    scope=r["scope"],
                    scope_key=r["scope_key"],
                    key=r["key"],
                    value=v if not isinstance(v, str) else json.loads(v),
                    source=r["source"],
                    updated_at=_iso(r["updated_at"]) if isinstance(r["updated_at"], datetime) else str(r["updated_at"]),
                )
            )
        return out

    def put_pref(self, user_id: str, pref: Pref) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO user_prefs (user_id, scope, scope_key, key, value, source, updated_at) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s) "
                "ON CONFLICT (user_id, scope, scope_key, key) DO UPDATE SET value = EXCLUDED.value, "
                "source = EXCLUDED.source, updated_at = EXCLUDED.updated_at",
                (
                    user_id,
                    pref.scope,
                    pref.scope_key,
                    pref.key,
                    json.dumps(pref.value),
                    pref.source,
                    datetime.fromisoformat(pref.updated_at),
                ),
            )

    def delete_pref(self, user_id: str, scope: str, scope_key: str, key: str) -> bool:
        with self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_prefs WHERE user_id = %s AND scope = %s AND scope_key = %s AND key = %s",
                (user_id, scope, scope_key, key),
            )
            return cur.rowcount > 0

    def delete_all_prefs(self, user_id: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM user_prefs WHERE user_id = %s", (user_id,))
            return cur.rowcount

    def add_event(self, user_id: str, event: dict[str, Any]) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pref_events (user_id, key, scope, old, new, source, at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    user_id,
                    event.get("key"),
                    event.get("scope"),
                    json.dumps(event.get("old")),
                    json.dumps(event.get("new")),
                    event.get("source"),
                    datetime.fromisoformat(event["at"]),
                ),
            )


def store_from_settings(storage: Storage, database_url: str) -> UserStore:
    if database_url.startswith(("postgresql://", "postgres://")):
        return PostgresUserStore(database_url)
    return LakeUserStore(storage)


# ---------------------------------------------------------------------------------------------
# Sessions and sign-in tokens
# ---------------------------------------------------------------------------------------------
class SessionSigner:
    """Stateless session tokens: v1.<user_id>.<expires>.<nonce>.<hmac>. Nothing to store or look up."""

    def __init__(self, secret: str, days: int = 30):
        if not secret:
            secret = secrets.token_urlsafe(32)
            log.warning("SESSION_SECRET is empty: sessions will not survive a restart")
        self.key = secret.encode()
        self.days = days

    def _sig(self, body: str) -> str:
        return hmac.new(self.key, body.encode(), hashlib.sha256).hexdigest()[:40]

    def sign(self, user_id: str, now: float | None = None) -> str:
        exp = int((now or time.time()) + self.days * 86400)
        body = f"v1.{user_id}.{exp}.{secrets.token_hex(6)}"  # nonce: every sign-in is its own token
        return f"{body}.{self._sig(body)}"

    def verify(self, token: str | None, now: float | None = None) -> str | None:
        if not token:
            return None
        parts = token.split(".")
        if len(parts) != 5 or parts[0] != "v1":
            return None
        _, user_id, exp, nonce, sig = parts
        body = f"v1.{user_id}.{exp}.{nonce}"
        if not hmac.compare_digest(sig, self._sig(body)):
            return None
        if not exp.isdigit() or int(exp) < (now or time.time()):
            return None
        return user_id


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_magic_link(store: UserStore, email: str, site_url: str) -> tuple[str, str]:
    """(token, link). The store keeps only the hash; the link carries the token once."""
    token = secrets.token_urlsafe(32)
    store.put_token(
        token_hash(token),
        {
            "purpose": "magic",
            "email": email.strip().lower(),
            "expires_at": _iso(_now() + timedelta(minutes=MAGIC_LINK_MINUTES)),
        },
    )
    base = site_url.rstrip("/") if site_url else ""
    return token, f"{base}/auth/callback?token={token}"


def redeem_magic_link(store: UserStore, token: str) -> User | None:
    rec = store.pop_token(token_hash(token))
    if not rec or rec.get("purpose") != "magic":
        return None
    if datetime.fromisoformat(rec["expires_at"]) < _now():
        return None
    return get_or_create_user(store, rec["email"])


def get_or_create_user(store: UserStore, email: str) -> User:
    return store.get_user_by_email(email) or store.create_user(email)


def google_email_for_code(code: str, redirect_uri: str, client_id: str, client_secret: str, http=None) -> str | None:
    """Exchange an OAuth code for the account's verified email. `http` is an httpx.Client (injectable)."""
    import httpx

    client = http or httpx.Client(timeout=15)
    try:
        tok = client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if tok.status_code != 200:
            log.warning("google token exchange failed: %s %s", tok.status_code, tok.text[:200])
            return None
        access = tok.json().get("access_token")
        info = client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo", headers={"Authorization": f"Bearer {access}"}
        )
        if info.status_code != 200:
            return None
        data = info.json()
        if not data.get("email") or not data.get("email_verified", False):
            return None
        return str(data["email"]).lower()
    finally:
        if http is None:
            client.close()


def validate_pref(scope: str, scope_key: str, key: str, value: Any, source: str) -> str | None:
    """A human-readable problem, or None when the preference is well-formed."""
    if scope not in SCOPES:
        return f"scope must be one of {', '.join(SCOPES)}"
    if scope == "global" and scope_key:
        return "a global preference has no scope_key"
    if scope != "global" and not scope_key:
        return f"a {scope} preference needs a scope_key"
    if not key or len(key) > 80 or not all(c.isalnum() or c in "._-" for c in key):
        return "key must be 1-80 characters of letters, digits, dots, dashes, underscores"
    if source not in SOURCES:
        return f"source must be one of {', '.join(SOURCES)}"
    if len(json.dumps(value)) > 20_000:
        return "value too large"
    return None


__all__ = [
    "DEFAULTS",
    "RESOLUTION",
    "SCOPES",
    "LakeUserStore",
    "PostgresUserStore",
    "Pref",
    "SessionSigner",
    "User",
    "get_or_create_user",
    "google_email_for_code",
    "issue_magic_link",
    "redeem_magic_link",
    "resolve",
    "scope_key_for",
    "store_from_settings",
    "validate_pref",
]
