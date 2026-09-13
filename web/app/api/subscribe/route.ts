import { NextRequest } from "next/server";
import { api } from "@/lib/server-api";
import { sessionToken } from "@/lib/session";

export async function POST(req: NextRequest) {
  const token = await sessionToken();
  if (!token) return Response.json({ error: "sign in required" }, { status: 401 });
  const body = await req.json().catch(() => ({}));
  const r = await api.post("/subscriptions", { ciks: body.ciks, ownership_flows: body.ownership_flows ?? [] }, token);
  return Response.json(r.data, { status: r.status });
}

export async function GET() {
  const token = await sessionToken();
  if (!token) return Response.json({ error: "sign in required" }, { status: 401 });
  try { return Response.json(await api.subscription(token)); }
  catch { return Response.json({ error: "Alerts could not be loaded" }, { status: 502 }); }
}

export async function DELETE() {
  const token = await sessionToken();
  if (!token) return Response.json({ error: "sign in required" }, { status: 401 });
  const r = await api.post("/subscriptions", null, token, "DELETE");
  return Response.json(r.data, { status: r.status });
}
