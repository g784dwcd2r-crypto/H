import { NextRequest } from "next/server";
import { requestHeaders } from "@/lib/server-api";
import { workspaceRequest } from "@/lib/workspace-api";
const noStore = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };
export async function GET(request: NextRequest, context: { params: Promise<{ segments?: string[] }> }) {
  const { segments = [] } = await context.params;
  const recent = segments.length === 1 && segments[0] === "recent";
  const exporting = segments.length === 3 && /^\d+$/.test(segments[0]) && ["insiders", "institutions", "events"].includes(segments[1]) && segments[2] === "export";
  if (!recent && !exporting) return Response.json({ error: "Ownership route not found." }, { status: 404, headers: noStore });
  const query = new URLSearchParams();
  for (const key of recent ? ["ciks", "flow", "since", "limit"] : ["from", "to", "direction"]) { const value = request.nextUrl.searchParams.get(key); if (value) query.set(key,value); }
  if (recent) { const result = await workspaceRequest(`/ownership/recent?${query}`); return Response.json(result.data ?? { error: result.error || "Ownership activity could not be loaded." },{ status: result.status, headers: noStore }); }
  const configured = process.env.FILINGS_API_URL || "http://localhost:8000", base = (/^https?:\/\//.test(configured) ? configured : `http://${configured}`).replace(/\/$/,"");
  try {
    const response = await fetch(`${base}/companies/${segments[0]}/ownership/${segments[1]}/export.csv?${query}`,{ headers: await requestHeaders(), cache: "no-store", redirect: "error", signal: AbortSignal.timeout(20000) });
    if (!response.ok) { const payload = await response.json().catch(() => null); return Response.json({ error: typeof payload?.detail === "string" ? payload.detail : "The ownership export could not be generated. Return to your filters and try again." },{ status: response.status, headers: noStore }); }
    return new Response(response.body,{ status:200, headers:{...noStore,"Content-Type":"text/csv; charset=utf-8","Content-Disposition":`attachment; filename="disclosure-${segments[0]}-${segments[1]}.csv"`} });
  } catch { return Response.json({ error:"The ownership export service is unavailable. No download was generated." },{status:503,headers:noStore}); }
}
