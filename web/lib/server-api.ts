import "server-only";
import { cookies } from "next/headers";
import { verifyVisitor, VISITOR_COOKIE, VISITOR_HEADER } from "@/lib/gateway-identity";
import type { AuthConfig, Company, Coverage, Dashboard, Documents, Filing, FilingSearch, Grid, GridParams, NextExpected, Peer, Period, Pref, Proposal, ReaderDoc, RecentFiling, Resolved, TouchReport, User } from "@/lib/api";

// Only the trusted web gateway possesses the service API key.

const RAW_BASE = process.env.FILINGS_API_URL || "http://localhost:8000";
// Render's Blueprint hands over the API as a bare host:port on the private network; add the scheme.
const BASE = (/^https?:\/\//.test(RAW_BASE) ? RAW_BASE : `http://${RAW_BASE}`).replace(/\/$/, "");
const KEY = process.env.FILINGS_API_KEY || "";


/** Construct an allowlist; never forward caller-supplied X-API-Key, X-Session or identity headers. */
export async function requestHeaders(session?: string | null): Promise<Record<string, string>> {
  const result: Record<string, string> = {};
  if (KEY) result["X-API-Key"] = KEY;
  try {
    const jar = await cookies();
    const visitor = await verifyVisitor(jar.get(VISITOR_COOKIE)?.value, KEY);
    if (visitor) result[VISITOR_HEADER] = visitor;
    // Public reads also identify a signed-in user. The API verifies the session before using its ID.
    const token = session ?? jar.get("fh_session")?.value;
    if (token) result["X-Session"] = token;
  } catch {
    // Calls outside a request (builds/scripts) use the API's direct-peer fallback.
    if (session) result["X-Session"] = session;
  }
  return result;
}

async function get<T>(path: string, revalidate = 300, session?: string | null): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: await requestHeaders(session),
    ...(session ? { cache: "no-store" as const } : { next: { revalidate } }),
  });
  if (res.status === 404) throw new NotFound(path);
  if (res.status === 401) throw new Unauthorized(path);
  if (!res.ok) throw new Error(`API ${res.status} for ${path}`);
  return (await res.json()) as T;
}

export class NotFound extends Error {}
export class Unauthorized extends Error {}

export const api = {
  search: (q: string) => get<{ results: Company[] }>(`/search?q=${encodeURIComponent(q)}`, 60),
  company: (cik: string) =>
    get<{
      company: Company;
      tickers: { ticker: string; exchange: string | null }[];
      latest_period: Period | null;
      next_expected: NextExpected;
      headline_preset: string[];
      metric_labels: Record<string, string>;
    }>(`/companies/${encodeURIComponent(cik)}`),
  periods: (cik: string) => get<{ periods: Period[] }>(`/companies/${encodeURIComponent(cik)}/periods?limit=60`),
  filings: (cik: string) => get<{ filings: Filing[] }>(`/companies/${encodeURIComponent(cik)}/filings?limit=200`),
  statements: (cik: string, periods?: string, limit = 8, params: GridParams = {}) => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (periods) q.set("periods", periods);
    if (params.period_mode) q.set("period_mode", params.period_mode);
    if (params.restated) q.set("restated", "true");
    if (params.column_order) q.set("column_order", params.column_order);
    if (params.as_of) q.set("as_of", params.as_of);
    return get<Grid>(`/companies/${encodeURIComponent(cik)}/statements?${q.toString()}`);
  },
  peers: (cik: string) => get<{ cik: number; sic: string | null; sic_description: string | null; peers: Peer[] }>(`/companies/${encodeURIComponent(cik)}/peers`),
  documents: (cik: string, limit = 8) => get<Documents>(`/companies/${encodeURIComponent(cik)}/documents?limit=${limit}`, 60),
  document: (cik: string, accession: string, file?: string) =>
    get<ReaderDoc>(`/companies/${encodeURIComponent(cik)}/filings/${encodeURIComponent(accession)}/document` + (file ? `?file=${encodeURIComponent(file)}` : ""), 3600),
  searchFilings: (cik: string, q: string, filings = 20) =>
    get<FilingSearch>(`/companies/${encodeURIComponent(cik)}/search?q=${encodeURIComponent(q)}&filings=${filings}`, 300),
  recent: (ciks: number[], days = 14) => get<{ filings: RecentFiling[] }>(`/filings/recent?ciks=${ciks.join(",")}&days=${days}`, 60),
  post: async (path: string, body: unknown, session?: string | null, method: "POST" | "PUT" | "DELETE" = "POST") => {
    const res = await fetch(`${BASE}${path}`, {
      method,
      headers: { "Content-Type": "application/json", ...await requestHeaders(session) },
      body: method === "DELETE" ? undefined : JSON.stringify(body ?? {}),
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data } as { ok: boolean; status: number; data: Record<string, unknown> };
  },
  authConfig: () => get<AuthConfig>("/auth/config", 300),
  me: (session: string) => get<{ user: User }>("/me", 0, session),
  listPrefs: (session: string) => get<{ user_id: string; prefs: Pref[]; defaults: Record<string, unknown> }>("/me/prefs", 0, session),
  resolvePrefs: (session: string, ctx: { cik?: string | number; sic?: string; statement?: string }) => {
    const q = new URLSearchParams();
    if (ctx.cik !== undefined) q.set("cik", String(ctx.cik));
    if (ctx.sic) q.set("sic", ctx.sic);
    if (ctx.statement) q.set("statement", ctx.statement);
    return get<{ prefs: Resolved }>(`/me/prefs/resolve?${q.toString()}`, 0, session);
  },
  exportUrl: (cik: string, query: URLSearchParams) => `${BASE}/companies/${encodeURIComponent(cik)}/export.xlsx?${query.toString()}`,
  proposals: (session: string) => get<{ proposals: Proposal[] }>("/me/proposals", 0, session),
  dashboard: (days: number, session: string) => get<Dashboard>(`/metrics?days=${days}`, 0, session),
  touchReport: (days: number, session: string) => get<TouchReport>(`/metrics/prefs?days=${days}`, 0, session),
  coverage: () => get<Coverage>("/coverage", 60),
  subscription: (session: string) => get<{ subscribed: boolean; ciks: number[] }>("/subscriptions", 0, session),
  exportResponse: async (cik: string, query: URLSearchParams) => fetch(`${BASE}/companies/${encodeURIComponent(cik)}/export.xlsx?${query.toString()}`, { headers: await requestHeaders(), cache: "no-store" }),
};
