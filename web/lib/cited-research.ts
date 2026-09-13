export type ResearchCapabilities = {
  available: boolean; unavailable_reason: "provider_not_ready" | "corpus_not_prepared" | null;
  provider: { configured: boolean; available: boolean; readiness: "not_configured" | "unverified" | "ready" | "account_unfunded"; provider: "xai" | "openai" | "fixture" | "disabled"; model: string | null; fixture: boolean };
  bounds: { max_question_chars: number; max_companies: number; max_documents: number; max_passages: number; max_runs_per_day: number };
  corpus: { indexed_documents: number; prepared_documents: number; spans: number; embedded_spans: number };
  limitations: string[];
};
export type ResearchPassage = {
  span_id: string; projection_id?: string; version_id: string; document_id: string; start: number; end: number; text: string;
  cik: number; title: string; form: string; filed_date: string; source_url: string; indexed_at: string;
};
export type CitedClaim = { id: string; text: string; assessment: "machine_assessed"; evidence: { span_id: string; relationship: "supporting" | "contradictory" | "context"; quote: string }[] };
export type CitedRun = {
  id: string; question: string; ciks: number[]; version_ids: string[]; as_of: string; parent_run_id: string | null;
  status: "running" | "completed" | "insufficient_evidence" | "conflicting_evidence" | "failed"; created_at: string; provider: ResearchCapabilities["provider"];
  claims: CitedClaim[]; passages: ResearchPassage[]; limitations: string[];
  coverage: { eligible_documents: number; eligible_spans: number; retrieved_passages: number; partial: boolean; excluded_after_cutoff: number };
  usage: { provider_calls: number; input_tokens: number; output_tokens: number }; calculations: ResearchCalculation[]; project_id: string | null;
};
export type CalculationOperand = { span_id: string; start: number; end: number; unit: string };
export type ResearchCalculation = { id: string; operation: string; value: string; unit: string; formula: string; operands: (CalculationOperand & { text: string; value: string })[]; limitations: string[] };
export type ResearchRunSummary = Pick<CitedRun, "id" | "question" | "status" | "created_at">;
export type RunRequest = { question: string; ciks: number[]; version_ids: string[]; as_of: string; parent_run_id?: string; idempotency_key: string };
export class CitedResearchError extends Error {
  constructor(message: string, public status: number) { super(message); }
}
export async function citedRequest<T>(path: string, method: "GET" | "POST" = "GET", body?: unknown): Promise<T> {
  let response: Response;
  try { response = await fetch(`/api/research-assistant${path}`, { method, cache: "no-store", ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }) }); }
  catch { throw new CitedResearchError("The request could not reach Disclosure. Your question and source selection are still here.", 0); }
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new CitedResearchError(typeof payload?.error === "string" ? payload.error : "The research request could not be completed. Your question and source selection are still here.", response.status);
  return payload as T;
}
export function runRequestKey(request: Omit<RunRequest, "idempotency_key">): string {
  return JSON.stringify({ ...request, ciks: [...request.ciks].sort((a,b) => a-b), version_ids: [...request.version_ids].sort() });
}
export function runStatusLabel(status: CitedRun["status"]): string {
  return { running: "Research in progress", completed: "Research draft", insufficient_evidence: "Insufficient evidence", conflicting_evidence: "Conflicting evidence", failed: "Research failed" }[status];
}
