// UI events for the option touch report; only signed-in people are counted.
import { NextRequest } from "next/server";
import { api } from "@/lib/server-api";
import { sessionToken } from "@/lib/session";

export async function POST(req: NextRequest) {
  const token = await sessionToken();
  if (!token) return Response.json({ ok: false }, { status: 401 });
  const body = await req.json().catch(() => ({}));
  const r = await api.post("/me/events", body, token);
  return Response.json(r.data, { status: r.status });
}
