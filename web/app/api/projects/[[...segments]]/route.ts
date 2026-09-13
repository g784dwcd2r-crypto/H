import { NextRequest } from "next/server";
import { sessionToken } from "@/lib/session";
import { sameOriginMutation, workspaceRequest } from "@/lib/workspace-api";

type Context = { params: Promise<{ segments?: string[] }> };
async function forward(request: NextRequest, context: Context) {
  if (request.method !== "GET" && !sameOriginMutation(request)) return Response.json({ error: "Request origin does not match." }, { status: 403 });
  if (!await sessionToken()) return Response.json({ error: "Sign in to use projects." }, { status: 401 });
  const { segments = [] } = await context.params;
  if (segments.some(segment => !/^[a-zA-Z0-9_-]{1,200}$/.test(segment))) return Response.json({ error: "Invalid project path." }, { status: 400 });
  let path: string;
  if (segments.length === 0 || segments.length === 1 || (segments.length === 2 || segments.length === 3) && segments[1] === "notes" || segments.length === 2 && segments[1] === "export" && request.method === "GET") path = `/projects${segments.length ? "/" + segments.join("/") : ""}`;
  else return Response.json({ error: "Project route not found." }, { status: 404 });
  if (request.method === "DELETE") {
    const revision = request.nextUrl.searchParams.get("expected_revision");
    if (!revision || !/^\d+$/.test(revision)) return Response.json({ error: "The saved revision is required." }, { status: 400 });
    path += `?expected_revision=${revision}`;
  }
  let body: unknown = undefined;
  if (request.method === "POST" || request.method === "PATCH") {
    try { body = await request.json(); } catch { return Response.json({ error: "Invalid request body." }, { status: 400 }); }
  }
  const result = await workspaceRequest(path, request.method as "GET" | "POST" | "PATCH" | "DELETE", body);
  return Response.json(result.data ?? { error: result.status === 409 ? "The saved item has changed. Reload it before trying again." : result.error || "The project request could not be completed." }, { status: result.status, headers: { "Cache-Control": "private, no-store" } });
}
export const GET = forward;
export const POST = forward;
export const PATCH = forward;
export const DELETE = forward;
