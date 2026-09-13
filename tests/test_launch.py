"""Durable first-twenty allocation, verified opt-in, safe auth returns and reviewed lead management."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import time_ns
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from filings_hub import accounts
from filings_hub.api.app import create_app
from filings_hub.config import Settings
from filings_hub.launch import CAMPAIGN_ID, ENDS, STARTS, DemoInput, LaunchStore, ReservationInput
from filings_hub.platform_admin import csrf_for
from filings_hub.tenancy import SecurityError, SecurityStore

REGIONS = ("US", "UK", "EU", "AU", "ROW")
HEADERS = {"X-API-Key": "test-launch-key"}
STRONG = "A unique! operator phrase 867"


@pytest.fixture(params=["lake", "postgres"])
def launch_api(request, tmp_path, db):
    url = request.getfixturevalue("pg_url") if request.param == "postgres" else ""
    settings = Settings(
        lake_root=str(tmp_path),
        database_url=url,
        api_key="test-launch-key",
        session_secret="launch-test-session",
        auth_dev_links=True,
        site_url="http://localhost:3201",
        api_rate_limit_per_minute=10000,
        platform_admin_enabled=True,
        platform_admin_environment="development",
        platform_admin_origin="http://localhost:3201",
        platform_admin_local_bootstrap=True,
    )
    app = create_app(settings, db=db)
    # pg_url is the disposable integration fixture; launch cases need independent campaign state.
    with app.state.account_security.transaction() as tx:
        for kind in ("launch_memberships", "demo_requests"):
            for row in tx.find(kind):
                tx.delete(kind, row["id"])
    now = [STARTS.timestamp() - 86400 * 30]
    app.state.launch.clock = lambda: now[0]
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        yield client, app, now
    if url:
        app.state.users.conn.close()


def new_user(app):
    return app.state.users.create_user(f"launch-{time_ns()}-{uuid4().hex[:5]}@example.test")


def signed(app, user):
    return {**HEADERS, "X-Session": app.state.signer.sign(user.id)}


def reserve(region="US"):
    return ReservationInput(region=region, accept_terms=True)


def demo(**changes):
    return {
        "request_id": str(uuid4()),
        "name": "Independent Analyst",
        "email": "analyst@example.test",
        "region": "ROW",
        "workflow": "Compare a company across reporting periods.",
        **changes,
    }


def parallel_stores(app, action, count=8):
    original = app.state.account_security
    users = [
        accounts.PostgresUserStore(original.database_url)
        if original.database_url
        else accounts.LakeUserStore(original.storage)
        for _ in range(count)
    ]
    stores = [
        LaunchStore(
            SecurityStore(user, original.storage, original.database_url),
            identity_secret="launch-test-session",
            clock=app.state.launch.clock,
        )
        for user in users
    ]
    barrier = Barrier(count)

    def work(item):
        i, store = item
        barrier.wait(timeout=15)
        return action(store, i)

    try:
        with ThreadPoolExecutor(max_workers=count) as pool:
            return list(pool.map(work, enumerate(stores)))
    finally:
        for user in users:
            if isinstance(user, accounts.PostgresUserStore):
                user.conn.close()


def test_only_verified_explicit_opt_in_reserves_and_campaign_is_not_cached(launch_api):
    client, app, _ = launch_api
    assert client.get("/launch/campaign").status_code == 401
    public = client.get("/launch/campaign", headers=HEADERS)
    assert public.status_code == 200 and public.headers["cache-control"] == "private, no-store"
    assert public.json()["campaign"]["remaining"] == 20
    issued = client.post("/auth/magic-link", headers=HEADERS, json={"email": "founder@example.test"})
    token = parse_qs(urlsplit(issued.json()["dev_link"]).query)["token"][0]
    assert client.get("/launch/campaign", headers=HEADERS).json()["campaign"]["allocated"] == 0
    for fake in ({}, {"X-User-ID": "disclosure"}, {"X-Session": "forged"}):
        assert (
            client.post("/me/early-access", headers={**HEADERS, **fake}, json=reserve().model_dump()).status_code == 401
        )
    verified = client.post("/auth/verify", headers=HEADERS, json={"token": token}).json()
    headers = {**HEADERS, "X-Session": verified["session"]}
    assert client.get("/me/early-access", headers=headers).json()["membership"] is None
    assert (
        client.post("/me/early-access", headers=headers, json={"region": "EU", "accept_terms": False}).status_code
        == 422
    )
    assert client.post("/me/early-access", headers=headers, json={"region": "EU", "accept_terms": 1}).status_code == 422
    assert (
        client.post("/me/early-access", headers=headers, json={"region": "Europe", "accept_terms": True}).status_code
        == 422
    )
    joined = client.post("/me/early-access", headers=headers, json=reserve("EU").model_dump())
    assert joined.status_code == 200 and joined.headers["cache-control"] == "private, no-store"
    assert joined.json()["membership"]["status"] == "reserved"
    assert joined.json()["membership"]["position"] == 1
    assert joined.json()["campaign"]["remaining"] == 19
    assert joined.json()["entitlement"]["active"] is False
    assert joined.json()["campaign"]["auto_charge"] is False
    assert client.get("/me/early-access", headers=signed(app, new_user(app))).json()["membership"] is None


def test_last_place_is_allocated_once_across_independent_connections_and_regions(launch_api):
    _, app, _ = launch_api
    for _ in range(19):
        app.state.launch.reserve(new_user(app).id, reserve())
    contenders = [new_user(app) for _ in range(8)]
    results = parallel_stores(app, lambda store, i: store.reserve(contenders[i].id, reserve(REGIONS[i % 5])))
    assert sum(row["membership"]["status"] == "reserved" for row in results) == 1
    assert sum(row["membership"]["status"] == "waitlisted" for row in results) == 7
    assert {row["membership"]["position"] for row in results} == set(range(20, 28))
    campaign = LaunchStore(app.state.account_security).campaign()["campaign"]
    assert campaign["allocated"] == 20 and campaign["remaining"] == 0
    with app.state.account_security.transaction() as tx:
        rows = tx.find("launch_memberships", campaign_id=CAMPAIGN_ID)
        assert len(rows) == 27
        assert len({row["user_id"] for row in rows}) == 27


def test_one_account_keeps_one_place_across_regions_retries_and_service_recreation(launch_api):
    _, app, _ = launch_api
    user = new_user(app)
    results = parallel_stores(app, lambda store, i: store.reserve(user.id, reserve(REGIONS[i % 5])))
    memberships = [row["membership"] for row in results]
    assert all(row == memberships[0] for row in memberships)
    assert memberships[0]["position"] == 1
    fresh = LaunchStore(app.state.account_security, clock=app.state.launch.clock)
    assert fresh.membership(user.id)["membership"] == memberships[0]
    assert fresh.campaign()["campaign"]["allocated"] == 1
    with app.state.account_security.transaction() as tx:
        audit = tx.find("audit", actor_id=user.id)
        assert sum(row["action"] == "launch.reserved" for row in audit) == 1


def test_launch_calendar_window_closure_and_idempotency(launch_api):
    client, app, now = launch_api
    user = new_user(app)
    headers = signed(app, user)
    original = client.post("/me/early-access", headers=headers, json=reserve().model_dump()).json()
    assert original["entitlement"]["phase"] == "upcoming"
    assert original["membership"]["benefit_starts_at"] == "2026-11-01T00:00:00+00:00"
    assert original["membership"]["benefit_ends_at"] == "2027-05-01T00:00:00+00:00"
    now[0] = STARTS.timestamp()
    active = client.get("/me/early-access", headers=headers).json()
    assert active["entitlement"]["active"] and active["entitlement"]["plan"] == "launch"
    assert active["entitlement"]["phase"] == "active"
    assert active["campaign"]["state"] == "closed"
    assert client.post("/me/early-access", headers=headers, json=reserve().model_dump()).status_code == 200
    assert (
        client.post("/me/early-access", headers=signed(app, new_user(app)), json=reserve().model_dump()).status_code
        == 409
    )
    now[0] = ENDS.timestamp()
    assert not client.get("/me/early-access", headers=headers).json()["entitlement"]["active"]
    assert client.get("/me/early-access", headers=headers).json()["entitlement"]["plan"] is None
    assert client.get("/me/early-access", headers=headers).json()["entitlement"]["phase"] == "expired"
    # The campaign does not mutate account billing, grant unlimited AI or initiate a payment.
    assert app.state.users.get_user(user.id).plan == "free"


def test_suspended_account_cannot_reserve_and_failed_audit_rolls_back(launch_api, monkeypatch):
    client, app, _ = launch_api
    user = new_user(app)
    headers = signed(app, user)
    with app.state.account_security.transaction() as tx:
        tx.put("platform_controls", {"id": user.id, "status": "suspended"})
    assert client.post("/me/early-access", headers=headers, json=reserve().model_dump()).status_code == 401
    with pytest.raises(SecurityError, match="suspended"):
        app.state.launch.reserve(user.id, reserve())
    other = new_user(app)

    def fail(*args, **kwargs):
        raise RuntimeError("audit storage unavailable")

    monkeypatch.setattr(app.state.account_security, "audit", fail)
    with pytest.raises(RuntimeError, match="audit storage"):
        app.state.launch.reserve(other.id, reserve())
    assert app.state.launch.campaign()["campaign"]["allocated"] == 0
    assert app.state.launch.membership(other.id)["membership"] is None


def test_demo_intake_validation_idempotency_no_slot_and_no_public_pii(launch_api):
    client, app, _ = launch_api
    assert client.post("/demo-requests", json=demo()).status_code == 401
    for change in ({"email": "bad"}, {"workflow": "short"}, {"region": "XX"}, {"request_id": "bad"}, {"name": " "}):
        assert client.post("/demo-requests", headers=HEADERS, json=demo(**change)).status_code == 422
    payload = demo(email=" Analyst@Example.Test ")
    result = client.post("/demo-requests", headers=HEADERS, json=payload)
    assert result.status_code == 201 and result.json() == {"received": True, "reference": payload["request_id"]}
    again = client.post("/demo-requests", headers=HEADERS, json=payload)
    assert again.json() == result.json()
    assert client.post("/demo-requests", headers=HEADERS, json={**payload, "name": "Different"}).status_code == 409
    assert client.get("/demo-requests", headers=HEADERS).status_code == 405
    assert client.get("/demo-requests/" + payload["request_id"], headers=HEADERS).status_code == 404
    assert app.state.launch.campaign()["campaign"]["allocated"] == 0
    with app.state.account_security.transaction() as tx:
        rows = tx.find("demo_requests")
        assert len(rows) == 1 and rows[0]["email"] == "analyst@example.test"
        assert rows[0]["status"] == "new" and rows[0]["revision"] == 1
        assert "127.0.0.1" not in str(rows)


def test_durable_demo_limits_survive_concurrent_workers_and_restart(launch_api):
    _, app, _ = launch_api

    def submit(store, i):
        try:
            return store.submit_demo(DemoInput(**demo(email=f"person{i}@example.test")), "same-visitor")["received"]
        except HTTPException as error:
            assert error.status_code == 429 and error.headers["Retry-After"] == "3600"
            return False

    assert sum(parallel_stores(app, submit)) == 5
    fresh = LaunchStore(app.state.account_security, identity_secret="launch-test-session", clock=app.state.launch.clock)
    with pytest.raises(HTTPException) as limited:
        fresh.submit_demo(DemoInput(**demo(email="another@example.test")), "same-visitor")
    assert limited.value.status_code == 429
    # A separate caller remains usable; email-based limits still span different callers.
    for i in range(3):
        fresh.submit_demo(DemoInput(**demo(email="same-person@example.test")), f"other-visitor-{i}")
    with pytest.raises(HTTPException) as limited:
        fresh.submit_demo(DemoInput(**demo(email="SAME-PERSON@EXAMPLE.TEST")), "other-visitor-4")
    assert limited.value.status_code == 429


def admin_headers(token=None):
    headers = {**HEADERS, "Origin": "http://localhost:3201", "Content-Type": "application/json"}
    if token:
        headers.update({"X-Admin-Session": token, "X-Admin-CSRF": csrf_for(token)})
    return headers


def operator(client, app):
    admin = app.state.platform_admin
    with admin.transaction() as tx:
        exists = tx.get("platform_admins", "disclosure") is not None
    admin.bootstrap("disclosure", "1234", local=True, recover=exists)
    token = client.post(
        "/platform-admin/login", headers=admin_headers(), json={"username": "disclosure", "password": "1234"}
    ).json()["token"]
    assert client.get("/platform-admin/demo-requests", headers=admin_headers(token)).status_code == 403
    changed = client.post(
        "/platform-admin/password",
        headers=admin_headers(token),
        json={"current_password": "1234", "new_password": STRONG},
    )
    return changed.json()["token"]


def test_demo_management_requires_operator_review_csrf_fresh_auth_and_revision(launch_api):
    client, app, _ = launch_api
    lead = client.post("/demo-requests", headers=HEADERS, json=demo(organisation="Example Research")).json()[
        "reference"
    ]
    tenant = signed(app, new_user(app))
    assert client.get("/platform-admin/demo-requests", headers=tenant).status_code == 401
    token = operator(client, app)
    listing = client.get("/platform-admin/demo-requests?status=new&q=Example", headers=admin_headers(token))
    assert listing.status_code == 200 and listing.json()["total"] == 1
    assert "caller_hash" not in listing.text and "content_hash" not in listing.text
    assert listing.headers["cache-control"] == "private, no-store"
    assert client.get("/platform-admin/demo-requests?status=invalid", headers=admin_headers(token)).status_code == 422
    path = f"/platform-admin/demo-requests/{lead}/status"
    payload = {
        "status": "contacted",
        "expected_revision": 1,
        "reason": "Contacted after reviewing the enquiry",
        "confirmation": f"demo.status:{lead}",
    }
    assert client.post(path, headers=admin_headers(token), json={**payload, "confirmation": "wrong"}).status_code == 422
    assert client.post(path, headers=admin_headers(token), json={**payload, "reason": "x"}).status_code == 422
    assert client.post(path, headers={**admin_headers(token), "X-Admin-CSRF": "wrong"}, json=payload).status_code == 403
    assert (
        client.post(path, headers={**admin_headers(token), "Origin": "http://evil.test"}, json=payload).status_code
        == 403
    )
    changed = client.post(path, headers=admin_headers(token), json=payload)
    assert changed.status_code == 200 and changed.json()["request"]["status"] == "contacted"
    assert changed.json()["request"]["revision"] == 2
    assert client.post(path, headers=admin_headers(token), json=payload).status_code == 409
    assert client.get("/platform-admin/demo-requests?status=new", headers=admin_headers(token)).json()["total"] == 0
    for revision, status in ((2, "scheduled"), (3, "completed")):
        assert (
            client.post(
                path, headers=admin_headers(token), json={**payload, "expected_revision": revision, "status": status}
            ).status_code
            == 200
        )
    with app.state.platform_admin.transaction() as tx:
        rows = tx.find("platform_admin_audit", action="demo.status", target_id=lead)
        assert len(rows) == 3 and all("email" not in row["metadata"] for row in rows)
        session = tx.get("platform_admin_sessions", token.split(".")[0])
        tx.put("platform_admin_sessions", {**session, "reauthenticated_at": 0})
    assert client.post(path, headers=admin_headers(token), json={**payload, "expected_revision": 4}).status_code == 403


def test_auth_email_carries_context_across_devices_without_allocating(launch_api):
    client, app, _ = launch_api
    for endpoint, extra in (
        ("magic-link", {}),
        (
            "signup",
            {
                "first_name": "Alex",
                "last_name": "Analyst",
                "company": "Independent",
                "phone": "0123456789",
                "title": "Analyst",
                "accept_terms": True,
            },
        ),
    ):
        payload = {"email": f"{endpoint}@example.test", "next": "/early-access", "region": "ROW", **extra}
        result = client.post(f"/auth/{endpoint}", headers=HEADERS, json=payload)
        assert result.status_code == 200, result.text
        query = parse_qs(urlsplit(result.json()["dev_link"]).query)
        assert query["next"] == ["/early-access"] and query["region"] == ["ROW"]
        assert client.post("/auth/verify", headers=HEADERS, json={"token": query["token"][0]}).status_code == 200
        assert app.state.launch.campaign()["campaign"]["allocated"] == 0
        for destination in (
            "https://evil.test",
            "//evil.test",
            "/api/account",
            "/auth/callback",
            "/research/../api/logout",
            "/%2fexample.test",
            "/%5cevil.test",
            "/\n/evil.test",
        ):
            bad = client.post(f"/auth/{endpoint}", headers=HEADERS, json={**payload, "next": destination})
            assert bad.status_code == 422, (destination, bad.text)
        assert (
            client.post(f"/auth/{endpoint}", headers=HEADERS, json={**payload, "region": "invalid"}).status_code == 422
        )


@pytest.mark.parametrize(
    "value",
    ["//evil.test", "/%252fexample.test", "/a/../auth/callback", "/api", "/AUTH/callback", "/a\\b", "/\x00", 3, {}],
)
def test_return_context_rejects_external_and_unsafe_paths(value):
    with pytest.raises(ValueError):
        accounts.auth_return_context(value)


def test_campaign_roster_is_operator_only_bounded_and_read_only(launch_api):
    client, app, _ = launch_api
    user = new_user(app)
    user.first_name, user.last_name = "Founding", "Analyst"
    app.state.users.update_user(user)
    app.state.launch.reserve(user.id, reserve("UK"))
    app.state.launch.reserve(new_user(app).id, reserve("ROW"))
    endpoint = "/platform-admin/launch-memberships"
    assert client.get(endpoint, headers=signed(app, user)).status_code == 401
    token = operator(client, app)
    result = client.get(endpoint + "?limit=1", headers=admin_headers(token))
    assert result.status_code == 200 and result.json()["total"] == 2
    assert result.headers["cache-control"] == "private, no-store"
    rows = result.json()["items"]
    assert len(rows) == 1 and rows[0]["name"] == "Founding Analyst" and rows[0]["region"] == "UK"
    assert result.json()["campaign"]["allocated"] == 2
    assert client.get(endpoint + "?q=Founding&status=reserved", headers=admin_headers(token)).json()["total"] == 1
    assert client.get(endpoint + "?status=waitlisted", headers=admin_headers(token)).json()["total"] == 0
    assert client.get(endpoint + "?status=new", headers=admin_headers(token)).status_code == 422
    assert client.get(endpoint + "?limit=101", headers=admin_headers(token)).status_code == 422
    assert client.get(endpoint + "?offset=-1", headers=admin_headers(token)).status_code == 422
    assert client.post(endpoint, headers=admin_headers(token), json={"status": "reserved"}).status_code == 405


def test_return_context_keeps_safe_queries_and_omitted_legacy_link():
    assert accounts.auth_return_context() == {}
    assert accounts.auth_return_context(region="UK") == {"next": "/", "region": "UK"}
    assert accounts.auth_return_context("/research?q=AAPL", "EU") == {"next": "/research?q=AAPL", "region": "EU"}
