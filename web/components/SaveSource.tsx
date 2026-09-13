"use client";
import { useState } from "react";
import Link from "next/link";
import { projectRequest, ProjectRequestError } from "@/lib/project-client";
import type { Project } from "@/lib/workspace-types";

export default function SaveSource({ documentId, versionId, title }: { documentId: string; versionId: string; title: string }) {
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [projectId, setProjectId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [signedOut, setSignedOut] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const start = async () => {
    setOpen(true); setBusy(true); setError(null);
    try { const data = await projectRequest<{ projects: Project[] }>(""); setProjects(data.projects); setProjectId(data.projects[0]?.id ?? ""); }
    catch (e) { if (e instanceof ProjectRequestError && e.status === 401) setSignedOut(true); else setError("Your projects could not be loaded. Please try again."); }
    finally { setBusy(false); }
  };
  return <div className="save-source-control">
    <button className="btn secondary" type="button" aria-expanded={open} onClick={() => open ? setOpen(false) : void start()}>Add source to project</button>
    {open && <div className="save-source-panel"><h3>Keep this source with your research</h3><p>This creates a source note with a reference to this indexed document version.</p>{error && <p role="alert" className="err">{error}</p>}{signedOut ? <Link href="/signin">Sign in to use projects →</Link> : projects && projects.length ? <><label>Project<select value={projectId} onChange={e => { setProjectId(e.target.value); setSaved(null); }}>{projects.map(project => <option key={project.id} value={project.id}>{project.name}{project.organization_id ? " · organisation" : ""}</option>)}</select></label><button type="button" className="btn" disabled={busy || !!saved} onClick={async () => { setBusy(true); setError(null); try { await projectRequest(`/${projectId}/notes`, "POST", { title: (title || "Source document").slice(0, 200), body: "", kind: "note", citations: [{ kind: "document", document_id: documentId, version_id: versionId }] }); setSaved(projectId); } catch (e) { setError(e instanceof Error ? e.message : "The source could not be saved."); } finally { setBusy(false); } }}>{busy ? "Saving…" : saved ? "Source saved" : "Save source note"}</button>{saved && <p role="status">Source note saved. <Link href={`/projects/${saved}`}>Open project →</Link></p>}</> : !busy && <p>No projects yet. <Link href="/projects">Create a project →</Link></p>}{busy && !projects && <p role="status">Loading projects…</p>}<button type="button" className="linkbtn" onClick={() => setOpen(false)}>Close</button></div>}
  </div>;
}
