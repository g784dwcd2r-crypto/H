export type ResearchFilters = { q: string; cik: string; form: string; from: string; to: string; offset: number };
export type ResearchResult = {
  document_id: string; version_id: string; cik: number; accession: string; filename: string;
  title: string; company_name: string; form: string; filed_date: string; source_url: string; snippet: string;
};
export type ResearchCoverage = {
  indexed: number; failed: number; pending: number; unsupported: number; total: number; partial: boolean;
  filings_known: number; inventories_complete: number; inventories_pending: number; inventories_failed: number;
  discovery_complete: boolean; last_discovery_at: string | null;
  scope: string; last_indexed_at: string | null;
};
export type ResearchResponse = { query: string; results: ResearchResult[]; total: number; limit: number; offset: number; next_offset: number | null; coverage: ResearchCoverage; syntax: string };

export function researchQuery(filters: ResearchFilters, offset = filters.offset): string {
  const query = new URLSearchParams();
  for (const key of ["q", "cik", "form", "from", "to"] as const) if (filters[key]) query.set(key, filters[key]);
  query.set("limit", "20");
  if (offset > 0) query.set("offset", String(offset));
  return query.toString();
}

export function safeSourceUrl(value: string): string | null {
  try { const url = new URL(value); return url.protocol === "https:" || url.protocol === "http:" ? url.href : null; }
  catch { return null; }
}

/** Next may retain percent encoding for reserved characters in a route parameter. */
export function documentVersionParam(value: string): string | null {
  try { const decoded = decodeURIComponent(value); return /^sha256:[a-f0-9]{64}$/.test(decoded) ? decoded : null; }
  catch { return null; }
}

export function researchError(status: number, detail: string | null): string {
  if (status === 422 || status === 400) return detail || "Check your query and filters. Use balanced quotes and parentheses, and a valid date range.";
  if (status === 429) return "Search is receiving too many requests. Wait a moment, then try again.";
  return "The filing index could not be searched right now. Your query has been kept. Please try again.";
}

export type IndexedDocument = Omit<ResearchResult, "snippet"> & {
  source_id: string; visibility: string; discovered_at: string; content_sha256: string;
  indexed_at: string; extractor_version: string; content_bytes: number;
  text_content: string; pages: { page: number; start: number; end: number }[];
};

/** Stored PDF offsets count Unicode code points, not JavaScript UTF-16 code units. */
export function indexedPageTexts(text: string, pages: IndexedDocument["pages"]): { page: number; text: string }[] {
  if (!pages.length) return [];
  const characters = Array.from(text);
  return pages.map(page => ({ page: page.page, text: characters.slice(page.start, page.end).join("") }));
}

/** Preserve only local filing-search context; never turn a return link into an external redirect. */
export function researchReturnPath(value?: string): string | null {
  if (!value || value.length > 5000) return null;
  try {
    const parsed = new URL(value, "https://disclosure.invalid");
    if (parsed.origin !== "https://disclosure.invalid" || parsed.pathname !== "/research" || !value.startsWith("/research")) return null;
    const query = new URLSearchParams();
    for (const key of ["q", "cik", "form", "from", "to", "offset"]) { const item = parsed.searchParams.get(key); if (item) query.set(key,item); }
    return `/research${query.size ? `?${query}` : ""}`;
  } catch { return null; }
}
export function indexedDocumentHref(version: string, returnTo?: string | null): string {
  const path = `/research/documents/${encodeURIComponent(version)}`;
  const safeReturn = researchReturnPath(returnTo ?? undefined);
  return safeReturn ? `${path}?${new URLSearchParams({return_to:safeReturn})}` : path;
}
