import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/session";
import { sameOriginMutation, workspaceRequest } from "@/lib/workspace-api";

export async function POST(req: NextRequest) {
  if (!sameOriginMutation(req)) return NextResponse.json({ error: "Request origin does not match." }, { status: 403 });
  const result = await workspaceRequest("/auth/logout", "POST");
  if (!result.ok && result.status !== 401) return NextResponse.redirect(new URL("/settings/security?error=signout", req.nextUrl.origin), { status: 303 });
  const res = NextResponse.redirect(new URL("/", req.nextUrl.origin), { status: 303 });
  res.cookies.set(SESSION_COOKIE, "", { httpOnly: true, path: "/", maxAge: 0 });
  return res;
}
