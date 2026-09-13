import { NextRequest } from "next/server";
import { sessionToken } from "@/lib/session";
import { sameOriginMutation, workspaceRequest } from "@/lib/workspace-api";

type Context = { params: Promise<{ segments?: string[] }> };
async function forward(request: NextRequest, context: Context) {
  if (request.method !== "GET" && !sameOriginMutation(request)) return Response.json({ error: "Request origin does not match." }, { status: 403 });
  const { segments = [] } = await context.params;
  const parts = segments.map(segment => { try { return decodeURIComponent(segment); } catch { return ""; } });
  if (parts.some(part => !/^[a-zA-Z0-9:_-]{1,200}$/.test(part))) return Response.json({ error: "Invalid research path." }, { status: 400 });
  const read = request.method === "GET";
  const allowed = read && parts.length === 1 && ["capabilities", "search"].includes(parts[0]) || read && parts.length === 2 && ["runs", "spans", "documents", "projections"].includes(parts[0]) || !read && parts[0] === "runs" && (parts.length === 1 || parts.length === 3 && ["save", "calculations"].includes(parts[2]));
  if (!allowed) return Response.json({ error: "Research route not found." }, { status: 404 });
  if (parts[0] === "runs" && !await sessionToken()) return Response.json({ error: "Sign in to create or open private research." }, { status: 401 });
  let path = `/research/${parts.map(encodeURIComponent).join("/")}`;
  if (read && parts[0] === "search") {
    const query = new URLSearchParams();
    for (const key of ["q", "cik", "form", "from", "to", "limit", "offset"]) { const value = request.nextUrl.searchParams.get(key); if (value) query.set(key, value); }
    path += `?${query}`;
  }
  let body: unknown;
  if (!read) { try { body = await request.json(); } catch { return Response.json({ error: "Invalid request body." }, { status: 400 }); } }
  const result = await workspaceRequest(path, read ? "GET" : "POST", body, !read && parts.length === 1 && parts[0] === "runs" ? 180_000 : 20_000);
  return Response.json(result.data ?? { error: result.error || (result.status === 404 ? "This research or source is unavailable, or you no longer have access." : result.status === 503 ? "The research provider or prepared source corpus is unavailable. Your question and selection have been kept." : "The research request could not be completed.") }, { status: result.status, headers: { "Cache-Control": "private, no-store" } });
}
export const GET = forward;
export const POST = forward;
