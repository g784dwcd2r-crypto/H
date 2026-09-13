import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { sessionToken } from "@/lib/session";
import { workspaceRequest } from "@/lib/workspace-api";
import type { Project, ProjectNote } from "@/lib/workspace-types";
import ProjectWorkspace from "@/components/ProjectWorkspace";

export const dynamic = "force-dynamic";
export const metadata = { title: "Research project" };
export default async function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  if (!await sessionToken()) redirect("/signin");
  const { id } = await params;
  const [project, notes, account] = await Promise.all([workspaceRequest<{ project: Project }>(`/projects/${encodeURIComponent(id)}`), workspaceRequest<{ notes: ProjectNote[] }>(`/projects/${encodeURIComponent(id)}/notes`), workspaceRequest<{user:{id:string}}>("/me")]);
  if (project.status === 401 || notes.status === 401 || account.status === 401) redirect("/signin");
  if (project.status === 403 || project.status === 404) notFound();
  if (!project.data || !notes.data || !account.data) return <div className="page-error"><h1>Project unavailable</h1><p>Your project could not be loaded. Refresh to try again.</p><Link href="/projects">Return to projects</Link></div>;
  return <ProjectWorkspace key={`${account.data.user.id}:${project.data.project.id}`} initialProject={project.data.project} initialNotes={notes.data.notes} accountId={account.data.user.id}/>;
}
