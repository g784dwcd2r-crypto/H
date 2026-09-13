"""Operator separation, durable revocation, reviewed writes, rollback and production credential gates."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from time import time_ns

import pytest
from fastapi.testclient import TestClient

from filings_hub import accounts, projects, tenancy
from filings_hub.api.app import create_app
from filings_hub.config import Settings
from filings_hub.platform_admin import AdminStore, csrf_for, password_matches, validate_configuration

STRONG = "A unique! operator phrase 867"
OTHER = "Another private phrase! 9753"


@pytest.fixture(params=["lake", "postgres"])
def admin_api(request, tmp_path, db):
    url = request.getfixturevalue("pg_url") if request.param == "postgres" else ""
    settings = Settings(
        lake_root=str(tmp_path),
        database_url=url,
        api_key="test-key",
        session_secret="test-session",
        platform_admin_enabled=True,
        platform_admin_environment="development",
        platform_admin_origin="http://localhost:3201",
        platform_admin_local_bootstrap=True,
        auth_dev_links=True,
        admin_emails="legacy-ops@example.test",
        api_rate_limit_per_minute=10000,
    )
    app = create_app(settings, db=db)
    admin = app.state.platform_admin
    # The disposable Postgres fixture is shared by cases, so explicit recovery resets the one local operator.
    with admin.transaction() as tx:
        exists = tx.get("platform_admins", "disclosure") is not None
    admin.bootstrap("disclosure", "1234", local=True, recover=exists)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        yield client, app, settings
    if url:
        app.state.users.conn.close()


def headers(token=None):
    out = {"X-API-Key": "test-key", "Origin": "http://localhost:3201", "Content-Type": "application/json"}
    if token:
        out.update({"X-Admin-Session": token, "X-Admin-CSRF": csrf_for(token)})
    return out


def changed_admin(client):
    signed = client.post(
        "/platform-admin/login", headers=headers(), json={"username": "disclosure", "password": "1234"}
    )
    assert signed.status_code == 200, signed.text
    initial = signed.json()["token"]
    changed = client.post(
        "/platform-admin/password", headers=headers(initial), json={"current_password": "1234", "new_password": STRONG}
    )
    assert changed.status_code == 200, changed.text
    return initial, changed.json()["token"]


def new_user(app, label):
    return app.state.users.create_user(f"admin-{label}-{time_ns()}@example.test")


def review(action, target, **values):
    return {"reason": "Verified operational request", "confirmation": f"{action}:{target}", **values}


def test_bootstrap_requires_password_change_rotates_and_revokes(admin_api):
    client, app, settings = admin_api
    signed = client.post(
        "/platform-admin/login", headers=headers(), json={"username": "disclosure", "password": "1234"}
    )
    assert signed.status_code == 200
    initial = signed.json()["token"]
    assert signed.json()["must_change_password"]
    for route in ["overview", "users", "organizations", "audit", "configuration", "research", "sources", "jobs"]:
        assert client.get("/platform-admin/" + route, headers=headers(initial)).status_code == 403
    assert (
        client.post(
            "/platform-admin/password",
            headers=headers(initial),
            json={"current_password": "1234", "new_password": "weak"},
        ).status_code
        == 422
    )
    changed = client.post(
        "/platform-admin/password", headers=headers(initial), json={"current_password": "1234", "new_password": STRONG}
    )
    token = changed.json()["token"]
    assert token != initial and not changed.json()["must_change_password"]
    assert client.get("/platform-admin/session", headers=headers(initial)).status_code == 401
    assert client.get("/platform-admin/overview", headers=headers(token)).status_code == 200
    fresh = AdminStore(app.state.account_security, settings)
    assert fresh.me(token)["username"] == "disclosure"
    with fresh.transaction() as tx:
        operator = tx.get("platform_admins", "disclosure")
        session = tx.get("platform_admin_sessions", token.split(".")[0])
        assert operator["password_hash"].startswith("scrypt-v1$")
        assert password_matches(STRONG, operator["password_hash"]) and not password_matches(
            "1234", operator["password_hash"]
        )
        assert token not in str(session) and STRONG not in str(operator)
    assert client.post("/platform-admin/logout", headers=headers(token), json={}).json() == {"revoked": True}
    assert client.get("/platform-admin/session", headers=headers(token)).status_code == 401
    assert client.get("/companies", headers={"X-API-Key": "test-key"}).status_code != 401


def test_user_tenant_admin_allowlisted_email_and_forged_id_never_become_superadmin(admin_api):
    client, app, _ = admin_api
    user = new_user(app, "ordinary")
    app.state.account_security.create_organization(user.id, "Owner is not operator")
    normal = app.state.signer.sign(user.id)
    for forged in [normal, "disclosure", "admin." + "x" * 64, "v2.disclosure.1234"]:
        h = {**headers(forged), "X-Session": normal, "X-User-ID": "disclosure", "X-Role": "superadmin"}
        assert client.get("/platform-admin/users", headers=h).status_code == 401
    _, token = changed_admin(client)
    assert (
        client.get(
            "/platform-admin/users", headers=headers(token[:-1] + ("a" if token[-1] != "a" else "b"))
        ).status_code
        == 401
    )
    assert client.get("/platform-admin/users", headers={"X-Admin-Session": token}).status_code == 401
    assert client.get("/me", headers={**headers(), "X-Session": normal}).json()["user"]["is_admin"] is False
    assert client.get("/me", headers=headers(token)).status_code == 401
    legacy = app.state.users.create_user("legacy-ops@example.test")
    legacy_token = app.state.signer.sign(legacy.id)
    assert client.get("/me", headers={**headers(), "X-Session": legacy_token}).json()["user"]["is_admin"] is True
    assert client.get("/platform-admin/users", headers={**headers(), "X-Session": legacy_token}).status_code == 401


def test_origin_csrf_reauthentication_and_review_are_required(admin_api):
    client, app, _ = admin_api
    _, token = changed_admin(client)
    user = new_user(app, "review")
    payload = review("account.status", user.id, status="suspended", expected_revision=1)
    for changed in [{"Origin": "https://attacker.test"}, {"Origin": ""}, {"X-Admin-CSRF": "forged"}]:
        assert (
            client.post(
                f"/platform-admin/users/{user.id}/status", headers={**headers(token), **changed}, json=payload
            ).status_code
            == 403
        )
    assert (
        client.post(
            f"/platform-admin/users/{user.id}/status",
            headers=headers(token),
            json={**payload, "confirmation": "wrong-target"},
        ).status_code
        == 422
    )
    app.state.platform_admin.clock = lambda: __import__("time").time() + 301
    assert (
        client.post(f"/platform-admin/users/{user.id}/status", headers=headers(token), json=payload).status_code == 403
    )
    authenticated = client.post("/platform-admin/reauthenticate", headers=headers(token), json={"password": STRONG})
    assert authenticated.status_code == 200
    replacement = authenticated.json()["token"]
    assert client.get("/platform-admin/session", headers=headers(token)).status_code == 401
    assert (
        client.post(f"/platform-admin/users/{user.id}/status", headers=headers(replacement), json=payload).status_code
        == 200
    )


def test_suspension_and_session_revocation_have_effect_and_atomic_audit(admin_api):
    client, app, _ = admin_api
    _, token = changed_admin(client)
    user = new_user(app, "suspend")
    first, second = app.state.signer.sign(user.id), app.state.signer.sign(user.id)
    body = review("account.status", user.id, status="suspended", expected_revision=1)
    response = client.post(f"/platform-admin/users/{user.id}/status", headers=headers(token), json=body)
    assert response.status_code == 200 and response.json()["sessions_revoked"] == 2
    assert app.state.signer.verify(first) is None and app.state.signer.verify(second) is None
    with pytest.raises(tenancy.SecurityError) as blocked:
        app.state.signer.sign(user.id)
    assert blocked.value.status == 403
    assert client.post(f"/platform-admin/users/{user.id}/status", headers=headers(token), json=body).status_code == 409
    resumed = review("account.status", user.id, status="active", expected_revision=2)
    assert (
        client.post(f"/platform-admin/users/{user.id}/status", headers=headers(token), json=resumed).status_code == 200
    )
    assert app.state.signer.verify(first) is None
    third = app.state.signer.sign(user.id)
    revoke = review("sessions.revoke", user.id, expected_revision=3)
    assert (
        client.post(f"/platform-admin/users/{user.id}/revoke-sessions", headers=headers(token), json=revoke).json()[
            "sessions_revoked"
        ]
        == 1
    )
    assert app.state.signer.verify(third) is None
    audit = client.get("/platform-admin/audit", headers=headers(token), params={"q": user.id}).json()["items"]
    assert len(audit) == 3 and all(row["metadata"]["reason"] == "Verified operational request" for row in audit)
    assert first not in str(audit) and STRONG not in str(audit)


def test_membership_changes_preserve_last_owner_and_tenant_isolation(admin_api):
    client, app, _ = admin_api
    _, token = changed_admin(client)
    owner, member = new_user(app, "org-owner"), new_user(app, "org-member")
    org = app.state.account_security.create_organization(owner.id, "Operational role test")["id"]
    detail = client.get(f"/platform-admin/organizations/{org}", headers=headers(token)).json()
    current = detail["members"][0]
    removal = review("membership.change", f"{org}:{owner.id}", role=None, expected_version=current["version"])
    assert (
        client.post(
            f"/platform-admin/organizations/{org}/members/{owner.id}", headers=headers(token), json=removal
        ).status_code
        == 409
    )
    add = review("membership.change", f"{org}:{member.id}", role="admin", expected_version="absent")
    added = client.post(f"/platform-admin/organizations/{org}/members/{member.id}", headers=headers(token), json=add)
    assert added.status_code == 200
    normal = app.state.signer.sign(member.id)
    assert client.get(f"/organizations/{org}", headers={**headers(), "X-Session": normal}).status_code == 200
    assert client.get("/platform-admin/organizations", headers={**headers(), "X-Session": normal}).status_code == 401
    remove = review("membership.change", f"{org}:{member.id}", role=None, expected_version=added.json()["version"])
    assert (
        client.post(
            f"/platform-admin/organizations/{org}/members/{member.id}", headers=headers(token), json=remove
        ).status_code
        == 200
    )
    assert client.get(f"/organizations/{org}", headers={**headers(), "X-Session": normal}).status_code == 404


def test_pagination_private_content_and_honest_health(admin_api):
    client, app, _ = admin_api
    _, token = changed_admin(client)
    marker = "page" + str(time_ns())
    users = [new_user(app, marker) for _ in range(3)]
    project_store = projects.ProjectStore(app.state.account_security)
    project = project_store.create(users[0].id, {"name": "PRIVATE_PROJECT_NAME"})
    project_store.create_note(project["id"], users[0].id, {"title": "PRIVATE_NOTE_TITLE", "body": "PRIVATE_NOTE_BODY"})
    first = client.get("/platform-admin/users", headers=headers(token), params={"q": marker, "limit": 2}).json()
    second = client.get(
        "/platform-admin/users", headers=headers(token), params={"q": marker, "limit": 2, "offset": 2}
    ).json()
    assert first["total"] == 3 and len(first["items"]) == 2 and len(second["items"]) == 1
    detail = client.get(f"/platform-admin/users/{users[0].id}", headers=headers(token)).json()
    assert "PRIVATE_" not in str(detail)
    health = client.get("/platform-admin/research", headers=headers(token)).json()
    assert health["state"] == "available" and health["coverage"]["partial"]
    assert client.get("/platform-admin/jobs", headers=headers(token)).json()["state"] == "unavailable"
    sources = client.get("/platform-admin/sources", headers=headers(token)).json()
    assert not sources["editable"] and any(row["status"] == "provider_required" for row in sources["sources"])


def test_config_controls_real_registration_and_conflicting_saves(admin_api):
    client, app, _ = admin_api
    _, token = changed_admin(client)
    existing = new_user(app, "existing")
    current = client.get("/platform-admin/configuration", headers=headers(token)).json()["configuration"]
    payload = review(
        "configuration.change", "registration", new_registration_enabled=False, expected_revision=current["revision"]
    )
    assert client.post("/platform-admin/configuration", headers=headers(token), json=payload).status_code == 200
    with pytest.raises(tenancy.SecurityError) as denied:
        new_user(app, "blocked-registration")
    assert denied.value.status == 403
    assert accounts.get_or_create_user(app.state.users, existing.email).id == existing.id
    assert client.get("/auth/config", headers=headers()).json()["new_registration_enabled"] is False
    assert (
        client.post(
            "/auth/magic-link", headers=headers(), json={"email": f"paused-{time_ns()}@example.test"}
        ).status_code
        == 403
    )
    assert client.post("/auth/magic-link", headers=headers(), json={"email": existing.email}).status_code == 200
    assert client.post("/platform-admin/configuration", headers=headers(token), json=payload).status_code == 409
    enabled = {**payload, "new_registration_enabled": True, "expected_revision": current["revision"] + 1}
    assert client.post("/platform-admin/configuration", headers=headers(token), json=enabled).status_code == 200
    assert new_user(app, "resumed-registration").id


def test_durable_backoff_expiry_and_recovery(admin_api):
    client, app, settings = admin_api
    clock = [__import__("time").time()]
    app.state.platform_admin.clock = lambda: clock[0]
    for _ in range(5):
        assert (
            client.post(
                "/platform-admin/login", headers=headers(), json={"username": "disclosure", "password": "wrong"}
            ).status_code
            == 401
        )
    reopened = AdminStore(app.state.account_security, settings, clock=lambda: clock[0])
    with pytest.raises(tenancy.SecurityError) as locked:
        reopened.login("disclosure", "1234", peer="127.0.0.1")
    assert locked.value.status == 429
    clock[0] += 61
    signed = reopened.login("disclosure", "1234", peer="127.0.0.1")
    assert signed["must_change_password"]
    reopened.bootstrap("disclosure", OTHER, recover=True)
    with pytest.raises(tenancy.SecurityError):
        reopened.me(signed["token"])
    newer = reopened.login("disclosure", OTHER, peer="127.0.0.1")
    clock[0] += 31 * 60
    with pytest.raises(tenancy.SecurityError) as expired:
        reopened.me(newer["token"])
    assert expired.value.status == 401


def test_concurrent_account_updates_have_one_winner(admin_api):
    client, app, settings = admin_api
    _, token = changed_admin(client)
    user = new_user(app, "concurrent")
    other = AdminStore(app.state.account_security, settings)
    barrier = Barrier(2)
    payload = review("account.status", user.id, status="suspended", expected_revision=1)

    def save(store):
        barrier.wait(timeout=10)
        try:
            return store.user_action(token, user.id, payload)
        except tenancy.SecurityError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, [app.state.platform_admin, other]))
    assert results.count(409) == 1
    events = app.state.admin_operations.audit(token, q=user.id)["items"]
    assert len(events) == 1


def test_production_and_local_bootstrap_configuration_fail_closed():
    production = Settings(
        platform_admin_enabled=True,
        platform_admin_origin="https://admin.example.test",
        platform_admin_environment="production",
        api_key="k" * 40,
        database_url="postgresql://operator@localhost/platform",
    )
    validate_configuration(production)
    for changes in [
        {"platform_admin_local_bootstrap": True},
        {"platform_admin_origin": "http://admin.example.test"},
        {"api_key": "weak"},
        {"database_url": ""},
        {"platform_admin_environment": "development"},
        {"platform_admin_origin": "https://admin.example.test/"},
    ]:
        with pytest.raises(ValueError):
            validate_configuration(production.model_copy(update=changes))


def test_privileged_write_failure_rolls_back_status_sessions_and_audit(admin_api, monkeypatch):
    client, app, _ = admin_api
    _, token = changed_admin(client)
    user = new_user(app, "rollback")
    normal = app.state.signer.sign(user.id)

    def fail(*_args, **_kwargs):
        raise RuntimeError("simulated audit write failure")

    monkeypatch.setattr(app.state.platform_admin, "audit", fail)
    with pytest.raises(RuntimeError, match="simulated audit write failure"):
        app.state.platform_admin.user_action(
            token, user.id, review("account.status", user.id, status="suspended", expected_revision=1)
        )
    assert app.state.signer.verify(normal) == user.id
    assert app.state.admin_operations.user(token, user.id)["user"]["status"] == "active"
    assert app.state.admin_operations.audit(token, q=user.id)["items"] == []


def test_bootstrap_credentials_cannot_migrate_into_production(admin_api):
    _, app, settings = admin_api
    production = settings.model_copy(
        update={
            "platform_admin_environment": "production",
            "platform_admin_local_bootstrap": False,
            "platform_admin_origin": "https://admin.example.test",
            "api_key": "k" * 40,
            "database_url": "postgresql://operator@localhost/platform",
        }
    )
    store = AdminStore(app.state.account_security, production)
    with pytest.raises(tenancy.SecurityError) as denied:
        store.login("disclosure", "1234", peer="127.0.0.1")
    assert denied.value.status == 403
    with pytest.raises(tenancy.SecurityError):
        store.bootstrap("disclosure", "1234", recover=True)


def test_concurrent_owner_removal_cannot_leave_ownerless_organization(admin_api):
    client, app, _ = admin_api
    _, token = changed_admin(client)
    first, second = new_user(app, "first-owner"), new_user(app, "second-owner")
    org = app.state.account_security.create_organization(first.id, "Concurrent ownership")["id"]
    app.state.account_security.change_member(org, first.id, second.id, "owner")
    members = app.state.admin_operations.organization(token, org)["members"]
    barrier = Barrier(2)

    def remove(member):
        barrier.wait(timeout=10)
        try:
            return app.state.platform_admin.member_action(
                token,
                org,
                member["user_id"],
                review("membership.change", member["id"], role=None, expected_version=member["version"]),
            )
        except tenancy.SecurityError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(remove, members))
    assert results.count(409) == 1
    assert len(app.state.admin_operations.organization(token, org)["members"]) == 1


def test_job_adapter_filters_worker_secrets_and_audits_confirmed_actions(admin_api, monkeypatch):
    client, app, _ = admin_api
    _, token = changed_admin(client)
    job = {
        "id": "a" * 32,
        "status": "paused",
        "revision": 1,
        "kind": "index",
        "token": "PRIVATE_WORKER_TOKEN",
        "idempotency_key": "PRIVATE_OPERATION_KEY",
    }

    class Engine:
        def list(self, **_):
            return {"jobs": [dict(job)], "total": 1}

        def health(self):
            return {"jobs": {job["status"]: 1}, "scheduler_active": False}

        def retry(self, ident, expected):
            assert ident == job["id"] and expected == job["revision"]
            job.update(status="queued", revision=2)
            return dict(job)

    @contextmanager
    def engine():
        yield Engine()

    monkeypatch.setattr(app.state.admin_operations, "job_engine", engine)
    listed = client.get("/platform-admin/jobs", headers=headers(token)).json()
    assert listed["state"] == "available" and "PRIVATE_" not in str(listed)
    payload = review("job.retry", job["id"], expected_revision=1)
    result = client.post(f"/platform-admin/jobs/{job['id']}/retry", headers=headers(token), json=payload)
    assert result.status_code == 200 and result.json()["job"]["revision"] == 2
    assert "PRIVATE_" not in str(result.json())
    audit = app.state.admin_operations.audit(token, q=job["id"])["items"]
    assert {row["action"] for row in audit} >= {"job.retry.requested", "job.retry.confirmed"}


def test_job_result_audit_failure_remains_visible_without_replaying_mutation(admin_api, monkeypatch):
    client, app, _ = admin_api
    _, token = changed_admin(client)
    job = {"id": "b" * 32, "revision": 1, "status": "running"}
    attempts = []

    class Engine:
        def list(self, **_):
            return {"jobs": [dict(job)], "total": 1}

        def health(self):
            return {"scheduler_active": False}

        def cancel(self, ident, expected):
            attempts.append((ident, expected))
            job.update(status="cancelled", revision=2)
            return dict(job)

    @contextmanager
    def engine():
        yield Engine()

    monkeypatch.setattr(app.state.admin_operations, "job_engine", engine)
    original_audit = app.state.platform_admin.audit

    def failing_audit(tx, actor, action, target, **metadata):
        if action == "job.cancel.confirmed":
            raise RuntimeError("simulated completion audit failure")
        return original_audit(tx, actor, action, target, **metadata)

    monkeypatch.setattr(app.state.platform_admin, "audit", failing_audit)
    payload = review("job.cancel", job["id"], expected_revision=1)
    response = client.post(f"/platform-admin/jobs/{job['id']}/cancel", headers=headers(token), json=payload)
    assert response.status_code == 503 and len(attempts) == 1
    listed = app.state.admin_operations.jobs(token)
    assert listed["jobs"][0]["status"] == "cancelled"
    assert any(row["job_id"] == job["id"] and row["status"] == "pending" for row in listed["unresolved_commands"])
    audit = app.state.admin_operations.audit(token, q=job["id"])["items"]
    assert any(row["action"] == "job.cancel.requested" for row in audit)
    assert not any(row["action"] == "job.cancel.confirmed" for row in audit)
