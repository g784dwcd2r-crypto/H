import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

type Context = { params: Promise<{ segments?: string[] }> };
const rawBase = process.env.FILINGS_API_URL || "http://localhost:8000";
const base = (/^https?:\/\//.test(rawBase) ? rawBase : `http://${rawBase}`).replace(/\/$/, "");
const origin = process.env.PLATFORM_ADMIN_ORIGIN || "";
const secure = origin.startsWith("https://");
const cookieName = secure ? "__Host-disclosure_admin" : "disclosure_admin_dev";
const noStore = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };

async function forward(request: NextRequest, context: Context) {
  const { segments = [] } = await context.params;
  const path = segments.join("/");
  const read = /^(session|overview|users(?:\/[a-z0-9]{32})?|organizations(?:\/[a-z0-9]{32})?|audit|research|jobs|sources|configuration)$/;
  const write = /^(login|password|reauthenticate|logout|configuration|users\/[a-z0-9]{32}\/(status|revoke-sessions)|organizations\/[a-z0-9]{32}\/members\/[a-z0-9]{32}|jobs\/[a-z0-9]{32}\/(retry|cancel))$/;
  if (!(request.method === "GET" ? read : write).test(path)) return NextResponse.json({ error: "Administrator route not found." }, { status: 404, headers: noStore });
  if (!origin) return NextResponse.json({ error: "Administrator gateway is not configured." }, { status: 503, headers: noStore });
  if (request.method !== "GET" && request.headers.get("origin") !== origin) return NextResponse.json({ error: "The request origin does not match." }, { status: 403, headers: noStore });
  const jar = await cookies();
  const token = jar.get(cookieName)?.value;
  if (path !== "login" && !token) return NextResponse.json({ error: "Platform administrator sign-in required." }, { status: 401, headers: noStore });
  const headers: Record<string, string> = { "Content-Type": "application/json", "X-API-Key": process.env.FILINGS_API_KEY || "" };
  if (token) headers["X-Admin-Session"] = token;
  if (request.method !== "GET") {
    headers.Origin = request.headers.get("origin") || "";
    headers["X-Admin-CSRF"] = request.headers.get("x-admin-csrf") || "";
  }
  let body: string | undefined;
  if (request.method !== "GET") {
    body = await request.text();
    if (body.length > 12000) return NextResponse.json({ error: "Administrator request is too large." }, { status: 413, headers: noStore });
    try { JSON.parse(body); } catch { return NextResponse.json({ error: "A JSON request is required." }, { status: 400, headers: noStore }); }
  }
  const query = new URLSearchParams();
  for (const key of ["q", "limit", "offset"]) {
    const value = request.nextUrl.searchParams.get(key);
    if (value !== null) query.set(key, value);
  }
  try {
    const upstream = await fetch(`${base}/platform-admin/${path}${query.size ? "?" + query : ""}`, {
      method: request.method, headers, body, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(20000),
    });
    let payload;
    try { payload = await upstream.json(); } catch { return NextResponse.json({ error: "The administrator service returned an invalid response." }, { status: 502, headers: noStore }); }
    const issued = typeof payload.token === "string" ? payload.token : null;
    delete payload.token; // Opaque sessions stay server-side in the HttpOnly cookie.
    const alreadySignedOut = path === "logout" && upstream.status === 401;
    const response = NextResponse.json(alreadySignedOut ? { revoked: true, already_invalid: true } : upstream.ok ? payload : { error: typeof payload.detail === "string" ? payload.detail : "The administrator request failed." }, { status: alreadySignedOut ? 200 : upstream.status, headers: noStore });
    if (upstream.ok && issued) response.cookies.set(cookieName, issued, { httpOnly: true, secure, sameSite: "strict", path: "/", expires: new Date(payload.expires_at) });
    if ((path === "logout" && (upstream.ok || upstream.status === 401)) || (path === "session" && upstream.status === 401)) response.cookies.set(cookieName, "", { httpOnly: true, secure, sameSite: "strict", path: "/", maxAge: 0 });
    return response;
  } catch {
    return NextResponse.json({ error: "The administrator service is unavailable. The result was not confirmed; reload before retrying a change." }, { status: 503, headers: noStore });
  }
}

export const GET = forward;
export const POST = forward;
