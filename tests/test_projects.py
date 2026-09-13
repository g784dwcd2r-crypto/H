"""Project isolation, membership revocation, reference honesty and optimistic concurrency."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from time import time_ns

import pytest
from fastapi.testclient import TestClient

from filings_hub import accounts, projects, tenancy
from filings_hub.api.app import create_app
from filings_hub.config import Settings
from filings_hub.lake.storage import Storage
from filings_hub.project_templates import templates
from filings_hub.research_index import open_index


@pytest.fixture(params=["lake", "postgres"])
def backend(request, tmp_path):
    url = request.getfixturevalue("pg_url") if request.param == "postgres" else ""
    storage = Storage(str(tmp_path))
    users = accounts.store_from_settings(storage, url)
    security = tenancy.SecurityStore(users, storage, url)
    yield users, security, projects.ProjectStore(security), url, storage
    if url:
        users.conn.close()


def user(users, label):
    return users.create_user(f"project-{label}-{time_ns()}@example.test")


def test_personal_project_crud_revision_conflicts_and_audit(backend):
    users, security, store, url, storage = backend
    owner, outsider = user(users, "owner"), user(users, "outside")
    project = store.create(owner.id, {"name": "Earnings review", "description": "Original thesis"})
    pid = project["id"]
    assert project["can_manage"] and project["revision"] == 1 and project["organization_id"] is None
    assert store.list(outsider.id) == []
    for action in [
        lambda: store.get(pid, outsider.id),
        lambda: store.notes(pid, outsider.id),
        lambda: store.export(pid, outsider.id),
        lambda: store.update(pid, outsider.id, {"expected_revision": 1, "name": "Stolen"}),
        lambda: store.delete(pid, outsider.id, 1),
    ]:
        with pytest.raises(tenancy.SecurityError) as denied:
            action()
        assert denied.value.status == 404
    updated = store.update(pid, owner.id, {"expected_revision": 1, "description": "Revised thesis"})
    assert updated["revision"] == 2
    with pytest.raises(tenancy.SecurityError) as stale:
        store.update(pid, owner.id, {"expected_revision": 1, "name": "Stale title"})
    assert stale.value.status == 409
    assert store.get(pid, owner.id)["name"] == "Earnings review"
    note = store.create_note(pid, owner.id, {"title": "Investment thesis", "body": "User reasoning", "kind": "thesis"})
    assert note["authorship"] == "user" and note["revision"] == 1 and note["project_revision"] == 3
    with pytest.raises(tenancy.SecurityError) as stale_delete:
        store.delete(pid, owner.id, 2)
    assert stale_delete.value.status == 409  # New unseen note protects project from stale deletion.
    refreshed = projects.ProjectStore(tenancy.SecurityStore(users, storage, url))
    assert refreshed.note(pid, note["id"], owner.id)["body"] == "User reasoning"
    edited = store.update_note(pid, note["id"], owner.id, {"expected_revision": 1, "body": "New reasoning"})
    assert edited["revision"] == 2 and edited["project_revision"] == 4
    with pytest.raises(tenancy.SecurityError) as conflict:
        store.update_note(pid, note["id"], owner.id, {"expected_revision": 1, "body": "Lost update"})
    assert conflict.value.status == 409
    assert store.note(pid, note["id"], owner.id)["body"] == "New reasoning"
    assert store.delete_note(pid, note["id"], owner.id, 2)["deleted"] is True
    assert store.notes(pid, owner.id) == []
    assert store.delete(pid, owner.id, store.get(pid, owner.id)["revision"]) == {"deleted": True}
    assert store.list(owner.id) == []
    audit = security.audit_records(owner.id)
    assert {row["action"] for row in audit} == {
        "project.created",
        "project.updated",
        "note.created",
        "note.updated",
        "note.deleted",
        "project.deleted",
    }
    assert all("reasoning" not in str(row) and "thesis" not in str(row) for row in audit)


def test_organization_scope_is_fixed_and_removed_members_lose_every_path(backend):
    users, security, store, _, _ = backend
    owner, member, outside = [user(users, label) for label in ("owner", "member", "outside")]
    org = security.create_organization(owner.id, "Fund team")["id"]
    other_org = security.create_organization(outside.id, "Other fund")["id"]
    security.change_member(org, owner.id, member.id, "member")
    project = store.create(member.id, {"name": "Coverage", "organization_id": org})
    pid = project["id"]
    assert not project["can_manage"] and store.get(pid, owner.id)["can_manage"]
    note = store.create_note(pid, member.id, {"title": "Initial view", "body": "My thesis"})
    personal = store.create(member.id, {"name": "Private work"})
    with pytest.raises(tenancy.SecurityError) as cannot_move:
        store.update(pid, owner.id, {"expected_revision": 2, "organization_id": other_org})
    assert cannot_move.value.status == 422
    for action in [lambda: store.delete(pid, member.id, 2), lambda: store.delete_note(pid, note["id"], member.id, 1)]:
        with pytest.raises(tenancy.SecurityError) as cannot_delete:
            action()
        assert cannot_delete.value.status == 403
    edited = store.update_note(pid, note["id"], owner.id, {"expected_revision": 1, "body": "Peer review"})
    assert edited["created_by"] == member.id and edited["updated_by"] == owner.id
    security.change_member(org, owner.id, member.id, action="remove")
    assert [p["id"] for p in store.list(member.id)] == [personal["id"]]
    for actor in [member.id, outside.id]:
        for action in [
            lambda actor=actor: store.get(pid, actor),
            lambda actor=actor: store.notes(pid, actor),
            lambda actor=actor: store.export(pid, actor),
            lambda actor=actor: store.note(pid, note["id"], actor),
            lambda actor=actor: store.create_note(pid, actor, {"title": "Forbidden"}),
            lambda actor=actor: store.update_note(
                pid, note["id"], actor, {"expected_revision": 2, "body": "Forbidden"}
            ),
            lambda actor=actor: store.delete_note(pid, note["id"], actor, 2),
            lambda actor=actor: store.delete(pid, actor, 3),
        ]:
            with pytest.raises(tenancy.SecurityError) as denied:
                action()
            assert denied.value.status == 404
    assert store.note(pid, note["id"], owner.id)["body"] == "Peer review"
    assert store.delete(pid, owner.id, store.get(pid, owner.id)["revision"])["deleted"]


def test_note_id_cannot_be_used_through_another_project(backend):
    users, _, store, _, _ = backend
    owner, other = user(users, "a"), user(users, "b")
    first = store.create(owner.id, {"name": "A"})["id"]
    second = store.create(other.id, {"name": "B"})["id"]
    note = store.create_note(first, owner.id, {"title": "Secret", "body": "Private"})
    for action in [
        lambda: store.note(second, note["id"], other.id),
        lambda: store.update_note(second, note["id"], other.id, {"expected_revision": 1, "body": "Overwrite"}),
        lambda: store.delete_note(second, note["id"], other.id, 1),
    ]:
        with pytest.raises(tenancy.SecurityError) as denied:
            action()
        assert denied.value.status == 404


def test_source_references_resolve_versions_without_caching_verified_text(backend):
    users, security, store, url, storage = backend
    owner = user(users, "sources")
    pid = store.create(owner.id, {"name": "Source checks"})["id"]
    index = open_index(storage, url)
    try:
        accession = "0000320193-24-000123"
        # Filename varies so independently parameterized tests do not share a restricted document.
        document_id = index.register_document(
            {"cik": 320193, "accession": accession, "form": "10-K", "filed_date": "2024-11-01"},
            {"filename": f"report-{time_ns()}.htm", "label": "Annual report"},
        )
        version = index.add_version(storage, document_id, b"original source bytes", "Revenue was 100.")
        reference = {"kind": "document", "document_id": document_id, "version_id": version}
        financial = {"kind": "financial_snapshot", "issuer_id": "sec:0000320193", "snapshot_id": "sha256:" + "a" * 64}
        note = store.create_note(
            pid, owner.id, {"title": "Evidence", "body": "My interpretation", "citations": [reference, financial]}
        )
        assert note["citations"][0]["status"] == "available"
        assert note["citations"][1]["status"] == "unresolved"
        assert "text_content" not in str(note) and "Revenue was 100" not in str(note)
        exported = store.export(pid, owner.id)
        assert exported["notes"][0]["citations"][0]["status"] == "available"
        assert "original source bytes" not in str(exported) and "Revenue was 100" not in str(exported)
        # A subsequent source restriction must affect already-saved notes, even at immutable IDs.
        index.execute("UPDATE research_documents SET visibility='organization' WHERE document_id=?", [document_id])
        later = store.note(pid, note["id"], owner.id)
        assert later["citations"][0]["status"] == "unavailable"
        assert "source_url" not in later["citations"][0]
        assert later["body"] == "My interpretation" and later["authorship"] == "user"
        restricted_export = store.export(pid, owner.id)
        assert restricted_export["notes"][0]["citations"][0]["status"] == "unavailable"
        assert "source_url" not in restricted_export["notes"][0]["citations"][0]
        assert restricted_export["notes"][0]["citations"][1]["status"] == "unresolved"
        with security.transaction() as tx:
            stored = tx.get("notes", note["id"])
            assert stored["citations"] == [reference, financial]
        for bad in [
            {**reference, "text": "Claimed source text"},
            {**reference, "verified": True},
            {**reference, "version_id": "latest"},
            {**financial, "issuer_id": "sec:0000000000"},
        ]:
            with pytest.raises(tenancy.SecurityError) as invalid:
                store.create_note(pid, owner.id, {"title": "Bad reference", "citations": [bad]})
            assert invalid.value.status == 422
    finally:
        index.close()


def test_concurrent_note_saves_preserve_one_winner_and_signal_conflict(backend):
    users, security, store, url, storage = backend
    owner = user(users, "concurrent")
    pid = store.create(owner.id, {"name": "Concurrency"})["id"]
    note = store.create_note(pid, owner.id, {"title": "Shared note", "body": "Original"})
    other = projects.ProjectStore(tenancy.SecurityStore(users, storage, url))
    barrier = Barrier(2)

    def save(item):
        instance, body = item
        barrier.wait(timeout=10)
        try:
            return instance.update_note(pid, note["id"], owner.id, {"expected_revision": 1, "body": body})
        except tenancy.SecurityError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, [(store, "First edit"), (other, "Second edit")]))
    assert results.count(409) == 1
    winner = next(result for result in results if isinstance(result, dict))
    assert store.note(pid, note["id"], owner.id)["body"] == winner["body"]
    assert store.get(pid, owner.id)["revision"] == 3
    assert sum(row["action"] == "note.updated" for row in security.audit_records(owner.id)) == 1


def test_source_outage_does_not_turn_successful_note_save_into_failed_response(backend):
    users, _, store, _, _ = backend
    owner = user(users, "outage")
    pid = store.create(owner.id, {"name": "Reference outage"})["id"]

    def unavailable(_):
        raise RuntimeError("backend unavailable")

    store.resolve_document = unavailable
    reference = {
        "kind": "document",
        "document_id": "sec:0000320193:0000320193-24-000123:report.htm",
        "version_id": "sha256:" + "f" * 64,
    }
    note = store.create_note(pid, owner.id, {"title": "Saved", "body": "User note", "citations": [reference]})
    assert note["citations"][0]["status"] == "unavailable" and len(store.notes(pid, owner.id)) == 1
    assert store.export(pid, owner.id)["notes"][0]["citations"][0]["status"] == "unavailable"


def test_project_export_is_versioned_scoped_and_omits_account_records(backend):
    users, security, store, _, _ = backend
    owner, outsider = user(users, "export-owner"), user(users, "export-outsider")
    personal = store.create(owner.id, {"name": "Portable work", "description": "Research description"})
    other = store.create(owner.id, {"name": "Separate personal project"})
    store.create_note(other["id"], owner.id, {"title": "Do not export", "body": "Unrelated private body"})
    org = security.create_organization(outsider.id, "Unrelated organization")["id"]
    foreign = store.create(outsider.id, {"name": "Other account", "organization_id": org})
    store.create_note(foreign["id"], outsider.id, {"title": "Foreign", "body": "Foreign private body"})
    note = store.create_note(personal["id"], owner.id, {"title": "My thesis", "body": "User work", "kind": "thesis"})
    saved = store.update_note(
        personal["id"], note["id"], owner.id, {"expected_revision": 1, "body": "Current user work"}
    )
    exported = store.export(personal["id"], owner.id)
    assert exported["format"] == "disclosure.research-project" and exported["schema_version"] == 1
    assert exported["scope"] == {"kind": "personal", "organization_id": None}
    assert exported["exported_at"] >= personal["created_at"]
    assert exported["source_policy"]["provider_documents_included"] is False
    assert exported["project"]["revision"] == saved["project_revision"] == 3
    assert exported["project"]["created_at"] == personal["created_at"]
    assert len(exported["notes"]) == 1 and exported["notes"][0]["revision"] == 2
    assert exported["notes"][0]["body"] == "Current user work"
    for private in [
        owner.id,
        outsider.id,
        org,
        other["id"],
        foreign["id"],
        "Unrelated private body",
        "Foreign private body",
        owner.email,
    ]:
        assert private not in str(exported)
    assert not {"owner_id", "can_manage"} & exported["project"].keys()
    assert not {"created_by", "updated_by"} & exported["notes"][0].keys()


def test_local_templates_seed_editable_prompts_with_origin_and_no_evidence(backend):
    users, security, store, _, _ = backend
    owner = user(users, "templates")
    for template in templates():
        project = store.create(owner.id, {"name": template["name"], "template_id": template["id"]})
        assert project["starter_template"] == {"id": template["id"], "version": 1}
        assert project["revision"] == 1  # Initial project and starter notes are one atomic version.
        notes = store.notes(project["id"], owner.id)
        assert len(notes) == len(template["notes"]) == 3
        assert all(
            note["authorship"] == "template" and note["revision"] == 1 and not note["citations"] for note in notes
        )
        assert all(note["body"].startswith("Research prompts") for note in notes)
        assert all(note["created_at"] == project["created_at"] for note in notes)
        exported = store.export(project["id"], owner.id)
        assert exported["project"]["starter_template"] == project["starter_template"]
        unchanged_text = store.update_note(
            project["id"], notes[0]["id"], owner.id, {"expected_revision": 1, "citations": []}
        )
        assert unchanged_text["authorship"] == "template"
        edited = store.update_note(
            project["id"], notes[0]["id"], owner.id, {"expected_revision": 2, "body": "My investigation"}
        )
        assert edited["authorship"] == "user" and edited["origin"] == notes[0]["origin"]
        assert store.get(project["id"], owner.id)["revision"] == 3
    assert any(note["kind"] == "thesis" for template in templates() for note in template["notes"])
    altered_catalog = templates()
    altered_catalog[0]["notes"][0]["body"] = "Caller injection"
    assert "Caller injection" not in str(templates())
    for bad in ["unknown-template", "", 1, [], {"id": "company-overview"}]:
        before = len(store.list(owner.id))
        with pytest.raises(tenancy.SecurityError) as invalid:
            store.create(owner.id, {"name": "Invalid", "template_id": bad})
        assert invalid.value.status == 422 and len(store.list(owner.id)) == before
    blank = store.create(owner.id, {"name": "Blank", "template_id": None})
    assert "starter_template" not in blank and store.notes(blank["id"], owner.id) == []
    assert any(event["metadata"].get("template_id") for event in security.audit_records(owner.id))


def test_template_creation_rolls_back_project_notes_and_audit_together(backend, monkeypatch):
    users, security, store, url, _ = backend
    owner = user(users, "template-rollback")
    transaction_type = tenancy.PostgresTransaction if url else tenancy.LakeTransaction
    original = transaction_type.put
    created_notes = 0
    project_id = None

    def fail_second_note(tx, kind, row):
        nonlocal created_notes, project_id
        if kind == "projects":
            project_id = row["id"]
        if kind == "notes":
            created_notes += 1
            if created_notes == 2:
                raise RuntimeError("simulated storage failure")
        return original(tx, kind, row)

    monkeypatch.setattr(transaction_type, "put", fail_second_note)
    with pytest.raises(RuntimeError, match="simulated storage failure"):
        store.create(owner.id, {"name": "Must roll back", "template_id": "company-overview"})
    assert store.list(owner.id) == [] and security.audit_records(owner.id) == []
    with security.transaction() as tx:
        assert project_id and tx.get("projects", project_id) is None
        assert tx.find("notes", project_id=project_id) == []


def test_export_keeps_note_and_project_revision_consistent_during_edits(backend):
    users, security, store, _, _ = backend
    owner = user(users, "export-concurrent")
    pid = store.create(owner.id, {"name": "Concurrent export"})["id"]
    reference = {
        "kind": "document",
        "document_id": "sec:0000320193:0000320193-24-000123:report.htm",
        "version_id": "sha256:" + "a" * 64,
    }
    store.resolve_document = lambda _: None
    note = store.create_note(pid, owner.id, {"title": "View", "body": "Before", "citations": [reference]})
    resolving, release, attempting_edit, edited = Event(), Event(), Event(), Event()

    def pause_reference(_):
        resolving.set()
        assert release.wait(timeout=10)
        return None

    exporting = projects.ProjectStore(security, resolve_document=pause_reference)

    def edit():
        attempting_edit.set()
        result = store.update_note(pid, note["id"], owner.id, {"expected_revision": 1, "body": "After"})
        edited.set()
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending_export = pool.submit(exporting.export, pid, owner.id)
        try:
            assert resolving.wait(timeout=10)
            pending_edit = pool.submit(edit)
            assert attempting_edit.wait(timeout=10)
            assert not edited.wait(timeout=0.2)
        finally:
            release.set()
        exported = pending_export.result(timeout=10)
        pending_edit.result(timeout=10)
    assert exported["project"]["revision"] == 2
    assert exported["notes"][0]["revision"] == 1 and exported["notes"][0]["body"] == "Before"
    later = store.export(pid, owner.id)
    assert later["project"]["revision"] == 3
    assert later["notes"][0]["revision"] == 2 and later["notes"][0]["body"] == "After"


@pytest.fixture(params=["lake", "postgres"])
def api(request, tmp_path, db):
    url = request.getfixturevalue("pg_url") if request.param == "postgres" else ""
    app = create_app(
        Settings(
            lake_root=str(tmp_path),
            database_url=url,
            api_key="k",
            session_secret="stable",
            api_rate_limit_per_minute=10000,
        ),
        db=db,
    )
    with TestClient(app) as client:
        yield client, app
    if url:
        app.state.users.conn.close()


def headers(app, user):
    return {"X-API-Key": "k", "X-Session": app.state.signer.sign(user.id)}


def test_projects_api_revision_and_removed_tenant_access(api):
    client, app = api
    owner, member = user(app.state.users, "api-owner"), user(app.state.users, "api-member")
    h, m = headers(app, owner), headers(app, member)
    assert client.get("/projects", headers={"X-API-Key": "k"}).status_code == 401
    org = client.post("/organizations", headers=h, json={"name": "Research"}).json()["organization"]["id"]
    client.post(f"/organizations/{org}/members", headers=h, json={"user_id": member.id})
    created = client.post("/projects", headers=h, json={"name": "Portfolio review", "organization_id": org})
    assert created.status_code == 201
    pid = created.json()["project"]["id"]
    base = f"/projects/{pid}"
    note = client.post(base + "/notes", headers=m, json={"title": "Thesis", "body": "Research", "kind": "thesis"})
    assert note.status_code == 201
    nid = note.json()["note"]["id"]
    edited = client.patch(base + f"/notes/{nid}", headers=m, json={"expected_revision": 1, "body": "Updated"})
    assert edited.status_code == 200
    assert (
        client.patch(base + f"/notes/{nid}", headers=h, json={"expected_revision": 1, "body": "Stale"}).status_code
        == 409
    )
    assert client.delete(base, headers=h, params={"expected_revision": 1}).status_code == 409
    assert client.delete(base + f"/notes/{nid}", headers=m, params={"expected_revision": 2}).status_code == 403
    client.delete(f"/organizations/{org}/members/{member.id}", headers=h)
    assert client.get("/projects", headers=m).json() == {"projects": []}
    for route in [base, base + "/notes", base + f"/notes/{nid}", base + "/export"]:
        assert client.get(route, headers=m).status_code == 404
    assert (
        client.patch(base + f"/notes/{nid}", headers=m, json={"expected_revision": 2, "body": "Forbidden"}).status_code
        == 404
    )
    assert client.post(base + "/notes", headers=m, json={"title": "Forbidden"}).status_code == 404
    assert client.get(base + f"/notes/{nid}", headers=h).json()["note"]["body"] == "Updated"
    current = client.get(base, headers=h).json()["project"]["revision"]
    assert client.delete(base, headers=h, params={"expected_revision": current}).json() == {"deleted": True}
    assert client.get(base, headers=h).status_code == 404


def test_revoked_session_cannot_use_projects(api):
    client, app = api
    owner = user(app.state.users, "revoked")
    h = headers(app, owner)
    project = client.post("/projects", headers=h, json={"name": "Private"}).json()["project"]
    assert client.post("/auth/logout", headers=h).status_code == 200
    assert client.get("/projects", headers=h).status_code == 401
    assert client.get(f"/projects/{project['id']}", headers=h).status_code == 401
    assert client.get(f"/projects/{project['id']}/export", headers=h).status_code == 401
    assert client.get("/projects/templates", headers=h).status_code == 401
    assert client.post(f"/projects/{project['id']}/notes", headers=h, json={"title": "After logout"}).status_code == 401


def test_project_templates_and_export_api_require_account_and_current_scope(api):
    client, app = api
    owner, member, outside = [
        user(app.state.users, label) for label in ("export-api-owner", "export-api-member", "export-api-outside")
    ]
    h, m, o = headers(app, owner), headers(app, member), headers(app, outside)
    assert client.get("/projects/templates", headers={"X-API-Key": "k"}).status_code == 401
    catalog = client.get("/projects/templates", headers=h)
    assert catalog.status_code == 200 and len(catalog.json()["templates"]) == 3
    org = client.post("/organizations", headers=h, json={"name": "Export team"}).json()["organization"]["id"]
    client.post(f"/organizations/{org}/members", headers=h, json={"user_id": member.id})
    created = client.post(
        "/projects", headers=m, json={"name": "Team earnings", "organization_id": org, "template_id": "earnings-review"}
    )
    assert created.status_code == 201
    project = created.json()["project"]
    route = f"/projects/{project['id']}/export"
    response = client.get(route, headers=m)
    assert response.status_code == 200 and response.headers["content-type"] == "application/json"
    assert response.headers["content-disposition"] == f'attachment; filename="disclosure-project-{project["id"]}.json"'
    assert response.headers["cache-control"] == "private, no-store"
    exported = response.json()
    assert exported["scope"] == {"kind": "organization", "organization_id": org}
    assert len(exported["notes"]) == 3 and exported["project"]["revision"] == 1
    assert client.get(route, headers=o).status_code == 404
    assert client.get(route, headers={"X-API-Key": "k"}).status_code == 401
    client.delete(f"/organizations/{org}/members/{member.id}", headers=h)
    assert client.get(route, headers=m).status_code == 404
    assert client.get(route, headers=h).status_code == 200
