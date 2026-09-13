import ResearchNav from "@/components/ResearchNav";
import CitedResearchWorkspace from "@/components/CitedResearchWorkspace";
import { sessionToken } from "@/lib/session";
import { workspaceRequest } from "@/lib/workspace-api";
import { documentVersionParam, type IndexedDocument } from "@/lib/research";
import type { CitedRun, ResearchCapabilities } from "@/lib/cited-research";

export const dynamic = "force-dynamic";
export const metadata = { title: "Ask with sources" };
export default async function AskResearchPage({ searchParams }: { searchParams: Promise<{ run?: string; version?: string }> }) {
  const params = await searchParams;
  const version = params.version ? documentVersionParam(params.version) : null;
  const runId = params.run && /^[a-zA-Z0-9_-]{1,200}$/.test(params.run) ? params.run : null;
  const signedIn = !!await sessionToken();
  const [capabilities, run, document, account] = await Promise.all([
    workspaceRequest<ResearchCapabilities>("/research/capabilities"),
    runId && signedIn ? workspaceRequest<CitedRun>(`/research/runs/${runId}`) : Promise.resolve(null),
    version ? workspaceRequest<IndexedDocument>(`/research/documents/${encodeURIComponent(version)}`) : Promise.resolve(null),
    signedIn ? workspaceRequest<{user:{id:string}}>("/me") : Promise.resolve(null),
  ]);
  const error = params.run && !signedIn ? "Sign in to open private research." : params.run && (!runId || !run?.ok) ? "This research could not be opened. It may be unavailable or outside your current access." : params.version && !document?.ok ? "The selected document could not be loaded. Choose an available indexed source." : null;
  return <div className="cited-research-page"><ResearchNav current="ask"/><div className="research-heading"><div><p className="eyebrow">Evidence before conclusions</p><h1>Ask. Inspect. Develop your view.</h1><p className="lead">Work through a question using selected company filings. Open the exact passages behind each machine-assessed claim.</p></div></div><CitedResearchWorkspace key={runId || version || "new"} signedIn={!!account?.data?.user.id} accountId={account?.data?.user.id || null} capabilities={capabilities.data} initialRun={run?.data ?? null} initialDocument={document?.data ?? null} initialError={error}/></div>;
}
