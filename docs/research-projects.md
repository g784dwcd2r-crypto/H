# Research projects: first persistence release

Projects persist personal or organization-scoped research with revisioned notes, thesis text and
source-reference pointers. This is the first D14 persistence slice, not complete document collaboration,
generated research, shared premium-content entitlements, or an archive of financial snapshots.

## Scope and access

Create a personal project with no `organization_id`, or choose an organization from `GET /organizations`.
Only a personal project's owner can access it. An organization's current members can read projects,
change names/descriptions, and create/edit notes. Organization owners/admins can additionally delete
projects and notes. The creator's `owner_id` is attribution, not an override of organization policy:
removing that person's membership removes their access to the organization project too.

Project scope is fixed at creation. No endpoint silently changes an organization, copies private work
into a team, or grants access through a tenant header. Moving/sharing projects and invitations are
separate releases. Personal preferences and watchlists do not become team data.

Every read and write checks membership. Postgres project mutations acquire the same organization
lock as membership mutations, re-read the project and recheck authorization within the transaction.
Personal writes use the owner's lock. Audit, content and revision changes commit together. Lake
development uses the same single-process atomic account-security state as the tenant foundation.

## API and conflict handling

| Endpoint | Request / response |
|---|---|
| `GET /projects` | `{projects:[project]}` visible to the current user |
| `POST /projects` | `{name,description?,organization_id?,template_id?}` -> `{project}` (201) |
| `GET /projects/templates` | `{templates:[{id,version,name,description,notes:[{title,body,kind}]}]}` |
| `GET /projects/{id}` | `{project}` |
| `GET /projects/{id}/export` | Download versioned JSON for the authorized project; see portability below |
| `PATCH /projects/{id}` | `{expected_revision,name?,description?}` -> `{project}` |
| `DELETE /projects/{id}?expected_revision=N` | `{deleted:true}` |
| `GET /projects/{id}/notes` | `{notes:[note]}` |
| `POST /projects/{id}/notes` | `{title,body?,kind?,citations?}` -> `{note}` (201) |
| `GET /projects/{id}/notes/{note_id}` | `{note}` |
| `PATCH /projects/{id}/notes/{note_id}` | `{expected_revision,title?,body?,kind?,citations?}` -> `{note}` |
| `DELETE /projects/{id}/notes/{note_id}?expected_revision=N` | `{deleted:true,project_revision:N}` |

A project has `id`, `name`, `description`, `organization_id`, `owner_id`, `revision`, `created_at`,
`updated_at` and the caller's computed `can_manage`. A note has `id`, `project_id`, `title`, `body`,
`kind` (`note` or `thesis`), `authorship` (`user` or `template`), `citations`, its own `revision`,
author/update IDs and creation/update times. Notes seeded by a starter template also carry `origin`;
see below. Render all text as text, not trusted HTML.

Updates and deletes require the expected revision. A stale revision returns 409 without overwriting
the winning change or creating a mutation audit event. Reload and reconcile the user's work; do not
automatically retry with a newer revision. Concurrent note edits have exactly one winner for a
given revision. A note ID cannot be accessed by substituting another accessible project in its URL.

Note creation, editing and deletion also advance the parent project's revision and updated time.
This prevents deleting a project from an old screen after someone adds or changes a note. Note
mutation responses include `project_revision`; refresh the project or apply that returned revision.
New note creation is not an idempotent operation: callers must not replay it blindly after an
uncertain network outcome. An explicit client operation ID is future retry-hardening work.

Titles are limited to 200 characters, note bodies to 100,000 characters, names to 120 characters,
descriptions to 2,000 characters and each note to 100 source references. Lists are intended for a
small initial workspace; large-workspace pagination, search and retention need a later capacity gate.

## Source references do not certify a note

Only these pointer shapes are accepted:

```json
{"kind":"document","document_id":"sec:0000320193:0000320193-24-000123:report.htm","version_id":"sha256:<64 lowercase hex characters>"}
```

```json
{"kind":"financial_snapshot","issuer_id":"sec:0000320193","snapshot_id":"sha256:<64 lowercase hex characters>"}
```

Document/issuer IDs follow the canonical SEC contracts and hashes identify immutable versions.
The API rejects additional `text`, `quote`, `verified`, source URL or arbitrary metadata fields.
It stores no provider text inside references. Users can write their interpretation in the clearly
user-authored body; a citation does not turn that interpretation into a verified fact.

