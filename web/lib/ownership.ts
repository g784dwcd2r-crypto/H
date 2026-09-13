export const OWNERSHIP_FLOWS = ["insiders", "institutions", "events"] as const;
export type OwnershipFlow = typeof OWNERSHIP_FLOWS[number];
export const FLOW_COPY: Record<OwnershipFlow, { title: string; eyebrow: string; description: string; empty: string }> = {
  insiders: { title: "Insider activity", eyebrow: "01 / People at the company", description: "Reported transactions and holdings from Forms 3, 4 and 5. Purchases, awards, exercises and sales have different meanings.", empty: "No parsed insider activity matches this selection. This does not establish that no transactions occurred." },
  institutions: { title: "Institutional positions", eyebrow: "02 / Investment managers", description: "Reported 13F positions and compatible quarter-to-quarter changes. These are delayed disclosures, not a live trading feed.", empty: "No mapped institutional positions match this selection. Unmatched securities and missing reports are excluded from company comparisons." },
  events: { title: "Beneficial ownership", eyebrow: "03 / Ownership disclosures", description: "Schedule 13D and 13G disclosures. A filing alone does not establish activism, a transaction or an investor letter.", empty: "No parsed beneficial-ownership disclosures match this selection. No conclusion about ownership should be drawn from an empty index." },
};
export type OwnershipCoverage = { status: string; parsed_filings: number; pending: number; failed: number; unsupported: number; last_successful_at: string | null; unmatched_positions: number; note: string; companies?: ({ cik: number } & OwnershipCoverage)[] };
export type OwnershipDocument = { document_id: string; accession: string; form: string; filed_date: string; filename: string; source_url: string; reader_url: string };
export type OwnershipRow = Record<string, unknown>;
export type OwnershipCardData = { id: string; name: string; role: string; summary: string; date: string; reported_date: string; badges: string[]; history: { date: string; value: string; label: string; series_key: string }[]; history_note: string; metrics: { label: string; value: string }[]; documents: OwnershipDocument[]; transactions: OwnershipRow[]; issuer_cik?: number };
export type OwnershipResponse = { flow: OwnershipFlow; cik: number; items: OwnershipCardData[]; total: number; limit: number; offset: number; next_offset: number | null; coverage: OwnershipCoverage; purchase_cluster?: { unique_reporting_identities: number; from: string; to: string; note: string } };
export type OwnershipFeed = { flow: OwnershipFlow; items: OwnershipCardData[]; coverage: OwnershipCoverage };
export type OwnershipSource = { document: OwnershipDocument; filing: OwnershipRow; kind: OwnershipFlow; rows: OwnershipRow[]; event: OwnershipRow | null; raw_text: string; raw_truncated: boolean; linkage?: {type: "structured_subject_issuer" | "verified_cusip_position" | "adjacent_quarter_comparison"; prior_accession?: string; note?: string} };
export type OwnershipQuery = { from: string; to: string; offset: number; direction: "all" | "buys" | "sales" };
export type SearchValues = Record<string, string | string[] | undefined>;
// The API validates dates. Do not silently turn a malformed date into an unbounded query.
const dateValue = (value: string) => value.trim().slice(0,100);
export function ownershipFilters(values: SearchValues, flow: OwnershipFlow): OwnershipQuery {
  const read = (name: string) => typeof values[`${flow}_${name}`] === "string" ? values[`${flow}_${name}`] as string : "";
  const offset = Number(read("offset"));
  return { from: dateValue(read("from")), to: dateValue(read("to")), offset: Number.isSafeInteger(offset) && offset > 0 ? offset : 0, direction: flow === "insiders" && ["buys", "sales"].includes(read("direction")) ? read("direction") as "buys" | "sales" : "all" };
}
export function ownershipQuery(filters: OwnershipQuery, page = true): string {
  const query = new URLSearchParams();
  if (filters.from) query.set("from", filters.from);
  if (filters.to) query.set("to", filters.to);
  if (filters.direction !== "all") query.set("direction", filters.direction);
  if (page) { query.set("limit", "20"); if (filters.offset) query.set("offset", String(filters.offset)); }
  return query.toString();
}
/** Context is limited to this issuer's ownership page; never accept an external return destination. */
export function ownershipPagePath(cik: string | number, values: SearchValues, change?: { flow: OwnershipFlow; offset?: number; clear?: boolean }): string {
  const query = new URLSearchParams();
  for (const flow of OWNERSHIP_FLOWS) {
    const filters = ownershipFilters(values, flow);
    if (change?.flow === flow && change.clear) continue;
    for (const key of ["from", "to", "direction"] as const) if (filters[key] && filters[key] !== "all") query.set(`${flow}_${key}`, filters[key]);
    const offset = change?.flow === flow && change.offset !== undefined ? change.offset : filters.offset;
    if (offset > 0) query.set(`${flow}_offset`, String(offset));
  }
  return `/companies/${cik}/ownership${query.size ? `?${query}` : ""}${change ? `#${change.flow}` : ""}`;
}
export function ownershipReturnPath(cik: string | number, value?: string): string {
  const fallback = `/companies/${cik}/ownership`;
  if (!value || value.length > 5000) return fallback;
  try {
    const url = new URL(value, "https://disclosure.invalid");
    if (url.origin !== "https://disclosure.invalid" || url.pathname !== fallback || !value.startsWith(fallback)) return fallback;
    const result = ownershipPagePath(cik, Object.fromEntries(url.searchParams));
    return result + (OWNERSHIP_FLOWS.includes(url.hash.slice(1) as OwnershipFlow) ? url.hash : "");
  } catch { return fallback; }
}
export function ownershipSourceHref(cik: string | number, document: OwnershipDocument, returnTo?: string): string {
  return `/companies/${cik}/ownership/documents/${encodeURIComponent(document.document_id)}${returnTo ? `?${new URLSearchParams({ return_to: ownershipReturnPath(cik, returnTo) })}` : ""}`;
}
/** Display exact reported decimals, including zero; chart coordinates are never used as figures. */
export function ownershipValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not reported";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return Array.isArray(value) ? value.map(ownershipValue).join("; ") : Object.entries(value as OwnershipRow).map(([k,v]) => `${k.replaceAll("_", " ")}: ${ownershipValue(v)}`).join(" · ");
  const text = String(value), match = text.match(/^(-?)(\d+)(\.\d+)?$/);
  return match ? `${match[1]}${match[2].replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${match[3] || ""}` : text;
}
export function compatibleHistory(history: OwnershipCardData["history"]) {
  if (history.length < 2 || !history[0].series_key || history.some(point => point.series_key !== history[0].series_key || !/^\d{4}-\d{2}-\d{2}$/.test(point.date) || !/^-?\d+(\.\d+)?$/.test(point.value) || !Number.isFinite(Number(point.value)))) return null;
  return [...history].sort((a,b) => a.date.localeCompare(b.date));
}
