// Streams the workbook from the Filings Hub API so the API key never reaches the browser.
import { NextRequest } from "next/server";
import { api } from "@/lib/api";

export async function GET(req: NextRequest) {
  const cik = req.nextUrl.searchParams.get("cik");
  const periods = req.nextUrl.searchParams.get("periods") ?? undefined;
  const limit = parseInt(req.nextUrl.searchParams.get("limit") ?? "8", 10) || 8;
  if (!cik) return new Response("cik required", { status: 400 });
  const upstream = await fetch(api.exportUrl(cik, periods, limit), { headers: api.key ? { "X-API-Key": api.key } : {} });
  if (!upstream.ok) return new Response(`export failed (${upstream.status})`, { status: upstream.status });
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "Content-Disposition": upstream.headers.get("content-disposition") ?? `attachment; filename="${cik}-statements.xlsx"`,
    },
  });
}
