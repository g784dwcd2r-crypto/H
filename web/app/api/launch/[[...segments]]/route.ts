import { NextRequest, NextResponse } from "next/server";
import { sameOriginMutation, workspaceRequest } from "@/lib/workspace-api";

const headers = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };
type Context = { params: Promise<{ segments?: string[] }> };
async function forward(request: NextRequest, context: Context) {
  const { segments = [] } = await context.params;
  const path = segments.join("/");
  const upstream = path === "campaign" && request.method === "GET" ? "/launch/campaign" : path === "membership" ? "/me/early-access" : null;
  if (!upstream) return NextResponse.json({ error: "Launch route not found." }, { status: 404, headers });
  let body;
  if (request.method === "POST") {
    if (!sameOriginMutation(request)) return NextResponse.json({ error: "The request origin does not match." }, { status: 403, headers });
    const raw = await request.text();
    if (raw.length > 2000) return NextResponse.json({ error: "Request too large." }, { status: 413, headers });
    try { body = JSON.parse(raw); } catch { return NextResponse.json({ error: "A JSON request is required." }, { status: 400, headers }); }
    body = { region: body?.region, accept_terms: body?.accept_terms };
  }
  const result = await workspaceRequest(upstream, request.method as "GET" | "POST", body);
  return NextResponse.json(result.ok ? result.data : { error: result.error || "Founding membership availability could not be confirmed. Please try again." }, { status: result.status, headers });
}
export const GET = forward;
export const POST = forward;
