"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ProjectRequestError, projectRequest, referencePointer } from "@/lib/project-client";
import type { Project, ProjectNote, SourceReference } from "@/lib/workspace-types";

import { clearProjectDraft, noteDraft as draftOf, readProjectDraft, writeProjectDraft, type NoteDraft as Draft } from "@/lib/project-drafts";
const empty = (): Draft => ({ title: "", body: "", kind: "note", citations: [] });


export default function ProjectWorkspace({ initialProject, initialNotes, accountId }: { initialProject: Project; initialNotes: ProjectNote[]; accountId: string }) {
  const router = useRouter();
  const [project, setProject] = useState(initialProject);
  const [notes, setNotes] = useState(initialNotes);
  const [current, setCurrent] = useState<ProjectNote | null>(initialNotes[0] ?? null);
  const [draft, setDraft] = useState<Draft>(initialNotes[0] ? draftOf(initialNotes[0]) : empty());
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [latest, setLatest] = useState<ProjectNote | null>(null);
  const [projectOptions, setProjectOptions] = useState(false);
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description);
  const [referenceKind, setReferenceKind] = useState<"document" | "financial_snapshot">("document");
  const [referenceId, setReferenceId] = useState("");
  const [referenceVersion, setReferenceVersion] = useState("");
  const base = `/${project.id}`;
  const editVersion = useRef(0);
  const [draftReady, setDraftReady] = useState(false);
  const [durableDraft, setDurableDraft] = useState(true);
  const draftStorage = () => { try { return window.sessionStorage; } catch { return null; } };
  useEffect(() => {
    const recovered = readProjectDraft(draftStorage(), accountId, initialProject.id);
    if (recovered) {
      const savedNote = initialNotes.find(note => note.id === recovered.noteId) ?? null;
      const changedRemotely = !!savedNote && savedNote.revision !== recovered.baseRevision;
      setCurrent(savedNote && recovered.baseRevision ? {...savedNote,revision:recovered.baseRevision} : null);
      setDraft(recovered.draft); setDirty(true); setConflict(changedRemotely);
      setNotice("Your unsaved draft was recovered in this tab. Review it, then save to your project.");
      if (changedRemotely) setError("The saved note changed while you were away. Compare the latest version before saving your recovered draft.");
      else if (recovered.noteId && !savedNote) setNotice("The original note is no longer available. Your recovered writing is a new unsaved draft.");
    }
    setDraftReady(true);
    // The server rechecks account and project access before mounting this editor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, initialProject.id]);
  useEffect(() => {
    if (!draftReady) return;
    if (dirty) setDurableDraft(writeProjectDraft(draftStorage(), {version:1,accountId,projectId:project.id,noteId:current?.id ?? null,baseRevision:current?.revision ?? null,draft}));
    else clearProjectDraft(draftStorage(),accountId,project.id);
  }, [accountId,project.id,current,draft,dirty,draftReady]);
  useEffect(() => {
    if (!dirty) return;
    const handler = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);
  const change = (next: Partial<Draft>) => { editVersion.current += 1; setDraft(value => ({ ...value, ...next })); setDirty(true); setNotice(null); };
  const open = (note: ProjectNote | null) => {
    if (dirty && !window.confirm("Discard the unsaved draft and open another note?")) return;
    setCurrent(note); setDraft(note ? draftOf(note) : empty()); setDirty(false); setError(null); setNotice(null); setConflict(false); setLatest(null);
  };
  const updateProjectRevision = (revision?: number) => { if (revision) setProject(value => ({ ...value, revision })); };
  const downloadResearch = async () => {
    setExporting(true); setError(null);
    try {
      const data = await projectRequest<{ format: string; schema_version: number }>(`${base}/export`);
      if (data.format !== "disclosure.research-project" || data.schema_version !== 1) throw new Error("The research download format could not be confirmed. Please try again.");
      const blob = new Blob([JSON.stringify(data, null, 2) + "\n"], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a"); link.href = url; link.download = `Disclosure-research-${project.id}.json`; document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      setNotice(dirty ? "Saved research downloaded. Your unsaved draft is still in the editor and is not included." : "Saved research downloaded as JSON, including notes and source references.");
    } catch (e) { setError(e instanceof Error ? e.message : "Your saved research could not be downloaded."); }
    finally { setExporting(false); }
  };
  const save = async () => {
    const submittedVersion = editVersion.current;
    setBusy(true); setError(null); setNotice(null);
    try {
      const payload = current ? {
        expected_revision: current.revision,
        ...(draft.title.trim() !== current.title ? { title: draft.title.trim() } : {}),
        ...(draft.body !== current.body ? { body: draft.body } : {}),
        ...(draft.kind !== current.kind ? { kind: draft.kind } : {}),
        citations: draft.citations.map(referencePointer),
      } : { ...draft, title: draft.title.trim(), citations: draft.citations.map(referencePointer) };
      const response = await projectRequest<{ note: ProjectNote & { project_revision?: number } }>(current ? `${base}/notes/${current.id}` : `${base}/notes`, current ? "PATCH" : "POST", payload);
      setCurrent(response.note); setNotes(list => [response.note, ...list.filter(note => note.id !== response.note.id)]); updateProjectRevision(response.note.project_revision); setConflict(false); setLatest(null);
      if (editVersion.current === submittedVersion) { setDraft(draftOf(response.note)); setDirty(false); setNotice("Saved to this project."); }
      else { setDirty(true); setNotice("The submitted version was saved. Your newer edits are still here and remain unsaved."); }
    } catch (e) { setError(e instanceof Error ? e.message : "Your note could not be saved."); setConflict(e instanceof ProjectRequestError && e.status === 409); }
    finally { setBusy(false); }
  };
  const loadLatest = async () => {
    if (!current) return;
    setBusy(true);
    try { const response = await projectRequest<{ note: ProjectNote }>(`${base}/notes/${current.id}`); setLatest(response.note); }
    catch (e) { setError(e instanceof Error ? e.message : "The latest note could not be loaded."); }
    finally { setBusy(false); }
  };
  return <div className="project-workspace-page">
    <p className="crumb"><Link href="/projects">← All projects</Link></p>
    <div className="research-heading"><div><p className="eyebrow">{project.organization_id ? "Organisation project" : "Personal project"}</p><h1>{project.name}</h1><p className="lead">{project.description || "Notes, a working thesis and the sources behind your research."}</p></div><div className="project-header-actions"><button className="btn secondary" type="button" disabled={exporting || busy} onClick={() => void downloadResearch()}>{exporting ? "Preparing download…" : "Download saved research"}</button>{project.can_manage && <button className="linkbtn" onClick={() => setProjectOptions(value => !value)} aria-expanded={projectOptions}>Project settings</button>}<p>Portable JSON of saved notes and references. Source documents are linked, not bundled.</p></div></div>
    {projectOptions && <form className="project-create" onSubmit={async event => { event.preventDefault(); setBusy(true); setError(null); try { const response = await projectRequest<{ project: Project }>(base, "PATCH", { expected_revision: project.revision, name, description }); setProject(response.project); setProjectOptions(false); setNotice("Project details saved."); } catch (e) { setError(e instanceof Error ? e.message : "Project details could not be saved."); } finally { setBusy(false); } }}>
      <label>Project name<input value={name} onChange={e => setName(e.target.value)} required maxLength={160}/></label><label>Description<textarea value={description} onChange={e => setDescription(e.target.value)} maxLength={2000}/></label><div className="row"><button className="btn" disabled={busy}>Save project details</button><button type="button" className="linkbtn danger-action" disabled={busy} onClick={async () => { if (!window.confirm(`Delete “${project.name}” and all its notes? This cannot be undone.`)) return; setBusy(true); try { await projectRequest(`${base}?expected_revision=${project.revision}`, "DELETE"); setDirty(false); router.push("/projects"); } catch (e) { setError(e instanceof Error ? e.message : "The project could not be deleted."); } finally { setBusy(false); } }}>Delete project</button></div><p className="filter-hint">Project access is fixed at creation. {project.organization_id ? "Organisation members can read and edit notes; owners and admins manage deletion." : "Only your account can access this project."}</p>
    </form>}
    {error && <div className="notice" role="alert">{error}{conflict && !latest && <button className="linkbtn" disabled={busy} onClick={() => void loadLatest()}>Compare latest saved version</button>}</div>}
    {notice && <p className="saved" role="status">{notice}</p>}
    {dirty && <p className="notice draft-recovery-notice">{durableDraft ? "Unsaved writing is kept for your account in this browser tab. It is not saved to the project or included in downloads until you save." : "This browser could not retain a reload-safe draft. Your writing is still in this open page; save before reloading or closing the tab."}</p>}
    <div className="project-workspace">
      <aside className="project-notes-nav" aria-label="Project notes"><div><h2>Notes & theses</h2><button className="linkbtn" disabled={busy} onClick={() => open(null)}>+ New note</button></div>{notes.length ? <ul>{notes.map(note => <li key={note.id}><button onClick={() => open(note)} disabled={busy} aria-current={current?.id === note.id ? "true" : undefined}><span>{note.kind === "thesis" ? "Thesis" : "Note"}</span><strong>{note.title}</strong><small>{note.citations.length} source {note.citations.length === 1 ? "reference" : "references"}</small></button></li>)}</ul> : <p className="muted">No saved notes yet. Write your first note here.</p>}<Link href="/research">Find source documents ↗</Link></aside>
      <section className="note-editor" aria-label="Research note editor">
        <div className="note-editor-top"><label>Type<select aria-label="Note type" value={draft.kind} onChange={e => change({ kind: e.target.value as Draft["kind"] })}><option value="note">Research note</option><option value="thesis">Working thesis</option></select></label><span>{dirty ? "Unsaved changes" : current ? `Saved · revision ${current.revision}` : "New draft"}</span></div>
        {current?.authorship === "template" && <p className="template-origin">Starter template prompts. Replace or expand them with your own research; they are not completed findings.</p>}
        <label>Title<input aria-label="Note title" value={draft.title} onChange={e => change({ title: e.target.value })} maxLength={200} placeholder="Give your research a title"/></label>
        <label>Your analysis<textarea aria-label="Your analysis" value={draft.body} onChange={e => change({ body: e.target.value })} maxLength={100000} rows={14} placeholder={draft.kind === "thesis" ? "Your thesis, supporting evidence, counterarguments and what would change your mind…" : "Write your observations, questions and next steps…"}/></label>
        {latest && <div className="note-conflict"><h3>Latest saved version · revision {latest.revision}</h3><strong>{latest.title}</strong><pre>{latest.body}</pre><p>Review the saved text and source references before merging changes into your draft. Nothing will be overwritten until you save.</p><p>{latest.citations.length} source references in the saved version.</p><div className="row"><button className="btn secondary" type="button" onClick={() => { setCurrent(latest); setDraft(draftOf(latest)); setDirty(false); setLatest(null); setConflict(false); setError(null); }}>Use latest saved version</button><button className="btn secondary" type="button" onClick={() => { setCurrent(latest); setLatest(null); setConflict(false); setError(null); setDirty(true); setNotice("Your draft is ready to merge. Review it, then save against the latest revision."); }}>Keep my draft for merging</button></div></div>}
        <div className="note-references"><h3>Source references</h3><p>References link your analysis to documents or snapshots. They do not verify the claims in your note.</p>{draft.citations.length > 0 && <ul>{draft.citations.map((reference, index) => <li key={index}><div><strong>{reference.title || (reference.kind === "document" ? "Document reference" : "Financial snapshot reference")}</strong><span className={"reference-status " + (reference.status || "unresolved")}>{reference.status === "available" ? "Source available" : reference.status === "unavailable" ? "Source unavailable" : "Reference unresolved"}</span><p>{reference.explanation || "Availability will be checked when this note is saved."}</p>{reference.kind === "document" ? <><code>{reference.document_id}</code><code>{reference.version_id}</code>{reference.status === "available" && <Link href={`/research/documents/${encodeURIComponent(reference.version_id)}`}>Open indexed source ↗</Link>}</> : <code>{reference.issuer_id} · {reference.snapshot_id}</code>}</div><button className="linkbtn" type="button" onClick={() => change({ citations: draft.citations.filter((_, i) => i !== index) })}>Remove</button></li>)}</ul>}
          <details><summary>Add a source reference</summary><label>Reference type<select value={referenceKind} onChange={e => setReferenceKind(e.target.value as typeof referenceKind)}><option value="document">Indexed document</option><option value="financial_snapshot">Financial snapshot</option></select></label><label>{referenceKind === "document" ? "Document ID" : "Issuer ID"}<input value={referenceId} onChange={e => setReferenceId(e.target.value)} placeholder={referenceKind === "document" ? "Copy from the indexed source" : "Issuer identifier"}/></label><label>{referenceKind === "document" ? "Version ID" : "Snapshot ID"}<input value={referenceVersion} onChange={e => setReferenceVersion(e.target.value)} placeholder="sha256:…"/></label><button className="btn secondary" type="button" disabled={!referenceId.trim() || !referenceVersion.trim()} onClick={() => { change({ citations: [...draft.citations, referenceKind === "document" ? { kind: "document", document_id: referenceId.trim(), version_id: referenceVersion.trim() } : { kind: "financial_snapshot", issuer_id: referenceId.trim(), snapshot_id: referenceVersion.trim() }] }); setReferenceId(""); setReferenceVersion(""); }}>Attach reference to draft</button></details>
        </div>
        <div className="note-save-actions"><button className="btn" type="button" disabled={busy || !draft.title.trim() || conflict || !!current && !dirty} onClick={() => void save()}>{busy ? "Saving…" : current ? "Save changes" : "Save note"}</button>{current && project.can_manage && <button type="button" className="linkbtn danger-action" disabled={busy} onClick={async () => { if (!window.confirm(`Delete “${current.title}”? This cannot be undone.`)) return; setBusy(true); setError(null); try { const response = await projectRequest<{ project_revision: number }>(`${base}/notes/${current.id}?expected_revision=${current.revision}`, "DELETE"); setNotes(list => list.filter(note => note.id !== current.id)); updateProjectRevision(response.project_revision); setCurrent(null); setDraft(empty()); setDirty(false); setNotice("Note deleted."); } catch (e) { setError(e instanceof Error ? e.message : "The note could not be deleted."); } finally { setBusy(false); } }}>Delete note</button>}<span>{current?.authorship === "template" ? "Template prompts · add your own analysis" : "Your writing · no generated analysis"}</span></div>
      </section>
    </div>
  </div>;
}
