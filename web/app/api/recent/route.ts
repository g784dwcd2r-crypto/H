import { NextRequest } from "next/server";
import { api } from "@/lib/api";

export async function GET(req: NextRequest) {
  const ciks = (req.nextUrl.searchParams.get("ciks") ?? "")
    .split(",")
    .map((s) => parseInt(s, 10))
    .filter((n) => Number.isFinite(n))
    .slice(0, 200);
  const days = Math.min(Math.max(parseInt(req.nextUrl.searchParams.get("days") ?? "14", 10) || 14, 1), 90);
  if (!ciks.length) return Response.json({ filings: [] });
  try {
    return Response.json(await api.recent(ciks, days));
  } catch {
    return Response.json({ filings: [], error: "unavailable" }, { status: 502 });
  }
}
