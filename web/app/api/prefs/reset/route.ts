import { NextRequest } from "next/server";
import { api } from "@/lib/server-api";
import { sessionToken } from "@/lib/session";

export async function POST(req: NextRequest) {
  const token = await sessionToken();
  if (!token) return Response.json({ error: "sign in required" }, { status: 401 });
  const body = await req.json().catch(() => ({}));
  const r = await api.post("/me/prefs/reset", body, token);
  return Response.json(r.data, { status: r.status });
}
