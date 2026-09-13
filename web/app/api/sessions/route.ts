import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, sessionToken } from "@/lib/session";
import { sameOriginMutation, workspaceRequest } from "@/lib/workspace-api";
import type { SessionsResponse } from "@/lib/workspace-types";

export async function GET() {
  if (!await sessionToken()) return Response.json({ error: "Sign in to manage your sessions." }, { status: 401 });
  const result = await workspaceRequest<SessionsResponse>("/me/sessions");
  return Response.json(result.data ?? { error: "Sessions could not be loaded. Please try again." }, { status: result.status });
}

export async function DELETE(request: NextRequest) {
  if (!sameOriginMutation(request)) return Response.json({ error: "Request origin does not match." }, { status: 403 });
  if (!await sessionToken()) return Response.json({ error: "Sign in again to manage sessions." }, { status: 401 });
  const id = request.nextUrl.searchParams.get("id");
  if (!id || id.length > 200) return Response.json({ error: "A valid session is required." }, { status: 400 });
  const result = await workspaceRequest<{ revoked: boolean; current: boolean }>(`/me/sessions/${encodeURIComponent(id)}`, "DELETE");
  const response = NextResponse.json(result.data ?? { error: result.status === 401 ? "Your session has expired. Please sign in again." : "The session could not be revoked. Please try again." }, { status: result.status });
  if (result.status === 401 || result.ok && result.data?.current) response.cookies.set(SESSION_COOKIE, "", { httpOnly: true, path: "/", maxAge: 0 });
  return response;
}

export async function POST(request: NextRequest) {
  if (!sameOriginMutation(request)) return Response.json({ error: "Request origin does not match." }, { status: 403 });
  if (!await sessionToken()) return Response.json({ error: "Sign in again to manage sessions." }, { status: 401 });
  const result = await workspaceRequest<{ revoked: number }>("/me/sessions/revoke-others", "POST");
  return Response.json(result.data ?? { error: "Other sessions could not be revoked. Please try again." }, { status: result.status });
}
