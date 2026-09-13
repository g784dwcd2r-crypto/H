import { NextRequest } from "next/server";
import { api } from "@/lib/server-api";
import { sessionToken } from "@/lib/session";

export async function GET() {
  const token = await sessionToken();
  if (!token) return Response.json({ error: "sign in required" }, { status: 401 });
  // The preferences response includes the owner; only return this account's watchlist.
  try {
    const result = await api.listPrefs(token);
    const pref = result.prefs.find(p => p.scope === "global" && p.key === "watchlist");
    return Response.json({ user_id: result.user_id, companies: Array.isArray(pref?.value) ? pref.value : [] });
  } catch { return Response.json({ error: "watchlist unavailable" }, { status: 502 }); }
}

export async function POST(req: NextRequest) {
  const token = await sessionToken();
  if (!token) return Response.json({ error: "sign in required" }, { status: 401 });
  const body = await req.json().catch(() => ({}));
  const result = await api.post("/me/watchlist", body, token);
  return Response.json(result.data, { status: result.status });
}
