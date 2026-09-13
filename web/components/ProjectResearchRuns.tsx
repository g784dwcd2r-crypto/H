import Link from "next/link";
import { workspaceRequest } from "@/lib/workspace-api";
import type { ResearchRunSummary } from "@/lib/cited-research";

export default async function ProjectResearchRuns({ projectId }: { projectId: string }) {
  const result = await workspaceRequest<ResearchRunSummary[]>(`/projects/${encodeURIComponent(projectId)}/research-runs`);
  return <section className="project-research-artifacts" aria-label="Saved cited research"><h2>Saved source research</h2><p>These artifacts retain the question, cutoff, evidence and calculations. Current project and source access is checked when opened.</p>{!result.ok ? <p>Saved research artifacts could not be loaded.</p> : !result.data?.length ? <p>No source research saved here yet. <Link href="/research/ask">Ask with sources →</Link></p> : <ul>{result.data.map(run => <li key={run.id}><Link href={`/research/ask?run=${run.id}`}>{run.question}</Link><span>{new Date(run.created_at).toLocaleDateString("en-GB", { timeZone: "UTC" })} · {run.status.replaceAll("_", " ")}</span></li>)}</ul>}</section>;
}
