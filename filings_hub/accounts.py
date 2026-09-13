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
import threading
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
    "period_mode": "as_filed",  # as_filed | quarterly | annual | ltm
    "restated": False,  # comparatives from the latest filing that presents the period
    "headline_cards": ["revenue", "net_income", "eps_diluted", "operating_cash_flow"],
    "export_config": {},  # the last export dialog settings (an ExportOptions dict plus grid params)
}
# keys whose repeated company-level choice can be proposed as the global one
PROPOSABLE = ("period_mode", "scale", "column_order", "restated", "periods_shown", "negative_style", "export_config")
PROPOSAL_STRIKES = 3  # the same choice on this many companies
PROPOSAL_DISMISSALS = 2  # dismissed this often: never again
DISMISSED_KEY = "proposals_dismissed"
MAGIC_LINK_MINUTES = 15
USERS = "users"
PREFS = "prefs"
TOKENS = "auth_tokens"
EVENTS = "pref_events"
WATCHLIST_LIMIT = 200
# One lock per lake in this API process, shared by store instances. A remote lake still requires one
# API writer process; use Postgres when account writes span processes or hosts.
_LAKE_LOCKS: dict[str, Any] = {}
_LAKE_LOCKS_GUARD = threading.Lock()


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(d: datetime) -> str:
    return d.isoformat()


PROFILE_FIELDS = ("first_name", "last_name", "company", "phone", "role", "specialty", "title", "country")
FREE_MAIL_DOMAINS = frozenset(
    [
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "yahoo.co.uk",
        "ymail.com",
        "hotmail.com",
        "hotmail.co.uk",
        "outlook.com",
        "live.com",
        "msn.com",
        "aol.com",
        "icloud.com",
        "me.com",
        "mac.com",
        "proton.me",
        "protonmail.com",
        "pm.me",
        "gmx.com",
        "gmx.de",
        "mail.com",
        "zoho.com",
        "yandex.com",
        "yandex.ru",
        "qq.com",
        "163.com",
        "126.com",
        "fastmail.com",
        "hey.com",
    ]
)


def is_business_email(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].lower().strip()
    return bool(domain) and domain not in FREE_MAIL_DOMAINS


@dataclass
class User:
    id: str
    email: str
    plan: str = "free"
    locale: str = ""
    timezone: str = ""
    created_at: str = field(default_factory=lambda: _iso(_now()))
    first_name: str = ""
    last_name: str = ""
    company: str = ""
    phone: str = ""
    role: str = ""
    specialty: str = ""
    title: str = ""
    country: str = ""
    marketing_opt_in: bool = False
    terms_accepted_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def with_profile(self, profile: dict[str, Any]) -> User:
        for k in PROFILE_FIELDS:
            if profile.get(k):
                setattr(self, k, str(profile[k])[:200])
        if "marketing_opt_in" in profile:
            self.marketing_opt_in = bool(profile["marketing_opt_in"])
        if profile.get("terms_accepted_at"):
            self.terms_accepted_at = str(profile["terms_accepted_at"])
        return self


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
    def create_user(self, email: str, profile: dict[str, Any] | None = None) -> User: ...
    def update_user(self, user: User) -> None: ...
    def put_token(self, token_hash: str, record: dict[str, Any]) -> None: ...
    def pop_token(self, token_hash: str) -> dict[str, Any] | None: ...
    def list_prefs(self, user_id: str) -> list[Pref]: ...
    def put_pref(self, user_id: str, pref: Pref) -> None: ...
    def delete_pref(self, user_id: str, scope: str, scope_key: str, key: str) -> bool: ...
    def delete_all_prefs(self, user_id: str) -> int: ...
    def mutate_watchlist(self, user_id: str, company: dict[str, Any], action: str) -> list[dict[str, Any]]: ...
    def add_event(self, user_id: str, event: dict[str, Any]) -> None: ...
    def list_events(self, user_id: str, limit: int = 500) -> list[dict[str, Any]]: ...
    def recent_events(self, days: int = 30, limit: int = 20000) -> list[dict[str, Any]]: ...


def _email_key(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:24]


