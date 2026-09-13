// Inferred proposals ("you chose this on three companies; make it your default?").
import { NextRequest } from "next/server";
import { api } from "@/lib/api";
import { sessionToken } from "@/lib/session";

export async function GET() {
  const token = await sessionToken();
  if (!token) return Response.json({ proposals: [] });
  try {
    return Response.json(await api.proposals(token));
  } catch {
    return Response.json({ proposals: [] });
  }
}

export async function POST(req: NextRequest) {
  const token = await sessionToken();
  if (!token) return Response.json({ error: "sign in required" }, { status: 401 });
  const body = await req.json().catch(() => ({}));
  const r = await api.post("/me/proposals", body, token);
  return Response.json(r.data, { status: r.status });
}
