import { NextRequest, NextResponse } from "next/server";
import { api } from "@/lib/server-api";
import { SESSION_COOKIE, SESSION_DAYS } from "@/lib/session";
import { deviceLabel } from "@/lib/device-label";

export async function GET(req: NextRequest) {
  const code = req.nextUrl.searchParams.get("code") ?? "";
  const state = req.nextUrl.searchParams.get("state") ?? "";
  const expected = req.cookies.get("fh_oauth_state")?.value;
  if (!code || !state || state !== expected) return NextResponse.redirect(new URL("/signin?error=google", req.nextUrl.origin));
  const r = await api.post("/auth/google", { code, redirect_uri: `${req.nextUrl.origin}/auth/google/callback`, device_label: deviceLabel(req.headers.get("user-agent") ?? "") });
  if (!r.ok || typeof r.data.session !== "string") return NextResponse.redirect(new URL("/signin?error=google", req.nextUrl.origin));
  const res = NextResponse.redirect(new URL("/", req.nextUrl.origin));
  res.cookies.set(SESSION_COOKIE, r.data.session, { httpOnly: true, sameSite: "lax", secure: req.nextUrl.protocol === "https:", path: "/", maxAge: SESSION_DAYS * 86400 });
  res.cookies.set("fh_oauth_state", "", { path: "/", maxAge: 0 });
  return res;
}
