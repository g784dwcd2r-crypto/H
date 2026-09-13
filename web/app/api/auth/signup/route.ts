import { NextRequest, NextResponse } from "next/server";
import { api } from "@/lib/server-api";
import { authRegion, REGION_COOKIE, safeAuthNext } from "@/lib/auth-navigation";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  if (!body || typeof body !== "object" || Array.isArray(body)) return Response.json({ detail: "Provide your account details." }, { status: 400 });
  const next = safeAuthNext(body.next);
  const region = authRegion(body.region, req.cookies.get(REGION_COOKIE)?.value);
  const payload = { ...body, next: next !== "/" ? next : undefined, region: region ?? undefined };
  try {
    const r = await api.post("/auth/signup", payload);
    const response = NextResponse.json(r.data, { status: r.status });
    if (region) response.cookies.set(REGION_COOKIE, region, { path: "/", maxAge: 31536000, sameSite: "lax", secure: req.nextUrl.protocol === "https:" });
    return response;
  } catch { return Response.json({ detail: "Sign-up is temporarily unavailable. Please try again." }, { status: 503 }); }
}
