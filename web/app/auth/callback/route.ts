// The link in the sign-in email lands here: the API turns the one-time token into a session.
import { NextRequest, NextResponse } from "next/server";
import { api } from "@/lib/server-api";
import { SESSION_COOKIE, SESSION_DAYS } from "@/lib/session";
import { deviceLabel } from "@/lib/device-label";
import { authHref, authRegion, REGION_COOKIE, safeAuthNext } from "@/lib/auth-navigation";

export async function GET(req: NextRequest) {
  const token = req.nextUrl.searchParams.get("token") ?? "";
  const next = safeAuthNext(req.nextUrl.searchParams.get("next"));
  const region = authRegion(req.nextUrl.searchParams.get("region"), req.cookies.get(REGION_COOKIE)?.value);
  const r = await api.post("/auth/verify", { token, device_label: deviceLabel(req.headers.get("user-agent") ?? "") }).catch(() => null);
  if (!r?.ok || typeof r.data.session !== "string") {
    return NextResponse.redirect(new URL(authHref("/signin", next, region, "link"), req.nextUrl.origin));
  }
  const res = NextResponse.redirect(new URL(next, req.nextUrl.origin));
  res.cookies.set(SESSION_COOKIE, r.data.session, {
    httpOnly: true,
    sameSite: "lax",
    secure: req.nextUrl.protocol === "https:",
    path: "/",
    maxAge: SESSION_DAYS * 86400,
  });
  if (region) res.cookies.set(REGION_COOKIE, region, { sameSite: "lax", secure: req.nextUrl.protocol === "https:", path: "/", maxAge: 31536000 });
  return res;
}
