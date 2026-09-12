// Server-side client for the Filings Hub API. The API key stays on the server.

const BASE = (process.env.FILINGS_API_URL || "http://localhost:8000").replace(/\/$/, "");
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

export type Period = {
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

export type NextExpected = {
  period_label: string;
  period_end: string;
  expected_results_filed_date: string | null;
  expected_earnings_release_date: string | null;
} | null;

async function get<T>(path: string, revalidate = 300): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: KEY ? { "X-API-Key": KEY } : {},
    next: { revalidate },
  });
  if (res.status === 404) throw new NotFound(path);
  if (!res.ok) throw new Error(`API ${res.status} for ${path}`);
  return (await res.json()) as T;
}

export class NotFound extends Error {}

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
  exportUrl: (cik: string, periods?: string, limit = 8) =>
    `${BASE}/companies/${encodeURIComponent(cik)}/export.xlsx?limit=${limit}` + (periods ? `&periods=${encodeURIComponent(periods)}` : ""),
  key: KEY,
};

export const fmtDate = (d: string | null | undefined) => (d ? new Date(d + "T00:00:00Z").toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" }) : "–");
