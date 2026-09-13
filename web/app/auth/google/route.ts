// Start Google sign-in: send the person to Google's consent screen with a state cookie.
import { NextRequest, NextResponse } from "next/server";
import { api } from "@/lib/server-api";
import { authHref, authRegion, OAUTH_COOKIE, OAUTH_COOKIE_PATH, REGION_COOKIE, safeAuthNext } from "@/lib/auth-navigation";

export async function GET(req: NextRequest) {
  const next = safeAuthNext(req.nextUrl.searchParams.get("next"));
  const region = authRegion(req.nextUrl.searchParams.get("region"), req.cookies.get(REGION_COOKIE)?.value);
  const cfg = await api.authConfig().catch(() => null);
  if (!cfg?.google_client_id) return NextResponse.redirect(new URL(authHref("/signin", next, region, "google"), req.nextUrl.origin));
  const state = crypto.randomUUID();
  const redirectUri = `${req.nextUrl.origin}/auth/google/callback`;
  const url = new URL("https://accounts.google.com/o/oauth2/v2/auth");
  url.searchParams.set("client_id", cfg.google_client_id);
  url.searchParams.set("redirect_uri", redirectUri);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", "openid email");
  url.searchParams.set("state", state);
  url.searchParams.set("prompt", "select_account");
  const res = NextResponse.redirect(url);
  res.cookies.set(OAUTH_COOKIE, JSON.stringify({ state, next, region }), { httpOnly: true, secure: req.nextUrl.protocol === "https:", sameSite: "lax", path: OAUTH_COOKIE_PATH, maxAge: 600 });
  return res;
}