def _watchlist_company(company: dict[str, Any], action: str) -> dict[str, Any]:
    if action not in ("toggle", "remove"):
        raise ValueError("watchlist action must be toggle or remove")
    if not isinstance(company, dict) or type(company.get("cik")) is not int or not 0 < company["cik"] < 10**10:
        raise ValueError("watchlist company needs a valid CIK")
    if not isinstance(company.get("name"), str) or not company["name"].strip() or len(company["name"]) > 200:
        raise ValueError("watchlist company needs a name of 1 to 200 characters")
    ticker = company.get("ticker")
    if ticker is not None and (not isinstance(ticker, str) or len(ticker) > 32):
        raise ValueError("watchlist ticker must be a short string or null")
    return {"cik": company["cik"], "name": company["name"], "ticker": ticker}


def _watchlist_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        row
        for row in value
        if isinstance(row, dict)
        and type(row.get("cik")) is int
        and 0 < row["cik"] < 10**10
        and isinstance(row.get("name"), str)
        and (row.get("ticker") is None or isinstance(row.get("ticker"), str))
    ]


class LakeUserStore:
    """JSON documents in the lake. Fine for a small user base behind one API process."""

    def __init__(self, storage: Storage):
        self.storage = storage
        with _LAKE_LOCKS_GUARD:
            self._lock = _LAKE_LOCKS.setdefault(storage.root, threading.RLock())

    def _read(self, rel: str) -> dict[str, Any] | None:
        with self._lock:
            if not self.storage.exists(rel):
                return None
            return json.loads(self.storage.read_text(rel))

    def _write(self, rel: str, doc: dict[str, Any]) -> None:
        with self._lock:
            self.storage.write_text(rel, json.dumps(doc))

    def get_user(self, user_id: str) -> User | None:
        d = self._read(f"{USERS}/{user_id}.json")
        return User(**{k: v for k, v in d.items() if k in User.__dataclass_fields__}) if d else None

    def get_user_by_email(self, email: str) -> User | None:
        with self._lock:
            d = self._read(f"{USERS}/by_email/{_email_key(email)}.json")
            return self.get_user(d["id"]) if d else None

    def create_user(self, email: str, profile: dict[str, Any] | None = None) -> User:
        with self._lock:
            existing = self.get_user_by_email(email)
            if existing is not None:
                return existing
            if policy := getattr(self, "registration_policy", None):
                policy(email)
            user = User(id=uuid.uuid4().hex, email=email.strip().lower()).with_profile(profile or {})
            self._write(f"{USERS}/{user.id}.json", user.to_dict())
            self._write(f"{USERS}/by_email/{_email_key(email)}.json", {"id": user.id})
            return user

    def update_user(self, user: User) -> None:
        self._write(f"{USERS}/{user.id}.json", user.to_dict())

    def put_token(self, token_hash: str, record: dict[str, Any]) -> None:
        self._write(f"{TOKENS}/{token_hash}.json", record)

    def pop_token(self, token_hash: str) -> dict[str, Any] | None:
        with self._lock:
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
        with self._lock:
            prefs = [p for p in self.list_prefs(user_id) if p.ident != pref.ident]
            prefs.append(pref)
            self._save_prefs(user_id, prefs)

    def delete_pref(self, user_id: str, scope: str, scope_key: str, key: str) -> bool:
        with self._lock:
            prefs = self.list_prefs(user_id)
            kept = [p for p in prefs if p.ident != (scope, scope_key, key)]
            if len(kept) == len(prefs):
                return False
            self._save_prefs(user_id, kept)
            return True

    def delete_all_prefs(self, user_id: str) -> int:
        with self._lock:
            n = len(self.list_prefs(user_id))
            self._save_prefs(user_id, [])
            return n

    def mutate_watchlist(self, user_id: str, company: dict[str, Any], action: str) -> list[dict[str, Any]]:
        company = _watchlist_company(company, action)
        with self._lock:
            value = next((p.value for p in self.list_prefs(user_id) if p.ident == ("global", "", "watchlist")), [])
            rows = _watchlist_rows(value)
            present = any(row["cik"] == company["cik"] for row in rows)
            updated = [row for row in rows if row["cik"] != company["cik"]]
            if action == "toggle" and not present:
                if len(updated) >= WATCHLIST_LIMIT:
                    raise ValueError(f"watchlist is limited to {WATCHLIST_LIMIT} companies")
                updated.append(company)
            self.put_pref(user_id, Pref("global", "", "watchlist", updated))
            return updated

    def add_event(self, user_id: str, event: dict[str, Any]) -> None:
        event = analytics_event(event)
        if event is None:
            return
        stamp = time.time_ns()
        self._write(f"{EVENTS}/{user_id}/{stamp // 1_000_000}-{stamp:020d}-{uuid.uuid4().hex[:6]}.json", event)

    def list_events(self, user_id: str, limit: int = 500) -> list[dict[str, Any]]:
        """Newest first. File names start with a millisecond timestamp, so the listing sorts by time."""
        out = []
        for rel in sorted(self.storage.ls(f"{EVENTS}/{user_id}"), reverse=True)[:limit]:
            d = self._read(rel)
            if d is not None:
                d["user_id"] = user_id
                out.append(d)
        return out

    def recent_events(self, days: int = 30, limit: int = 20000) -> list[dict[str, Any]]:
        since = int((time.time() - days * 86400) * 1000)
        out: list[dict[str, Any]] = []
        for user_dir in self.storage.ls(EVENTS):
            uid = user_dir.rstrip("/").rsplit("/", 1)[-1]
            for rel in sorted(self.storage.ls(user_dir), reverse=True):
                stamp = rel.rsplit("/", 1)[-1].split("-", 1)[0]
                if stamp.isdigit() and int(stamp) < since:
                    break
                d = self._read(rel)
                if d is not None:
                    d["user_id"] = uid
                    out.append(d)
                if len(out) >= limit:
                    return out
        return out


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
        ts = row.get("terms_accepted_at")
        return User(
            id=row["id"],
            email=row["email"],
            plan=row["plan"],
            locale=row["locale"] or "",
            timezone=row["timezone"] or "",
            created_at=_iso(row["created_at"]) if isinstance(row["created_at"], datetime) else str(row["created_at"]),
            first_name=row.get("first_name") or "",
            last_name=row.get("last_name") or "",
            company=row.get("company") or "",
            phone=row.get("phone") or "",
            role=row.get("role") or "",
            specialty=row.get("specialty") or "",
            title=row.get("title") or "",
            country=row.get("country") or "",
            marketing_opt_in=bool(row.get("marketing_opt_in")),
            terms_accepted_at=_iso(ts) if isinstance(ts, datetime) else (str(ts) if ts else ""),
        )

    def get_user(self, user_id: str) -> User | None:
        return self._user(self._one("SELECT * FROM users WHERE id = %s", (user_id,)))

    def get_user_by_email(self, email: str) -> User | None:
        return self._user(self._one("SELECT * FROM users WHERE email = %s", (email.strip().lower(),)))

    def create_user(self, email: str, profile: dict[str, Any] | None = None) -> User:
        if policy := getattr(self, "registration_policy", None):
            policy(email)
        user = User(id=uuid.uuid4().hex, email=email.strip().lower()).with_profile(profile or {})
        # The uniqueness constraint arbitrates simultaneous first sign-ins. Return the existing
        # account on conflict without overwriting its profile with a competing sign-up's defaults.
        row = self._one(
            "INSERT INTO users (id, email, plan, locale, timezone, created_at, first_name, last_name, "
            "company, phone, role, specialty, title, country, marketing_opt_in, terms_accepted_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email RETURNING *",
            (
                user.id,
                user.email,
                user.plan,
                user.locale,
                user.timezone,
                datetime.fromisoformat(user.created_at),
                *(getattr(user, field) for field in PROFILE_FIELDS),
                user.marketing_opt_in,
                datetime.fromisoformat(user.terms_accepted_at) if user.terms_accepted_at else None,
            ),
        )
        result = self._user(row)
        assert result is not None
        return result

    def update_user(self, user: User) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET first_name = %s, last_name = %s, company = %s, phone = %s, role = %s, "
                "specialty = %s, title = %s, country = %s, marketing_opt_in = %s, terms_accepted_at = %s, "
                "locale = %s, timezone = %s, plan = %s WHERE id = %s",
                (
                    user.first_name,
                    user.last_name,
                    user.company,
                    user.phone,
                    user.role,
                    user.specialty,
                    user.title,
                    user.country,
                    user.marketing_opt_in,
                    datetime.fromisoformat(user.terms_accepted_at) if user.terms_accepted_at else None,
                    user.locale,
                    user.timezone,
                    user.plan,
                    user.id,
                ),
            )

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
                    value=v,  # psycopg already decodes JSONB, including JSON string scalars
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

    def mutate_watchlist(self, user_id: str, company: dict[str, Any], action: str) -> list[dict[str, Any]]:
        company = _watchlist_company(company, action)
        encoded = json.dumps([company])
        match = json.dumps([{"cik": company["cik"]}])
        # One INSERT/ON CONFLICT statement locks and mutates the latest row version. A SELECT then
        # UPDATE (even through a single Python store) would race other workers/connections.
        row = self._one(
            """
            INSERT INTO user_prefs AS prefs (user_id, scope, scope_key, key, value, source, updated_at)
            VALUES (%s, 'global', '', 'watchlist', %s::jsonb, 'explicit', clock_timestamp())
            ON CONFLICT (user_id, scope, scope_key, key) DO UPDATE SET value = (
                SELECT COALESCE(jsonb_agg(item) FILTER (WHERE item->'cik' <> to_jsonb(%s::bigint)), '[]'::jsonb)
                    || CASE WHEN %s = 'toggle' AND NOT COALESCE(bool_or(item->'cik' = to_jsonb(%s::bigint)), false)
                       THEN %s::jsonb ELSE '[]'::jsonb END
                FROM jsonb_array_elements(CASE WHEN jsonb_typeof(prefs.value) = 'array'
                    THEN prefs.value ELSE '[]'::jsonb END) AS items(item)
                WHERE jsonb_typeof(item) = 'object' AND jsonb_typeof(item->'cik') = 'number'
                    AND item->>'cik' ~ '^[1-9][0-9]{0,9}$' AND jsonb_typeof(item->'name') = 'string'
                    AND (item->'ticker' IS NULL OR item->'ticker' = 'null'::jsonb
                        OR jsonb_typeof(item->'ticker') = 'string')
            ), source = 'explicit', updated_at = EXCLUDED.updated_at
            WHERE %s = 'remove' OR COALESCE(prefs.value @> %s::jsonb, false)
                OR jsonb_array_length(CASE WHEN jsonb_typeof(prefs.value) = 'array'
                    THEN prefs.value ELSE '[]'::jsonb END) < %s
            RETURNING value
            """,
            (
                user_id,
                encoded if action == "toggle" else "[]",
                company["cik"],
                action,
                company["cik"],
                encoded,
                action,
                match,
                WATCHLIST_LIMIT,
            ),
        )
        if row is None:
            raise ValueError(f"watchlist is limited to {WATCHLIST_LIMIT} companies")
        return row["value"]

    def add_event(self, user_id: str, event: dict[str, Any]) -> None:
        event = analytics_event(event)
        if event is None:
            return
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

    @staticmethod
    def _event(r: dict[str, Any]) -> dict[str, Any]:
        out = dict(r)
        # JSONB old/new values are already decoded by psycopg.
        if isinstance(out.get("at"), datetime):
            out["at"] = _iso(out["at"])
        return out

    def list_events(self, user_id: str, limit: int = 500) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT user_id, key, scope, old, new, source, at FROM pref_events WHERE user_id = %s "
            "ORDER BY at DESC LIMIT %s",
            (user_id, limit),
        )
        return [self._event(r) for r in rows]

    def recent_events(self, days: int = 30, limit: int = 20000) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT user_id, key, scope, old, new, source, at FROM pref_events "
            "WHERE at >= now() - make_interval(days => %s) ORDER BY at DESC LIMIT %s",
            (days, limit),
        )
        return [self._event(r) for r in rows]


