import { redirect } from "next/navigation";
import { sessionToken } from "@/lib/session";
import { workspaceRequest } from "@/lib/workspace-api";
import type { OrganizationChoice, Project, ProjectTemplate } from "@/lib/workspace-types";
import ProjectList from "@/components/ProjectList";

export const dynamic = "force-dynamic";
export const metadata = { title: "Research projects" };
export default async function ProjectsPage() {
  if (!await sessionToken()) redirect("/signin");
  const [projects, organizations, templates] = await Promise.all([workspaceRequest<{ projects: Project[] }>("/projects"), workspaceRequest<{ organizations: OrganizationChoice[] }>("/organizations"), workspaceRequest<{ templates: ProjectTemplate[] }>("/projects/templates")]);
  if (projects.status === 401) redirect("/signin");
  return <div className="projects-page"><p className="eyebrow">Research workspace</p><h1>Projects</h1><p className="lead">Develop your thinking in notes and theses, with references back to the sources you use.</p><ProjectList initial={projects.data?.projects ?? null} organizations={organizations.data?.organizations ?? []} templates={templates.data?.templates ?? []} initialError={!projects.ok ? "Projects could not be loaded. Refresh to try again." : !organizations.ok ? "Organisation access could not be checked. New projects can be personal until access is available." : !templates.ok ? "Templates could not be loaded. You can still start with a blank project." : null}/></div>;
}
