"""Server-side session revocation and tenant policy against lake and real Postgres stores."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import time, time_ns

import pytest
from fastapi.testclient import TestClient

from filings_hub import accounts, tenancy
from filings_hub.api.app import create_app
from filings_hub.config import Settings
from filings_hub.lake.storage import Storage


@pytest.fixture(params=["lake", "postgres"])
def security(request, tmp_path):
    url = request.getfixturevalue("pg_url") if request.param == "postgres" else ""
    storage = Storage(str(tmp_path))
    users = accounts.store_from_settings(storage, url)
    store = tenancy.SecurityStore(users, storage, url)
    yield users, store, url, storage
    if url:
        users.conn.close()


def person(users, label):
    return users.create_user(f"{label}-{time_ns()}@example.test")


def test_sessions_are_durable_revocable_expiring_and_account_scoped(security):
    users, store, url, storage = security
    user, other = person(users, "owner"), person(users, "other")
    now = time()
    signer = accounts.SessionSigner("secret", 1, store)
    first = signer.sign(user.id, now=now, device_label="Laptop\nBrowser")
    second = signer.sign(user.id, now=now + 1, device_label="Phone")
    outsider = signer.sign(other.id, now=now)
    assert first.startswith("v2.")
    assert signer.verify(first, now=now + 1) == user.id
    assert signer.verify(first[:-1] + ("0" if first[-1] != "0" else "1")) is None
    assert signer.verify(accounts.SessionSigner("secret").sign(user.id)) is None
    unregistered = f"v2.{user.id}.{int(now + 86400)}.unknown"
    assert signer.verify(f"{unregistered}.{signer._sig(unregistered)}") is None
    rows = store.sessions(user.id, now)
    assert {row["device_label"] for row in rows} == {"LaptopBrowser", "Phone"}
    assert len(rows) == 2
    sid = signer.session(first, now=now + 601)["id"]
    assert signer.session(first, now=now + 700)["last_seen_at"] == tenancy.stamp(now + 601)
    other_sid = signer.session(outsider, now=now)["id"]
    with pytest.raises(tenancy.SecurityError, match="session not found") as forbidden:
        store.revoke(user.id, other_sid, now)
    assert forbidden.value.status == 404
    assert store.revoke(user.id, sid, now + 1)
    assert not store.revoke(user.id, sid, now + 2)  # idempotent and no duplicate audit mutation
    # A separate API/store instance cannot resurrect a revoked token after restart.
    restarted = accounts.SessionSigner("secret", 1, tenancy.SecurityStore(users, storage, url))
    assert restarted.verify(first, now=now + 2) is None
    assert restarted.verify(second, now=now + 2) == user.id
    assert signer.verify(second, now=now + 86402) is None
    assert store.sessions(user.id, now + 86402) == []
    assert signer.verify(outsider, now=now + 2) == other.id
    audit = store.audit_records(user.id)
    assert sum(row["action"] == "session.revoked" for row in audit) == 1
    assert all(row["actor_id"] == user.id and row["organization_id"] is None for row in audit)
    assert all("token" not in row["metadata"] for row in audit)


def test_expiry_boundary_and_revoke_others(security):
    users, store, _, _ = security
    user = person(users, "revoke")
    signer = accounts.SessionSigner("secret", 1, store)
    now = int(time())
    keep = signer.sign(user.id, now=now)
    others = [signer.sign(user.id, now=now) for _ in range(3)]
    sid = signer.session(keep, now=now)["id"]
    assert store.revoke_others(user.id, sid, now) == 3
    assert store.revoke_others(user.id, sid, now) == 0
    assert signer.verify(keep, now=now + 86399) == user.id
    assert signer.verify(keep, now=now + 86400) is None
    assert all(signer.verify(token, now=now) is None for token in others)
    with pytest.raises(tenancy.SecurityError) as expired:
        store.revoke_others(user.id, sid, now + 86400)
    assert expired.value.status == 401


def test_tenant_roles_fail_closed_and_last_owner_is_preserved(security):
    users, store, _, _ = security
    owner, admin, member, outsider = [person(users, label) for label in ("owner", "admin", "member", "outside")]
    org = store.create_organization(owner.id, "Research team")
    other_org = store.create_organization(outsider.id, "Other team")
    oid = org["id"]
    store.change_member(oid, owner.id, admin.id, "admin")
    store.change_member(oid, admin.id, member.id, "member")
    assert {r["id"] for r in store.organizations(member.id)} == {oid}
    assert store.organization(oid, member.id)["role"] == "member"
    assert len(store.members(oid, member.id)) == 3
    for actor, target_org in [(outsider.id, oid), (owner.id, other_org["id"])]:
        for fn, args in [
            (store.organization, (target_org, actor)),
            (store.members, (target_org, actor)),
            (store.audit_records, (actor, target_org)),
            (store.change_member, (target_org, actor, actor, "owner")),
        ]:
            with pytest.raises(tenancy.SecurityError) as denied:
                fn(*args)
            assert denied.value.status == 404
    for actor, target, role in [
        (member.id, member.id, "owner"),
        (admin.id, admin.id, "owner"),
        (admin.id, owner.id, "member"),
        (admin.id, member.id, "admin"),
    ]:
        with pytest.raises(tenancy.SecurityError) as denied:
            store.change_member(oid, actor, target, role, "update")
        assert denied.value.status == 403
    with pytest.raises(tenancy.SecurityError) as last_owner:
        store.change_member(oid, owner.id, owner.id, action="remove")
    assert last_owner.value.status == 409
    with pytest.raises(tenancy.SecurityError) as invalid_role:
        store.change_member(oid, owner.id, member.id, "super-admin", "update")
    assert invalid_role.value.status == 422
    with pytest.raises(tenancy.SecurityError) as unknown:
        store.change_member(oid, owner.id, "does-not-exist", "member")
    assert unknown.value.status == 422
    # Owner transfer uses explicit promotion followed by removal; no ownerless intermediate state.
    store.change_member(oid, owner.id, admin.id, "owner", "update")
    store.change_member(oid, admin.id, owner.id, action="remove")
    assert store.organizations(owner.id) == []
    with pytest.raises(tenancy.SecurityError) as removed:
        store.members(oid, owner.id)
    assert removed.value.status == 404
    rows = store.audit_records(admin.id, oid)
    assert {row["action"] for row in rows} == {
        "organization.created",
        "membership.added",
        "membership.role_changed",
        "membership.removed",
    }
    assert all(row["organization_id"] == oid for row in rows)
    with pytest.raises(tenancy.SecurityError) as no_audit:
        store.audit_records(member.id, oid)
    assert no_audit.value.status == 403


def test_concurrent_owner_removals_are_serialized_across_stores(security):
    users, store, url, storage = security
    owner, other = person(users, "concurrent-owner"), person(users, "other-owner")
    org = store.create_organization(owner.id, "Concurrent team")["id"]
    store.change_member(org, owner.id, other.id, "owner")
    second = tenancy.SecurityStore(users, storage, url)
    barrier = Barrier(2)

    def remove(item):
        backend, actor = item
        barrier.wait(timeout=10)
        try:
            backend.change_member(org, actor, actor, action="remove")
            return "removed"
        except tenancy.SecurityError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(remove, [(store, owner.id), (second, other.id)]))
    assert outcomes.count("removed") == 1 and outcomes.count(409) == 1
    remaining = store.organizations(owner.id) or store.organizations(other.id)
    assert remaining[0]["role"] == "owner"


@pytest.fixture(params=["lake", "postgres"])
def api(request, tmp_path, db):
    url = request.getfixturevalue("pg_url") if request.param == "postgres" else ""
    app = create_app(
        Settings(
            lake_root=str(tmp_path),
            database_url=url,
            api_key="k",
            session_secret="stable",
            auth_dev_links=True,
            api_rate_limit_per_minute=10000,
        ),
        db=db,
    )
    with TestClient(app) as client:
        yield client, app
    if url:
        app.state.users.conn.close()


def signed(app, user, label="Browser"):
    return {"X-API-Key": "k", "X-Session": app.state.signer.sign(user.id, device_label=label)}


def test_session_api_logout_revokes_token_but_preserves_anonymous_browsing(api):
    client, app = api
    user, other = person(app.state.users, "web"), person(app.state.users, "other-web")
    first, second, outside = signed(app, user), signed(app, user, "Phone"), signed(app, other)
    own = client.get("/me/sessions", headers=first).json()
    assert own["current_session_id"] == next(row["id"] for row in own["sessions"] if row["current"])
    assert len(own["sessions"]) == 2 and "user_id" not in own["sessions"][0]
    assert "X-Session" not in str(own) and first["X-Session"] not in str(own)
    outside_id = client.get("/me/sessions", headers=outside).json()["current_session_id"]
    assert client.delete(f"/me/sessions/{outside_id}", headers=first).status_code == 404
    assert client.post("/me/sessions/revoke-others", headers=first).json() == {"revoked": 1}
    for route in ["/me", "/me/prefs", "/me/watchlist", "/subscriptions", "/organizations", "/me/security-audit"]:
        assert client.get(route, headers=second).status_code == 401, route
    assert client.get("/me", headers=outside).status_code == 200
    assert client.post("/auth/logout", headers=first).json() == {"revoked": True}
    assert client.get("/me", headers=first).status_code == 401
    assert client.post("/auth/logout", headers=first).status_code == 401
    assert client.get("/auth/config", headers={"X-API-Key": "k"}).status_code == 200
    assert client.get("/search", params={"q": "AAPL"}, headers={"X-API-Key": "k"}).status_code == 200
    legacy = {"X-API-Key": "k", "X-Session": accounts.SessionSigner("stable").sign(user.id)}
    assert client.get("/me", headers=legacy).status_code == 401
    fresh = signed(app, user)
    assert client.delete("/me/sessions/current", headers=fresh).json() == {"revoked": True, "current": True}
    assert client.get("/me", headers=fresh).status_code == 401


def test_tenant_api_authorizes_every_read_write_and_audit(api):
    client, app = api
    owner, member, outsider = [person(app.state.users, label) for label in ("api-owner", "api-member", "api-outside")]
    h, m, o = signed(app, owner), signed(app, member), signed(app, outsider)
    response = client.post("/organizations", json={"name": "Fund A"}, headers=h)
    assert response.status_code == 201
    org = response.json()["organization"]["id"]
    base = f"/organizations/{org}"
    assert client.get("/organizations", headers=o).json() == {"organizations": []}
    for route in [base, base + "/members", base + "/audit"]:
        assert client.get(route, headers={**o, "X-Organization-ID": org}).status_code == 404
    assert client.post(base + "/members", json={"user_id": outsider.id, "role": "owner"}, headers=o).status_code == 404
    assert client.post(base + "/members", json={"user_id": member.id}, headers=h).status_code == 201
    assert client.get(base + "/members", headers=m).status_code == 200
    assert client.patch(base + f"/members/{member.id}", json={"role": "owner"}, headers=m).status_code == 403
    assert client.delete(base + f"/members/{owner.id}", headers=m).status_code == 403
    assert client.get(base + "/audit", headers=m).status_code == 403
    assert client.delete(base + f"/members/{owner.id}", headers=h).status_code == 409
    assert client.delete(base + f"/members/{member.id}", headers=h).status_code == 200
    assert client.get(base, headers=m).status_code == 404
    assert client.get("/organizations", headers=m).json() == {"organizations": []}
    assert client.get("/me", headers=m).status_code == 200  # tenant removal is not personal account deletion
    events = client.get(base + "/audit", headers=h).json()["events"]
    assert {r["action"] for r in events} == {"organization.created", "membership.added", "membership.removed"}
    assert client.get(base + "/audit", headers={"X-API-Key": "k"}).status_code == 401


def test_magic_link_creates_registered_device_session(api):
    client, app = api
    user = person(app.state.users, "magic-security")
    token, _ = accounts.issue_magic_link(app.state.users, user.email, "")
    response = client.post(
        "/auth/verify", json={"token": token}, headers={"X-API-Key": "k", "User-Agent": "Test browser"}
    )
    assert response.status_code == 200
    h = {"X-API-Key": "k", "X-Session": response.json()["session"]}
    rows = client.get("/me/sessions", headers=h).json()["sessions"]
    assert rows[0]["device_label"] == "Test browser" and rows[0]["current"] is True
    assert client.post("/auth/verify", json={"token": token}, headers={"X-API-Key": "k"}).status_code == 401


def test_backend_failure_does_not_fall_back_to_signed_identity(security, monkeypatch):
    users, store, _, _ = security
    user = person(users, "fail-closed")
    signer = accounts.SessionSigner("secret", 1, store)
    token = signer.sign(user.id)

    def unavailable(*_args):
        raise OSError("session store unavailable")

    monkeypatch.setattr(store, "session", unavailable)
    with pytest.raises(OSError, match="unavailable"):
        signer.verify(token)