def store_from_settings(storage: Storage, database_url: str) -> UserStore:
    if database_url.startswith(("postgresql://", "postgres://")):
        return PostgresUserStore(database_url)
    return LakeUserStore(storage)


# ---------------------------------------------------------------------------------------------
# Sessions and sign-in tokens
# ---------------------------------------------------------------------------------------------
class SessionSigner:
    """Signed sessions. The API supplies a durable store and accepts only registered v2 tokens.

    The no-store v1 mode remains for isolated signature/rate-limiter consumers; it is never used by
    create_app. Existing unregistered v1 browser sessions must sign in again after this upgrade.
    """

    def __init__(self, secret: str, days: int = 30, store=None):
        if not secret:
            secret = secrets.token_urlsafe(32)
            log.warning("SESSION_SECRET is empty: sessions will not survive a restart")
        self.key = secret.encode()
        self.days = days
        self.store = store

    def _sig(self, body: str) -> str:
        return hmac.new(self.key, body.encode(), hashlib.sha256).hexdigest()[:40]

    def sign(self, user_id: str, now: float | None = None, device_label: str = "") -> str:
        issued = time.time() if now is None else now
        exp = int(issued + self.days * 86400)
        ident = secrets.token_hex(24)
        version = "v2" if self.store is not None else "v1"
        body = f"{version}.{user_id}.{exp}.{ident}"
        if self.store is not None:
            label = "".join(char for char in device_label if char.isprintable()).strip()[:120] or "Unknown device"
            self.store.create_session(
                {
                    "id": ident,
                    "user_id": user_id,
                    "created_at": _iso(datetime.fromtimestamp(issued, UTC)),
                    "expires_at": _iso(datetime.fromtimestamp(exp, UTC)),
                    "last_seen_at": _iso(datetime.fromtimestamp(issued, UTC)),
                    "device_label": label,
                    "revoked_at": None,
                }
            )
        return f"{body}.{self._sig(body)}"

    def session(self, token: str | None, now: float | None = None) -> dict[str, Any] | None:
        if not token or len(token) > 1024:
            return None
        parts = token.split(".")
        version = "v2" if self.store is not None else "v1"
        if len(parts) != 5 or parts[0] != version:
            return None
        _, user_id, exp, nonce, sig = parts
        body = f"{version}.{user_id}.{exp}.{nonce}"
        if not hmac.compare_digest(sig, self._sig(body)):
            return None
        current = time.time() if now is None else now
        if not exp.isdigit() or int(exp) <= current:
            return None
        if self.store is None:
            return {"user_id": user_id, "id": nonce}
        record = self.store.session(nonce, user_id, current)
        if not record or datetime.fromisoformat(record["expires_at"]).timestamp() != int(exp):
            return None
        return record

    def verify(self, token: str | None, now: float | None = None) -> str | None:
        record = self.session(token, now)
        return record["user_id"] if record else None


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_magic_link(
    store: UserStore, email: str, site_url: str, profile: dict[str, Any] | None = None
) -> tuple[str, str]:
    """(token, link). The store keeps only the hash; the link carries the token once. A sign-up's
    profile rides along and is applied when the link is redeemed."""
    token = secrets.token_urlsafe(32)
    store.put_token(
        token_hash(token),
        {
            "purpose": "magic",
            "email": email.strip().lower(),
            "expires_at": _iso(_now() + timedelta(minutes=MAGIC_LINK_MINUTES)),
            **({"profile": profile} if profile else {}),
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
    profile = rec.get("profile")
    user = store.get_user_by_email(rec["email"])
    if user is None:
        return store.create_user(rec["email"], profile)
    if profile:  # an existing account signing up again: fill what is empty, never overwrite
        missing = {k: v for k, v in profile.items() if k in PROFILE_FIELDS and not getattr(user, k, "")}
        if missing or ("marketing_opt_in" in profile) or profile.get("terms_accepted_at"):
            user.with_profile(
                {**missing, **{k: profile[k] for k in ("marketing_opt_in", "terms_accepted_at") if k in profile}}
            )
            store.update_user(user)
    return user


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


SIGNUP_REQUIRED = ("first_name", "last_name", "company", "phone", "title")


def validate_signup(payload: dict[str, Any], business_only: bool) -> str | None:
    """A human-readable problem with a sign-up, or None."""
    email = str(payload.get("email") or "").strip().lower()
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        return "a valid email is required"
    if business_only and not is_business_email(email):
        return "please enter a valid business email address"
    for k in SIGNUP_REQUIRED:
        if not str(payload.get(k) or "").strip():
            return f"{k.replace('_', ' ')} is required"
    if not payload.get("accept_terms"):
        return "you need to accept the terms of use and privacy policy"
    return None


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


# ---------------------------------------------------------------------------------------------
# UI events, inferred proposals, and the option touch report
# ---------------------------------------------------------------------------------------------
UI_SCOPE = "ui"

# Analytics is deliberately separate from the arbitrary JSON a preference can contain.
# Never copy watchlists, company identifiers, profile names, filenames or UI props into events.
ANALYTICS_VALUES = {
    "scale": ("units", "thousands", "millions", "billions"),
    "statement": ("IS", "BS", "CF", "EQ", "CI"),
    "negative_style": ("parentheses", "minus"),
    "column_order": ("newest_right", "newest_left"),
    "period_mode": ("as_filed", "quarterly", "annual", "ltm"),
}
ANALYTICS_UI = frozenset(
    (
        "export.download",
        "export.profile.load",
        "export.profile.save",
        "export.remember",
        "export.open",
        "card.preset",
        "card.swap",
        "proposal.shown",
        "proposal.dismiss",
    )
)
ANALYTICS_COUNTS_ONLY = frozenset(("headline_cards", "export_config"))


def analytics_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """Allowlisted telemetry only. Applied on write and again when reading legacy events."""
    key, scope = event.get("key"), event.get("scope")
    if not isinstance(key, str) or not isinstance(scope, str):
        return None
    base = {"key": key, "scope": scope, "at": event.get("at", _iso(_now()))}
    if scope == UI_SCOPE:
        if key not in ANALYTICS_UI:
            return None
        return {**base, "old": None, "new": None, "source": "ui"}
    if scope not in SCOPES or event.get("source") not in SOURCES:
        return None

    def safe_value(value: Any) -> bool:
        if key in ANALYTICS_VALUES:
            return isinstance(value, str) and value in ANALYTICS_VALUES[key]
        if key == "periods_shown":
            return type(value) is int and 1 <= value <= 60
        return key == "restated" and type(value) is bool

    if key in ANALYTICS_COUNTS_ONLY:
        old, new = None, None
    elif safe_value(event.get("new")):
        old = event.get("old") if safe_value(event.get("old")) else None
        new = event["new"]
    else:
        return None
    return {**base, "old": old, "new": new, "source": event["source"]}


def validate_event(payload: dict[str, Any]) -> str | None:
    name = payload.get("name")
    if not isinstance(name, str) or not (1 <= len(name) <= 60) or not all(c.isalnum() or c in "._-:" for c in name):
        return "name must be 1-60 characters of letters, digits, dots, dashes, colons, underscores"
    props = payload.get("props", {})
    if props is None:
        props = {}
    if not isinstance(props, dict) or len(json.dumps(props)) > 2000:
        return "props must be a small object"
    return None


def ui_event(name: str, props: dict[str, Any] | None) -> dict[str, Any]:
    """A UI event in the shape of a preference event, so one table (or folder) holds both."""
    return {"key": name, "scope": UI_SCOPE, "old": None, "new": props or {}, "source": "ui", "at": _iso(_now())}


def _proposal_id(key: str, value: Any) -> str:
    return f"{key}={json.dumps(value, sort_keys=True)}"


def proposals(prefs: list[Pref]) -> list[dict[str, Any]]:
    """Choices repeated on several companies that the global default does not yet make.

    Three strikes: the same explicit value at company scope on PROPOSAL_STRIKES companies, while the
    global value (or the system default) says something else, yields one proposal. Dismissed twice,
    a proposal is never shown again; accepting writes the global preference with source=inferred.
    """
    dismissed = next((p.value for p in prefs if p.ident == ("global", "", DISMISSED_KEY)), None)
    dismissed = dismissed if isinstance(dismissed, dict) else {}
    global_vals = {p.key: p.value for p in prefs if p.scope == "global"}
    counts: dict[tuple[str, str], set[str]] = {}
    values: dict[tuple[str, str], Any] = {}
    for p in prefs:
        if p.scope != "company" or p.key not in PROPOSABLE or p.source != "explicit":
            continue
        pid = _proposal_id(p.key, p.value)
        counts.setdefault((p.key, pid), set()).add(p.scope_key)
        values[(p.key, pid)] = p.value
    out = []
    for (key, pid), ciks in counts.items():
        value = values[(key, pid)]
        current = global_vals.get(key, DEFAULTS.get(key))
        if len(ciks) < PROPOSAL_STRIKES or current == value or dismissed.get(pid, 0) >= PROPOSAL_DISMISSALS:
            continue
        out.append(
            {
                "id": pid,
                "key": key,
                "value": value,
                "companies": sorted(ciks),
                "current": current,
                "message": f"You chose this on {len(ciks)} companies. Make it your default everywhere?",
            }
        )
    return sorted(out, key=lambda d: (-len(d["companies"]), d["key"]))


def accept_proposal(store: UserStore, user_id: str, key: str, value: Any) -> Pref:
    if key not in PROPOSABLE:
        raise ValueError("not a proposable preference")
    old = next((p.value for p in store.list_prefs(user_id) if p.ident == ("global", "", key)), None)
    pref = Pref(scope="global", scope_key="", key=key, value=value, source="inferred")
    store.put_pref(user_id, pref)
    store.add_event(
        user_id, {"key": key, "scope": "global", "old": old, "new": value, "source": "inferred", "at": pref.updated_at}
    )
    return pref


def dismiss_proposal(store: UserStore, user_id: str, key: str, value: Any) -> int:
    """Count a dismissal; returns how many times this proposal has now been dismissed."""
    prefs = store.list_prefs(user_id)
    cur = next((p.value for p in prefs if p.ident == ("global", "", DISMISSED_KEY)), None)
    cur = dict(cur) if isinstance(cur, dict) else {}
    pid = _proposal_id(key, value)
    cur[pid] = int(cur.get(pid, 0)) + 1
    store.put_pref(user_id, Pref(scope="global", scope_key="", key=DISMISSED_KEY, value=cur, source="explicit"))
    store.add_event(
        user_id,
        {
            "key": "proposal.dismiss",
            "scope": UI_SCOPE,
            "old": None,
            "new": {"id": pid, "times": cur[pid]},
            "source": "ui",
            "at": _iso(_now()),
        },
    )
    return cur[pid]


def touch_report(events: list[dict[str, Any]], days: int) -> dict[str, Any]:
    """Which options people touch: preference writes by key and value, UI events by name."""
    users: set[str] = set()
    pref_keys: dict[str, dict[str, Any]] = {}
    ui: dict[str, dict[str, Any]] = {}
    accepted = 0
    for e in events:
        uid = str(e.get("user_id") or "")
        e = analytics_event(e)
        if e is None:
            continue
        accepted += 1
        users.add(uid)
        key = str(e.get("key") or "")
        if e.get("scope") == UI_SCOPE:
            d = ui.setdefault(key, {"name": key, "count": 0, "users": set()})
            d["count"] += 1
            d["users"].add(uid)
            continue
        d = pref_keys.setdefault(
            key, {"key": key, "writes": 0, "users": set(), "scopes": {}, "values": {}, "inferred": 0}
        )
        d["writes"] += 1
        d["users"].add(uid)
        d["scopes"][str(e.get("scope"))] = d["scopes"].get(str(e.get("scope")), 0) + 1
        if key not in ANALYTICS_COUNTS_ONLY:
            v = json.dumps(e.get("new"), sort_keys=True)
            d["values"][v] = d["values"].get(v, 0) + 1
        if e.get("source") == "inferred":
            d["inferred"] += 1
    prefs_out = []
    for d in sorted(pref_keys.values(), key=lambda d: -d["writes"]):
        top = sorted(d["values"].items(), key=lambda kv: -kv[1])[:5]
        prefs_out.append(
            {
                "key": d["key"],
                "writes": d["writes"],
                "users": len(d["users"]),
                "inferred": d["inferred"],
                "scopes": d["scopes"],
                "top_values": [{"value": json.loads(v), "n": n} for v, n in top],
            }
        )
    ui_out = [
        {"name": d["name"], "count": d["count"], "users": len(d["users"])}
        for d in sorted(ui.values(), key=lambda d: -d["count"])
    ]
    return {"days": days, "events": accepted, "users": len(users), "prefs": prefs_out, "ui": ui_out}


__all__ = [
    "DEFAULTS",
    "PROPOSABLE",
    "RESOLUTION",
    "SCOPES",
    "LakeUserStore",
    "PostgresUserStore",
    "Pref",
    "SessionSigner",
    "User",
    "accept_proposal",
    "dismiss_proposal",
    "get_or_create_user",
    "google_email_for_code",
    "is_business_email",
    "issue_magic_link",
    "proposals",
    "redeem_magic_link",
    "resolve",
    "scope_key_for",
    "store_from_settings",
    "touch_report",
    "ui_event",
    "validate_event",
    "validate_pref",
    "validate_signup",
]
