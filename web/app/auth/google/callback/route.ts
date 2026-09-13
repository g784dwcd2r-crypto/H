import { NextRequest, NextResponse } from "next/server";
import { api } from "@/lib/server-api";
import { SESSION_COOKIE, SESSION_DAYS } from "@/lib/session";
import { deviceLabel } from "@/lib/device-label";
import { authHref, OAUTH_COOKIE, OAUTH_COOKIE_PATH, readOAuthContext, REGION_COOKIE } from "@/lib/auth-navigation";

export async function GET(req: NextRequest) {
  const code = req.nextUrl.searchParams.get("code") ?? "";
  const state = req.nextUrl.searchParams.get("state") ?? "";
  const context = readOAuthContext(req.cookies.get(OAUTH_COOKIE)?.value, state);
  const failure = () => {
    const response = NextResponse.redirect(new URL(authHref("/signin", context?.next ?? "/", context?.region ?? null, "google"), req.nextUrl.origin));
    response.cookies.set(OAUTH_COOKIE, "", { path: OAUTH_COOKIE_PATH, maxAge: 0 });
    return response;
  };
  if (!code || !context) return failure();
  const r = await api.post("/auth/google", { code, redirect_uri: `${req.nextUrl.origin}/auth/google/callback`, device_label: deviceLabel(req.headers.get("user-agent") ?? "") }).catch(() => null);
  if (!r?.ok || typeof r.data.session !== "string") return failure();
  const res = NextResponse.redirect(new URL(context.next, req.nextUrl.origin));
  res.cookies.set(SESSION_COOKIE, r.data.session, { httpOnly: true, sameSite: "lax", secure: req.nextUrl.protocol === "https:", path: "/", maxAge: SESSION_DAYS * 86400 });
  res.cookies.set(OAUTH_COOKIE, "", { path: OAUTH_COOKIE_PATH, maxAge: 0 });
  if (context.region) res.cookies.set(REGION_COOKIE, context.region, { path: "/", maxAge: 31536000, sameSite: "lax", secure: req.nextUrl.protocol === "https:" });
  return res;
}
