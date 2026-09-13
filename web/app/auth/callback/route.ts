// The link in the sign-in email lands here: the API turns the one-time token into a session.
import { NextRequest, NextResponse } from "next/server";
import { api } from "@/lib/api";
import { SESSION_COOKIE, SESSION_DAYS } from "@/lib/session";

export async function GET(req: NextRequest) {
  const token = req.nextUrl.searchParams.get("token") ?? "";
  const r = await api.post("/auth/verify", { token });
  if (!r.ok || typeof r.data.session !== "string") {
    return NextResponse.redirect(new URL("/signin?error=link", req.nextUrl.origin));
  }
  const res = NextResponse.redirect(new URL(req.nextUrl.searchParams.get("next") ?? "/", req.nextUrl.origin));
  res.cookies.set(SESSION_COOKIE, r.data.session, {
    httpOnly: true,
    sameSite: "lax",
    secure: req.nextUrl.protocol === "https:",
    path: "/",
    maxAge: SESSION_DAYS * 86400,
  });
  return res;
}
