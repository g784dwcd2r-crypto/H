"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { projectRequest } from "@/lib/project-client";
import type { OrganizationChoice, Project, ProjectTemplate } from "@/lib/workspace-types";

export default function ProjectList({ initial, organizations, templates, initialError }: { initial: Project[] | null; organizations: OrganizationChoice[]; templates: ProjectTemplate[]; initialError?: string | null }) {
  const router = useRouter();
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(initialError ?? null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [organization, setOrganization] = useState("");
  const [template, setTemplate] = useState("");
  const selectedTemplate = templates.find(item => item.id === template);
  return <>
    <div className="section-heading"><p className="muted">{initial ? `${initial.length} ${initial.length === 1 ? "project" : "projects"}` : "Project list unavailable"}</p><button className="btn" onClick={() => setCreating(value => !value)} aria-expanded={creating} aria-controls="new-project">{creating ? "Close new project" : "New project"}</button></div>
    {error && <div className="notice" role="alert">{error}</div>}
    {creating && <form id="new-project" className="project-create" onSubmit={async event => { event.preventDefault(); setBusy(true); setError(null); try { const data = await projectRequest<{ project: Project }>("", "POST", { name: name.trim(), description: description.trim(), organization_id: organization || null, template_id: template || null }); router.push(`/projects/${data.project.id}`); } catch (e) { setError(e instanceof Error ? e.message : "The project could not be created."); } finally { setBusy(false); } }}>
      <h2>A place for your research</h2><label>Project name<input value={name} onChange={e => setName(e.target.value)} required maxLength={160} autoFocus placeholder="e.g. Payments industry review" /></label><label>Description<textarea value={description} onChange={e => setDescription(e.target.value)} maxLength={2000} rows={2} placeholder="What are you investigating?" /></label>
      <label>Starting point<select value={template} onChange={e => setTemplate(e.target.value)}><option value="">Blank project</option>{templates.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      {selectedTemplate && <div className="template-preview"><p>{selectedTemplate.description}</p><p>Starts with {selectedTemplate.notes.length} note prompts for your own research:</p><ul>{selectedTemplate.notes.map((note, index) => <li key={index}>{note.title}</li>)}</ul><small>These are research prompts, not generated analysis or completed findings.</small></div>}
      <label>Access<select value={organization} onChange={e => setOrganization(e.target.value)}><option value="">Personal · only you</option>{organizations.map(org => <option key={org.id} value={org.id}>{org.name} · organisation members</option>)}</select></label>
      <p className="filter-hint">Access is fixed when the project is created. Organisation projects are visible to that organisation’s members.</p><button type="submit" className="btn" disabled={busy || !name.trim()}>{busy ? "Creating…" : "Create project"}</button>
    </form>}
    {initial && initial.length > 0 ? <ul className="project-list">{initial.map(project => <li key={project.id}><div><span className="project-scope">{project.organization_id ? organizations.find(org => org.id === project.organization_id)?.name || "Organisation project" : "Personal project"}</span><h2><Link href={`/projects/${project.id}`}>{project.name}</Link></h2><p>{project.description || "No description added."}</p></div><Link className="text-link" href={`/projects/${project.id}`}>Open project →</Link></li>)}</ul> : initial && !creating && <div className="empty"><h2>Your research, kept together.</h2><p>Create a project for notes, a working thesis and source references. Nothing is generated or shared automatically.</p><button className="btn secondary" onClick={() => setCreating(true)}>Create your first project</button></div>}
  </>;
}
