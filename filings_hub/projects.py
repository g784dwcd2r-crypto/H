"""Revisioned scoped research notes, local starter prompts and portable project exports.

References are immutable IDs, never a client assertion of verified evidence. Document references
are re-resolved through the permission-filtered public SEC index; financial content hashes are
unresolved pointers because the financial endpoint does not archive its responses yet.
"""

from __future__ import annotations

import logging
import re
import uuid
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from filings_hub.platform.contracts import issuer_id, sec_document_id
from filings_hub.project_templates import find_template, templates
from filings_hub.tenancy import ROLES, SecurityError, SecurityStore, stamp

log = logging.getLogger(__name__)
HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
DOCUMENT = re.compile(r"^sec:[0-9]{10}:[0-9]{10}-[0-9]{2}-[0-9]{6}:[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")
ISSUER = re.compile(r"^sec:[0-9]{10}$")


def text_field(value: Any, name: str, maximum: int, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise SecurityError(
            422, f"{name} must be {'non-empty ' if required else ''}text of at most {maximum} characters"
        )
    return value.strip() if name != "body" else value


def revision_matches(row: dict[str, Any], expected: Any) -> None:
    if type(expected) is not int or expected < 1:
        raise SecurityError(422, "expected_revision must be a positive integer")
    if row["revision"] != expected:
        raise SecurityError(409, "this item changed; reload it before saving")


def validate_citations(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 100:
        raise SecurityError(422, "citations must be a list of at most 100 source references")
    out = []
    for citation in value:
        if not isinstance(citation, dict):
            raise SecurityError(422, "a citation must be a source reference")
        kind = citation.get("kind")
        keys = {"kind", "document_id", "version_id"} if kind == "document" else {"kind", "snapshot_id", "issuer_id"}
        if kind not in ("document", "financial_snapshot") or set(citation) != keys:
            raise SecurityError(
                422, "citations accept only immutable source IDs, not source text or verification claims"
            )
        if not all(isinstance(v, str) for v in citation.values()):
            raise SecurityError(422, "citation IDs must be strings")
        if kind == "document":
            valid = DOCUMENT.fullmatch(citation["document_id"]) and HASH.fullmatch(citation["version_id"])
            valid = valid and ".." not in citation["document_id"].rsplit(":", 1)[-1]
        else:
            valid = HASH.fullmatch(citation["snapshot_id"]) and ISSUER.fullmatch(citation["issuer_id"])
        if not valid:
            raise SecurityError(422, "citation IDs do not match the immutable source contract")
        try:
            if kind == "document":
                _, cik, accession, filename = citation["document_id"].split(":", 3)
                if sec_document_id(int(cik), accession, filename) != citation["document_id"]:
                    raise ValueError("noncanonical source")
            elif issuer_id(int(citation["issuer_id"].split(":")[1])) != citation["issuer_id"]:
                raise ValueError("noncanonical issuer")
        except ValueError as error:
            raise SecurityError(422, "citation IDs do not match the immutable source contract") from error
        if citation not in out:
            out.append(dict(citation))
    return out


class ProjectStore:
    def __init__(self, security: SecurityStore, resolve_document=None):
        self.security = security
        self.resolve_document = resolve_document or self._document

    def _document(self, version_id: str):
        from filings_hub.research_index import open_index

        index = open_index(self.security.storage, self.security.database_url)
        try:
            return index.version(version_id)
        finally:
            index.close()

    def authorize(self, tx, project_id: str, actor: str, manage: bool = False) -> tuple[dict[str, Any], bool]:
        row = tx.get("projects", project_id)
        if row is None:
            raise SecurityError(404, "project not found")
        if row["organization_id"]:
            _, member = self.security.authorize(tx, row["organization_id"], actor)
            can_manage = member["role"] in {"owner", "admin"}
        else:
            if row["owner_id"] != actor:
                raise SecurityError(404, "project not found")
            can_manage = True
        if manage and not can_manage:
            raise SecurityError(403, "only an organization owner or administrator can manage this project")
        return row, can_manage

    @contextmanager
    def transaction(self, project_id: str, actor: str, manage: bool = False):
        # The organization cannot be moved after creation. Resolve the lock namespace, then re-read
        # and reauthorize inside that lock, shared with membership mutations and every project write.
        with self.security.transaction() as tx:
            row, _ = self.authorize(tx, project_id, actor, manage)
            scope = "org:" + row["organization_id"] if row["organization_id"] else "user:" + row["owner_id"]
        with self.security.transaction(scope) as tx:
            row, can_manage = self.authorize(tx, project_id, actor, manage)
            yield tx, row, can_manage

    def list(self, actor: str) -> list[dict[str, Any]]:
        with self.security.transaction() as tx:
            rows = [r for r in tx.find("projects", owner_id=actor) if r["organization_id"] is None]
            for membership in tx.find("memberships", user_id=actor):
                if membership["role"] in ROLES:
                    rows.extend(tx.find("projects", organization_id=membership["organization_id"]))
            visible = []
            for row in rows:
                current, can_manage = self.authorize(tx, row["id"], actor)
                visible.append({**current, "can_manage": can_manage})
            return sorted(visible, key=lambda r: (r["updated_at"], r["id"]), reverse=True)

    def create(self, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) - {"name", "description", "organization_id", "template_id"}:
            raise SecurityError(422, "unknown project fields")
        name = text_field(payload.get("name"), "name", 120, True)
        description = text_field(payload.get("description", ""), "description", 2000)
        template = find_template(payload.get("template_id"))
        org = payload.get("organization_id")
        if org is not None and (not isinstance(org, str) or not re.fullmatch(r"[0-9a-f]{32}", org)):
            raise SecurityError(422, "organization_id must identify an organization or be null")
        scope = "org:" + org if org else "user:" + actor
        with self.security.transaction(scope) as tx:
            can_manage = True
            if org:
                _, member = self.security.authorize(tx, org, actor)
                can_manage = member["role"] in {"owner", "admin"}
            elif self.security.users.get_user(actor) is None:
                raise SecurityError(401, "sign in required")
            created = stamp()
            row = {
                "id": uuid.uuid4().hex,
                "owner_id": actor,
                "organization_id": org,
                "name": name,
                "description": description,
                "revision": 1,
                "created_at": created,
                "updated_at": created,
            }
            if template:
                row["starter_template"] = {"id": template["id"], "version": template["version"]}
            tx.put("projects", row)
            self.security.audit(tx, actor, "project.created", row["id"], org)
            if template:
                for prompt in template["notes"]:
                    note = self.new_note(row["id"], actor, self.note_changes(prompt, create=True), created)
                    note["authorship"] = "template"
                    note["origin"] = {
                        "kind": "starter_template",
                        "template_id": template["id"],
                        "template_version": template["version"],
                    }
                    tx.put("notes", note)
                    self.security.audit(
                        tx,
                        actor,
                        "note.created",
                        note["id"],
                        org,
                        project_id=row["id"],
                        template_id=template["id"],
                        template_version=template["version"],
                    )
            return {**row, "can_manage": can_manage}

    def get(self, project_id: str, actor: str) -> dict[str, Any]:
        with self.security.transaction() as tx:
            row, can_manage = self.authorize(tx, project_id, actor)
            return {**row, "can_manage": can_manage}

    def export(self, project_id: str, actor: str) -> dict[str, Any]:
        # The scope lock gives the project and notes one coherent revision and serializes with
        # membership removal. Resolve references now; never export cached provider content.
        with self.transaction(project_id, actor) as (tx, project, _):
            exported_at = stamp()
            project_fields = ("id", "name", "description", "revision", "created_at", "updated_at", "starter_template")
            note_fields = (
                "id",
                "project_id",
                "title",
                "body",
                "kind",
                "authorship",
                "origin",
                "revision",
                "created_at",
                "updated_at",
            )
            references = {}
            notes = []
            for note in sorted(tx.find("notes", project_id=project_id), key=lambda row: (row["created_at"], row["id"])):
                citations = []
                for citation in note["citations"]:
                    key = tuple(sorted(citation.items()))
                    if key not in references:
                        references[key] = self.reference(citation)
                    citations.append(references[key])
                notes.append({**{key: note[key] for key in note_fields if key in note}, "citations": citations})
            return {
                "format": "disclosure.research-project",
                "schema_version": 1,
                "exported_at": exported_at,
                "source_policy": {
                    "provider_documents_included": False,
                    "references": (
                        "Source pointers and their resolution status at export; not redistributed document text."
                    ),
                    "note_bodies": "User-authored text or local starter prompts, as labeled by authorship and origin.",
                },
                "scope": {
                    "kind": "organization" if project["organization_id"] else "personal",
                    "organization_id": project["organization_id"],
                },
                "project": {key: project[key] for key in project_fields if key in project},
                "notes": notes,
            }

    def update(self, project_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) - {"expected_revision", "name", "description"}:
            raise SecurityError(422, "project scope and ownership cannot be changed")
        with self.transaction(project_id, actor) as (tx, row, can_manage):
            revision_matches(row, payload.get("expected_revision"))
            changes = {}
            for field, maximum in (("name", 120), ("description", 2000)):
                if field in payload:
                    changes[field] = text_field(payload[field], field, maximum, field == "name")
            if not changes:
                raise SecurityError(422, "include a project field to update")
            updated = {**row, **changes, "revision": row["revision"] + 1, "updated_at": stamp()}
            tx.put("projects", updated)
            self.security.audit(
                tx, actor, "project.updated", project_id, row["organization_id"], revision=updated["revision"]
            )
            return {**updated, "can_manage": can_manage}

    def delete(self, project_id: str, actor: str, expected: Any) -> dict[str, Any]:
        with self.transaction(project_id, actor, manage=True) as (tx, row, _):
            revision_matches(row, expected)
            for note in tx.find("notes", project_id=project_id):
                tx.delete("notes", note["id"])
            tx.delete("projects", project_id)
            self.security.audit(
                tx, actor, "project.deleted", project_id, row["organization_id"], revision=row["revision"]
            )
            return {"deleted": True}

    def reference(self, citation: dict[str, str]) -> dict[str, Any]:
        if citation["kind"] == "financial_snapshot":
            return {
                **citation,
                "status": "unresolved",
                "explanation": "Content hash reference; financial response is not archived.",
            }
        try:
            document = self.resolve_document(citation["version_id"])
        except Exception as error:
            # A reference-resolution outage must not make a committed note creation appear to fail
            # and invite duplicate retries. Return no source content when resolution cannot run.
            log.warning("project reference resolution unavailable: %s", type(error).__name__)
            return {**citation, "status": "unavailable", "explanation": "The source index is unavailable."}
        if (
            not document
            or document.get("document_id") != citation["document_id"]
            or document.get("version_id") != citation["version_id"]
        ):
            return {
                **citation,
                "status": "unavailable",
                "explanation": "This source version is missing or is not accessible.",
            }
        return {
            **citation,
            "status": "available",
            "source_url": document.get("source_url"),
            "title": document.get("title"),
            "explanation": "Indexed source reference; it does not verify the note's contents.",
        }

    def render_note(self, note: dict[str, Any]) -> dict[str, Any]:
        return {**note, "citations": [self.reference(citation) for citation in note["citations"]]}

    @staticmethod
    def touch_project(tx, project: dict[str, Any]) -> int:
        updated = {**project, "revision": project["revision"] + 1, "updated_at": stamp()}
        tx.put("projects", updated)
        return updated["revision"]

    def notes(self, project_id: str, actor: str) -> list[dict[str, Any]]:
        with self.security.transaction() as tx:
            self.authorize(tx, project_id, actor)
            rows = tx.find("notes", project_id=project_id)
        return [self.render_note(row) for row in sorted(rows, key=lambda r: (r["updated_at"], r["id"]), reverse=True)]

    @staticmethod
    def note_changes(payload: dict[str, Any], create: bool = False) -> dict[str, Any]:
        if set(payload) - {"expected_revision", "title", "body", "kind", "citations"}:
            raise SecurityError(422, "notes accept user-authored text and source references only")
        changes = {}
        for field, maximum in (("title", 200), ("body", 100000)):
            if create or field in payload:
                changes[field] = text_field(payload.get(field, ""), field, maximum, field == "title")
        if create or "kind" in payload:
            if payload.get("kind", "note") not in ("note", "thesis"):
                raise SecurityError(422, "kind must be note or thesis")
            changes["kind"] = payload.get("kind", "note")
        if create or "citations" in payload:
            changes["citations"] = validate_citations(payload.get("citations", []))
        return changes

    @staticmethod
    def new_note(project_id: str, actor: str, changes: dict[str, Any], created: str) -> dict[str, Any]:
        return {
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "revision": 1,
            "created_by": actor,
            "created_at": created,
            "updated_at": created,
            "updated_by": actor,
            "authorship": "user",
            **changes,
        }

    def create_note(self, project_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.transaction(project_id, actor) as (tx, project, _):
            changes = self.note_changes(payload, create=True)
            created = stamp()
            row = self.new_note(project_id, actor, changes, created)
            tx.put("notes", row)
            project_revision = self.touch_project(tx, project)
            self.security.audit(tx, actor, "note.created", row["id"], project["organization_id"], project_id=project_id)
        return {**self.render_note(row), "project_revision": project_revision}

    @staticmethod
    def require_note(tx, project_id: str, note_id: str) -> dict[str, Any]:
        row = tx.get("notes", note_id)
        if not row or row["project_id"] != project_id:
            raise SecurityError(404, "note not found")
        return row

    def note(self, project_id: str, note_id: str, actor: str) -> dict[str, Any]:
        with self.security.transaction() as tx:
            self.authorize(tx, project_id, actor)
            row = self.require_note(tx, project_id, note_id)
        return self.render_note(row)

    def update_note(self, project_id: str, note_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.transaction(project_id, actor) as (tx, project, _):
            row = self.require_note(tx, project_id, note_id)
            revision_matches(row, payload.get("expected_revision"))
            changes = self.note_changes(payload)
            if not changes:
                raise SecurityError(422, "include a note field to update")
            updated = {**row, **changes, "revision": row["revision"] + 1, "updated_at": stamp(), "updated_by": actor}
            if {"title", "body"} & changes.keys():
                updated["authorship"] = "user"
            tx.put("notes", updated)
            project_revision = self.touch_project(tx, project)
            self.security.audit(
                tx,
                actor,
                "note.updated",
                note_id,
                project["organization_id"],
                project_id=project_id,
                revision=updated["revision"],
            )
        return {**self.render_note(updated), "project_revision": project_revision}

    def delete_note(self, project_id: str, note_id: str, actor: str, expected: Any) -> dict[str, Any]:
        with self.transaction(project_id, actor, manage=True) as (tx, project, _):
            row = self.require_note(tx, project_id, note_id)
            revision_matches(row, expected)
            tx.delete("notes", note_id)
            project_revision = self.touch_project(tx, project)
            self.security.audit(
                tx,
                actor,
                "note.deleted",
                note_id,
                project["organization_id"],
                project_id=project_id,
                revision=row["revision"],
            )
            return {"deleted": True, "project_revision": project_revision}


def project_router(security: SecurityStore, current_user) -> APIRouter:
    router = APIRouter()
    store = ProjectStore(security)

    def invoke(fn, *args):
        try:
            return fn(*args)
        except SecurityError as error:
            raise HTTPException(error.status, error.detail) from error

    @router.get("/projects")
    def list_projects(user=Depends(current_user)):
        return {"projects": invoke(store.list, user.id)}

    @router.post("/projects", status_code=201)
    def create_project(payload: dict[str, Any] = Body(...), user=Depends(current_user)):
        return {"project": invoke(store.create, user.id, payload)}

    @router.get("/projects/templates")
    def list_templates(user=Depends(current_user)):
        return {"templates": templates()}

    @router.get("/projects/{project_id}/export")
    def export_project(project_id: str, user=Depends(current_user)):
        result = invoke(store.export, project_id, user.id)
        return JSONResponse(
            result,
            headers={
                "Content-Disposition": f'attachment; filename="disclosure-project-{result["project"]["id"]}.json"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get("/projects/{project_id}")
    def get_project(project_id: str, user=Depends(current_user)):
        return {"project": invoke(store.get, project_id, user.id)}

    @router.patch("/projects/{project_id}")
    def update_project(project_id: str, payload: dict[str, Any] = Body(...), user=Depends(current_user)):
        return {"project": invoke(store.update, project_id, user.id, payload)}

    @router.delete("/projects/{project_id}")
    def delete_project(project_id: str, expected_revision: int = Query(..., ge=1), user=Depends(current_user)):
        return invoke(store.delete, project_id, user.id, expected_revision)

    @router.get("/projects/{project_id}/notes")
    def list_notes(project_id: str, user=Depends(current_user)):
        return {"notes": invoke(store.notes, project_id, user.id)}

    @router.post("/projects/{project_id}/notes", status_code=201)
    def create_note(project_id: str, payload: dict[str, Any] = Body(...), user=Depends(current_user)):
        return {"note": invoke(store.create_note, project_id, user.id, payload)}

    @router.get("/projects/{project_id}/notes/{note_id}")
    def get_note(project_id: str, note_id: str, user=Depends(current_user)):
        return {"note": invoke(store.note, project_id, note_id, user.id)}

    @router.patch("/projects/{project_id}/notes/{note_id}")
    def update_note(project_id: str, note_id: str, payload: dict[str, Any] = Body(...), user=Depends(current_user)):
        return {"note": invoke(store.update_note, project_id, note_id, user.id, payload)}

    @router.delete("/projects/{project_id}/notes/{note_id}")
    def delete_note(
        project_id: str, note_id: str, expected_revision: int = Query(..., ge=1), user=Depends(current_user)
    ):
        return invoke(store.delete_note, project_id, note_id, user.id, expected_revision)

    return router