On each note response, document pointers resolve through the currently public SEC index, matching
both document and version IDs. A readable indexed reference gets `status: "available"` and its current
source title/URL; missing, mismatched, restricted or failed lookup gets `status: "unavailable"` with
no cached provider metadata. A later document restriction therefore also affects saved notes.

Financial pointers get `status: "unresolved"`: the current financial API returns content hashes but
does not archive those responses. The project does not claim that the referenced numbers can be
reconstructed or were independently verified. A reference-resolution outage produces a visible
unavailable state rather than making a committed note save appear to fail and inviting duplicates.

Responses add `status`, `explanation` and optional `title`/`source_url` to references. When editing,
send only their original pointer fields back. This slice does not accept private/licensed documents
into the public index or implement premium-source grant enforcement; such adapters remain blocked.

## Evidence and remaining work

Migration `0011_research_projects.sql` adds Postgres projects/notes with foreign keys and scoped
indexes. Tests in `tests/test_projects.py` exercise lake and real Postgres: personal and cross-tenant
isolation, revoked membership/sessions, fixed scope, owner/admin delete policy, immutable ID checks,
source restriction after save, honest unresolved financial references, source outages, restart
persistence, atomic audit, stale deletion and concurrent note saves.

## Local starter templates (D14.06 first slice)

The authenticated template catalog contains `company-overview`, `earnings-review`, and
`investment-thesis-diligence`, each at version 1. They are locally maintained research questions,
not AI-generated analysis or prefilled company claims. Their three initial notes have no citations.
Omit `template_id` or send null to create a blank project; an unknown ID or invalid type returns 422.
The normal personal/organization creation permissions apply.

Project creation writes the project, its starter notes and audit records in one transaction. A
failure rolls everything back. The complete initial state has project revision 1 and note revision 1;
subsequent changes advance revisions normally. The project records
`starter_template: {id,version}`. Seeded notes have `authorship: "template"` and
`origin: {kind:"starter_template",template_id,template_version}`. A user edit of title or body changes
authorship to `user` while retaining the origin. Adding citations or changing kind alone does not
change authorship. Clients should send only fields the user actually changed when updating a note.

Later catalog changes do not rewrite existing research. This slice does not include user-defined
template publishing, organization template libraries, mandatory workflows or generated answers.

## Portable project JSON (D20.07 first slice)

`GET /projects/{id}/export` requires a current account session and the same project read permission
as the editor. Current organization members may export their shared project; removed members and
other accounts get 404, revoked sessions get 401. Personal projects remain owner-only. The response
is `application/json` with an attachment filename `disclosure-project-{id}.json`,
`Cache-Control: private, no-store` and `X-Content-Type-Options: nosniff`.

The payload is:

```text
{
  format: "disclosure.research-project",
  schema_version: 1,
  exported_at: UTC timestamp,
  source_policy: {
    provider_documents_included: false,
    references: explanation,
    note_bodies: explanation
  },
  scope: {kind: "personal" | "organization", organization_id: null | source organization ID},
  project: {id, name, description, revision, created_at, updated_at, starter_template?},
  notes: [{id, project_id, title, body, kind, authorship, origin?, revision,
           created_at, updated_at, citations: [resolved source pointers]}]
}
```

The project metadata and all saved notes are captured under the scope lock used by edits and
membership changes, so concurrent saves cannot mix project and note revisions. Source pointers
are resolved when exporting; unavailable/restricted sources have no cached title, URL or text.
Financial pointers remain explicitly unresolved. The export includes the saved note bodies,
including local starter prompts as labeled, and source-reference metadata. References are not
redistributed provider documents and do not certify the note text. It excludes unsaved browser
drafts, other projects, account records, member rosters, email addresses, author account IDs,
session records and security audit data. The organization ID describes the exported project's
scope; it does not grant access or transfer permissions to a different system.

Tests cover live source restriction/outage, current scope/session authorization, privacy fields,
coherent exports during edits, template origin, blank/invalid template selection, and rollback of a
partially seeded project. The same cases run against lake and Postgres storage. This is an open,
versioned download format; an import endpoint, full version-history backup, source-document archive,
bulk account transfer and rights-aware migration of licensed material are not implemented.

Notes retain the current text plus revision and audit metadata. This is not a full historical text
archive or legal retention feature. Invitations, real-time coediting, artifact generation, saved
financial payloads, fine-grained source entitlements, pagination and production-scale operation need
their own releases. Production mail/OAuth, restore and deployment assurance remain separate gates.
