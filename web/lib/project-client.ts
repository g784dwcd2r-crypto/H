import type { SourceReference } from "@/lib/workspace-types";

export function referencePointer(reference: SourceReference): SourceReference {
  return reference.kind === "document" ? { kind: "document", document_id: reference.document_id, version_id: reference.version_id } : { kind: "financial_snapshot", snapshot_id: reference.snapshot_id, issuer_id: reference.issuer_id };
}

export class ProjectRequestError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function projectRequest<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`/api/projects${path}`, { method, ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }), cache: "no-store" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ProjectRequestError(response.status, response.status === 409 ? "This item changed in another session. Your draft is still here. Load the latest saved version before trying again." : response.status === 401 ? "Your session has expired. Sign in again; keep a copy of your draft first." : data.error || "Your changes could not be saved. Please try again.");
  return data as T;
}
