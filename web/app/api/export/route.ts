// Streams the workbook from the Filings Hub API so the API key never reaches the browser.
// Every export option is passed through as-is; the API validates them.
import { NextRequest } from "next/server";
import { api } from "@/lib/api";

export async function GET(req: NextRequest) {
  const q = new URLSearchParams(req.nextUrl.searchParams);
  const cik = q.get("cik");
  if (!cik) return new Response("cik required", { status: 400 });
  q.delete("cik");
  if (!q.get("limit")) q.set("limit", "8");
  const upstream = await fetch(api.exportUrl(cik, q), { headers: api.key ? { "X-API-Key": api.key } : {} });
  if (!upstream.ok) return new Response(`export failed (${upstream.status}): ${await upstream.text()}`, { status: upstream.status });
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "Content-Disposition": upstream.headers.get("content-disposition") ?? `attachment; filename="${cik}-statements.xlsx"`,
    },
  });
}
