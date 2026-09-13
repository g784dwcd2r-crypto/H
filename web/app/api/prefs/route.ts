// Preference reads and writes for the signed-in person; the session cookie never leaves the server.
import { NextRequest } from "next/server";
import { api } from "@/lib/api";
import { sessionToken } from "@/lib/session";

export async function GET() {
  const token = await sessionToken();
  if (!token) return Response.json({ error: "sign in required" }, { status: 401 });
  try {
    return Response.json(await api.listPrefs(token));
  } catch {
    return Response.json({ error: "unavailable" }, { status: 502 });
  }
}

export async function PUT(req: NextRequest) {
  const token = await sessionToken();
  if (!token) return Response.json({ error: "sign in required" }, { status: 401 });
  const body = await req.json().catch(() => ({}));
  const r = await api.post("/me/prefs", body, token, "PUT");
  return Response.json(r.data, { status: r.status });
}

export async function DELETE(req: NextRequest) {
  const token = await sessionToken();
  if (!token) return Response.json({ error: "sign in required" }, { status: 401 });
  const q = req.nextUrl.searchParams;
  const r = await api.post(`/me/prefs?scope=${encodeURIComponent(q.get("scope") ?? "")}&scope_key=${encodeURIComponent(q.get("scope_key") ?? "")}&key=${encodeURIComponent(q.get("key") ?? "")}`, null, token, "DELETE");
  return Response.json(r.data, { status: r.status });
}
