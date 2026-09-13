// Start Google sign-in: send the person to Google's consent screen with a state cookie.
import { NextRequest, NextResponse } from "next/server";
import { api } from "@/lib/api";

export async function GET(req: NextRequest) {
  const cfg = await api.authConfig().catch(() => null);
  if (!cfg?.google_client_id) return NextResponse.redirect(new URL("/signin?error=google", req.nextUrl.origin));
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
  res.cookies.set("fh_oauth_state", state, { httpOnly: true, sameSite: "lax", path: "/", maxAge: 600 });
  return res;
}
