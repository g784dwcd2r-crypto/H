// Server-side client for the Disclosure API. The API key stays on the server.

const RAW_BASE = process.env.FILINGS_API_URL || "http://localhost:8000";
// Render's Blueprint hands over the API as a bare host:port on the private network; add the scheme.
const BASE = (/^https?:\/\//.test(RAW_BASE) ? RAW_BASE : `http://${RAW_BASE}`).replace(/\/$/, "");
const KEY = process.env.FILINGS_API_KEY || "";

export type Company = {
  cik: number;
  name: string;
  ticker: string | null;
  exchange: string | null;
  sic: string | null;
  sic_description: string | null;
  fiscal_year_end: string | null;
  is_active: boolean;
  last_financial_report_date: string | null;
};

export type Metrics = Record<string, number | null>;

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
  parent_concept: string | null;
  unit: string | null;
  values: Record<string, number | null>;
};

export type PeriodMode = "as_filed" | "quarterly" | "annual" | "ltm";
export type ColumnOrder = "newest_right" | "newest_left";
export type GridParams = { period_mode?: PeriodMode; restated?: boolean; column_order?: ColumnOrder };

export type GridPeriod = {
  period_label: string;
  filed_label: string;
  period_end: string;
  fiscal_year: number;
  fiscal_quarter: number;
  period_type: string;
  accession: string;
  form: string | null;
  filed_date: string | null;
  filing_index_url: string | null;
  is_provisional: boolean;
  checks_passed: boolean | null;
  basis: "as filed" | "derived" | "restated";
  basis_note: string | null;
  restated_from: string | null;
};

export type Grid = {
  cik: number;
  company_name: string;
  ticker: string | null;
  period_mode: PeriodMode;
  restated: boolean;
  column_order: ColumnOrder;
  periods: GridPeriod[];
  statements: { code: string; name: string; lines: GridLine[] }[];
};

/** Everything the export dialog can set; mirrors ExportOptions on the API plus the grid parameters. */
export type ExportConfig = {
  period_mode: PeriodMode;
  restated: boolean;
  column_order: ColumnOrder;
  limit: number;
  layout: "sheet_per_statement" | "one_sheet";
  orientation: "periods_across" | "periods_down";
  subtotals: "values" | "formulas";
  include_source: boolean;
  include_checks: boolean;
  include_concepts: boolean;
  include_filed_dates: boolean;
  scale: "units" | "thousands" | "millions" | "billions";
  negative_style: "parentheses" | "minus";
  filename: string;
  statements: string[];
};

export const EXPORT_DEFAULTS: ExportConfig = {
  period_mode: "as_filed",
  restated: false,
  column_order: "newest_right",
  limit: 8,
  layout: "sheet_per_statement",
  orientation: "periods_across",
  subtotals: "values",
  include_source: true,
  include_checks: true,
  include_concepts: true,
  include_filed_dates: true,
  scale: "units",
  negative_style: "parentheses",
  filename: "{ticker}-statements",
  statements: ["IS", "BS", "CF", "EQ", "CI"],
};

export function exportQuery(cik: string, cfg: Partial<ExportConfig>, periods?: string): string {
  const c = { ...EXPORT_DEFAULTS, ...cfg };
  const q = new URLSearchParams({
    cik,
    limit: String(c.limit),
    period_mode: c.period_mode,
    restated: String(c.restated),
    column_order: c.column_order,
    layout: c.layout,
    orientation: c.orientation,
    subtotals: c.subtotals,
    include: (["source", "checks", "concepts", "filed_dates"] as const).filter((k) => c[`include_${k}` as keyof ExportConfig]).join(","),
    scale: c.scale,
    negative_style: c.negative_style,
    filename: c.filename,
    statements: c.statements.join(","),
  });
  if (periods) q.set("periods", periods);
  return q.toString();
}

export type Proposal = { id: string; key: string; value: unknown; companies: string[]; current: unknown; message: string };
export type TouchReport = {
  days: number;
  events: number;
  users: number;
  prefs: { key: string; writes: number; users: number; inferred: number; scopes: Record<string, number>; top_values: { value: unknown; n: number }[] }[];
  ui: { name: string; count: number; users: number }[];
};
export type Dashboard = {
  totals: { companies?: number; filings?: number; periods?: number; filings_with_statements?: number };
  filings_per_day: { filed_date: string; filings: number }[];
  runs: { run_id: string; kind: string; status: string; started_at: string; duration_seconds: number | null; new_filings: number | null; ciks_refreshed: number | null; statements_built: number | null }[];
  checks_by_fiscal_year: { fiscal_year: number; periods: number; passed: number; applicable: number; provisional: number; pass_rate: number | null }[];
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
  exportUrl: (cik: string, query: URLSearchParams) => `${BASE}/companies/${encodeURIComponent(cik)}/export.xlsx?${query.toString()}`,
  proposals: (session: string) => get<{ proposals: Proposal[] }>("/me/proposals", 0, session),
  dashboard: (days = 30) => get<Dashboard>(`/metrics?days=${days}`, 60),
  touchReport: (days = 30) => get<TouchReport>(`/metrics/prefs?days=${days}`, 60),
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
