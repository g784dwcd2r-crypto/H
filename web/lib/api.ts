// Shared browser-safe data types, formatting and export configuration. No server credentials.

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

export type ValueSource = {
  accession: string;
  concept: string;
  taxonomy?: string | null;
  period_end: string | null;
  period_start?: string | null;
  qtrs: number | null;
  unit: string | null;
  reported_unit?: string | null;
  unit_note?: string | null;
  date_note?: string | null;
  value: number | null;
  coefficient?: number;
  filed_date?: string | null;
  document_url?: string | null;
  filing_index_url?: string | null;
};
export type ValueMetadata = {
  status: "reported" | "derived" | "unavailable" | "latest_presentation";
  reason?: string | null;
  formula?: string | null;
  sources: ValueSource[];
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
  labels?: Record<string, string>;
  value_metadata?: Record<string, ValueMetadata>;
};

export type PeriodMode = "as_filed" | "quarterly" | "annual" | "ltm";
export type ColumnOrder = "newest_right" | "newest_left";
export type GridParams = { period_mode?: PeriodMode; restated?: boolean; column_order?: ColumnOrder; as_of?: string };

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
  primary_doc_url?: string | null;
  statements_source?: string | null;
  checks_passed: boolean | null;
  basis: "as filed" | "derived" | "restated";
  basis_note: string | null;
  restated_from: string | null;
};

export type Grid = {
  as_of?: string | null;
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

export function exportQuery(cik: string, cfg: Partial<ExportConfig>, periods?: string, asOf?: string): string {
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
  // A cutoff is explicitly supplied view state, never an export profile preference.
  if (asOf) q.set("as_of", asOf);
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

export type User = {
  id: string;
  is_admin?: boolean;
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

export type Coverage = {
  as_of: string;
  jurisdiction: string;
  totals: { directory_companies: number; companies_with_statements: number; filings: number; filings_with_statements: number; latest_filing_date: string | null };
  fiscal_years: { fiscal_year: number; periods: number; structured: number; provisional: number; unavailable: number; checks_passed: number; checks_failed: number; checks_not_run: number }[];
  forms: { form: string; filings: number }[];
  last_completed_ingestion: string | null;
  limitations: string[];
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
