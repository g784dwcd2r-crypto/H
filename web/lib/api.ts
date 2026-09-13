// Server-side client for the Filings Hub API. The API key stays on the server.

const RAW_BASE = process.env.FILINGS_API_URL || "http://localhost:8000";
// Render's Blueprint hands over the API as a bare host:port on the private network; add the scheme.
const BASE = (/^https?:\/\//.test(RAW_BASE) ? RAW_BASE : `http://${RAW_BASE}`).replace(/\/$/, "");
const KEY = process.env.FILINGS_API_KEY || "";

export type Company = {
  cik: number;
  name: string;
  ticker: string | null;
  exchange: string | null;
  sic_description: string | null;
  fiscal_year_end: string | null;
  is_active: boolean;
  last_financial_report_date: string | null;
};

export type Metrics = {
  revenue: number | null;
  net_income: number | null;
  eps_diluted: number | null;
  total_assets: number | null;
  operating_cash_flow: number | null;
};

export type Period = {
  metrics?: Metrics;
  period_label: string;
  period_end: string;
  period_type: string;
  results_accession: string;
  results_form: string | null;
  results_filed_date: string | null;
  results_primary_doc_url: string | null;
  results_filing_index_url?: string | null;
  earnings_release_accession: string | null;
  earnings_release_filed_date: string | null;
  earnings_release_primary_doc_url: string | null;
  amendment_accessions: string[] | null;
  statements_source: "fsds" | "facts_fallback" | null;
  checks_passed: boolean | null;
};

export type Filing = {
  accession: string;
  form: string;
  label: string;
  filed_date: string;
  report_date: string | null;
  primary_doc_url: string | null;
  filing_index_url: string | null;
};

export type GridLine = {
  key: string;
  concept: string;
  label: string;
  is_abstract: boolean;
  is_subtotal: boolean;
  unit: string | null;
  values: Record<string, number | null>;
};

export type Grid = {
  cik: number;
  company_name: string;
  ticker: string | null;
  periods: {
    period_label: string;
    period_end: string;
    accession: string;
    form: string | null;
    filed_date: string | null;
    filing_index_url: string | null;
    is_provisional: boolean;
    checks_passed: boolean | null;
  }[];
  statements: { code: string; name: string; lines: GridLine[] }[];
};

export type Doc = {
  seq: number;
  doc_type: string;
  description: string;
  filename: string;
  url: string;
  size: number;
  label: string;
  kind: "primary" | "release" | "presentation" | "letter" | "supplement" | "transcript" | "exhibit" | "support";
  is_primary: boolean;
};

export type Documents = { cik: number; documents: Record<string, Doc[]>; failures: string[]; fetch_enabled: boolean };

export type Peer = {
  cik: number;
  name: string;
  ticker: string | null;
  exchange: string | null;
  fiscal_year: number | null;
  revenue: number | null;
  net_income: number | null;
  total_assets: number | null;
};

export type ReaderDoc = {
  cik: number;
  accession: string;
  form: string;
  filed_date: string | null;
  filename: string;
  source_url: string;
  html: string;
  toc: { id: string; title: string }[];
  title: string;
};

export type SearchHit = { before: string; match: string; after: string; snippet: string };
export type FilingSearch = {
  cik: number;
  query: string;
  searched: number;
  fetch_enabled: boolean;
  results: { accession: string; form: string; label: string; filed_date: string; filename: string; hits: SearchHit[] }[];
};

export type RecentFiling = {
  cik: number;
  name: string | null;
  ticker: string | null;
  accession: string;
  form: string;
  filed_date: string;
  items: string[] | null;
  primary_doc_url: string | null;
  filing_index_url: string | null;
  label: string;
  is_results: boolean;
};

export type NextExpected = {
  period_label: string;
  period_end: string;
  expected_results_filed_date: string | null;
  expected_earnings_release_date: string | null;
} | null;

function headers(session?: string | null): Record<string, string> {
  const h: Record<string, string> = {};
  if (KEY) h["X-API-Key"] = KEY;
  if (session) h["X-Session"] = session;
  return h;
}

async function get<T>(path: string, revalidate = 300, session?: string | null): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: headers(session),
    ...(session ? { cache: "no-store" as const } : { next: { revalidate } }),
  });
  if (res.status === 404) throw new NotFound(path);
  if (res.status === 401) throw new Unauthorized(path);
  if (!res.ok) throw new Error(`API ${res.status} for ${path}`);
  return (await res.json()) as T;
}

