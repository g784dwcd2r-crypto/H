import { NextRequest, NextResponse } from "next/server";
import { sameOriginMutation, workspaceRequest } from "@/lib/workspace-api";
const headers = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };
export async function POST(request: NextRequest) {
  if (!sameOriginMutation(request)) return NextResponse.json({ error: "The request origin does not match." }, { status: 403, headers });
  const raw = await request.text();
  if (raw.length > 12000) return NextResponse.json({ error: "Your message is too long." }, { status: 413, headers });
  let value;
  try { value = JSON.parse(raw); } catch { return NextResponse.json({ error: "A JSON request is required." }, { status: 400, headers }); }
  const body = { name: value?.name, email: value?.email, organisation: value?.organisation, region: value?.region, workflow: value?.workflow, request_id: value?.request_id };
  const result = await workspaceRequest("/demo-requests", "POST", body);
  return NextResponse.json(result.ok ? result.data : { error: result.error || "We could not confirm your request. Your message is still here; please try again." }, { status: result.status, headers: { ...headers, ...(result.status === 429 && result.retryAfter ? { "Retry-After": result.retryAfter } : {}) } });
}
