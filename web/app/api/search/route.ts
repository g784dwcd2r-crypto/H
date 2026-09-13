// Suggest-as-you-type: the browser asks this route, which asks the API with the server-side key.
import { NextRequest } from "next/server";
import { api } from "@/lib/server-api";

export async function GET(req: NextRequest) {
  const q = (req.nextUrl.searchParams.get("q") ?? "").trim();
  if (q.length < 1) return Response.json({ results: [] });
  try {
    const { results } = await api.search(q);
    return Response.json({ results: results.slice(0, 8) });
  } catch {
    return Response.json({ results: [], error: "Company search is temporarily unavailable" }, { status: 503 });
  }
}