export class NotFound extends Error {}
export class Unauthorized extends Error {}

export type User = {
  id: string;
  email: string;
  plan: string;
  locale: string;
  timezone: string;
  created_at: string;
  first_name?: string;
  last_name?: string;
  company?: string;
  phone?: string;
  role?: string;
  specialty?: string;
  title?: string;
  country?: string;
  marketing_opt_in?: boolean;
};
export type Pref = { scope: string; scope_key: string; key: string; value: unknown; source: string; updated_at: string };
export type Resolved = Record<string, { value: unknown; scope: string; scope_key: string; source: string }>;
export type AuthConfig = { email_link: boolean; google_client_id: string | null; site_url: string; business_email_only?: boolean };

export const api = {
  search: (q: string) => get<{ results: Company[] }>(`/search?q=${encodeURIComponent(q)}`, 60),
  company: (cik: string) =>
    get<{ company: Company; tickers: { ticker: string; exchange: string | null }[]; latest_period: Period | null; next_expected: NextExpected }>(
      `/companies/${encodeURIComponent(cik)}`,
    ),
  periods: (cik: string) => get<{ periods: Period[] }>(`/companies/${encodeURIComponent(cik)}/periods?limit=60`),
  filings: (cik: string) => get<{ filings: Filing[] }>(`/companies/${encodeURIComponent(cik)}/filings?limit=200`),
  statements: (cik: string, periods?: string, limit = 8) =>
    get<Grid>(
      `/companies/${encodeURIComponent(cik)}/statements?limit=${limit}` + (periods ? `&periods=${encodeURIComponent(periods)}` : ""),
    ),
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
      headers: { "Content-Type": "application/json", ...headers(session) },
      body: method === "DELETE" ? undefined : JSON.stringify(body ?? {}),
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data } as { ok: boolean; status: number; data: Record<string, unknown> };
  },
  authConfig: () => get<AuthConfig>("/auth/config", 300),
  me: (session: string) => get<{ user: User }>("/me", 0, session),
  listPrefs: (session: string) => get<{ prefs: Pref[]; defaults: Record<string, unknown> }>("/me/prefs", 0, session),
  resolvePrefs: (session: string, ctx: { cik?: string | number; sic?: string; statement?: string }) => {
    const q = new URLSearchParams();
    if (ctx.cik !== undefined) q.set("cik", String(ctx.cik));
    if (ctx.sic) q.set("sic", ctx.sic);
    if (ctx.statement) q.set("statement", ctx.statement);
    return get<{ prefs: Resolved }>(`/me/prefs/resolve?${q.toString()}`, 0, session);
  },
  exportUrl: (cik: string, periods?: string, limit = 8) =>
    `${BASE}/companies/${encodeURIComponent(cik)}/export.xlsx?limit=${limit}` + (periods ? `&periods=${encodeURIComponent(periods)}` : ""),
  key: KEY,
};

export const fmtDate = (d: string | null | undefined) => (d ? new Date(d + "T00:00:00Z").toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" }) : "–");

export const fmtMoney = (v: number | null | undefined): string => {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const a = Math.abs(v);
  const s =
    a >= 1e12 ? `${(a / 1e12).toFixed(2)}T` : a >= 1e9 ? `${(a / 1e9).toFixed(1)}B` : a >= 1e6 ? `${(a / 1e6).toFixed(1)}M` : a >= 1e3 ? `${(a / 1e3).toFixed(0)}K` : a.toFixed(0);
  return v < 0 ? `(${s})` : s;
};

export const fmtEps = (v: number | null | undefined): string =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : v < 0 ? `(${Math.abs(v).toFixed(2)})` : v.toFixed(2);

export const isAnnual = (form: string | null | undefined) => !!form && (form.startsWith("10-K") || form.endsWith("-F") || form.includes("-F/"));
