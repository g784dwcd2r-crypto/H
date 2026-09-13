import type { ProjectNote, SourceReference } from "@/lib/workspace-types";

export type NoteDraft = { title: string; body: string; kind: "note" | "thesis"; citations: SourceReference[] };
export type TabDraft = { version: 1; accountId: string; projectId: string; noteId: string | null; baseRevision: number | null; draft: NoteDraft };
const memory = new Map<string, TabDraft>();
export function projectDraftKey(accountId: string, projectId: string): string { return `disclosure:project-draft:v1:${encodeURIComponent(accountId)}:${encodeURIComponent(projectId)}`; }
export function readProjectDraft(storage: Pick<Storage,"getItem"> | null, accountId: string, projectId: string): TabDraft | null {
  const key = projectDraftKey(accountId, projectId);
  let value: unknown;
  try { const raw = storage?.getItem(key); value = raw ? JSON.parse(raw) : memory.get(key); } catch { value = memory.get(key); }
  const item = value as TabDraft | undefined;
  if (!item || item.version !== 1 || item.accountId !== accountId || item.projectId !== projectId || !(item.noteId === null || typeof item.noteId === "string") || !(item.baseRevision === null || Number.isInteger(item.baseRevision) && item.baseRevision > 0)) return null;
  const draft = item.draft;
  if (!draft || typeof draft.title !== "string" || draft.title.length > 200 || typeof draft.body !== "string" || draft.body.length > 100000 || !["note","thesis"].includes(draft.kind) || !Array.isArray(draft.citations)) return null;
  // Local recovery is never evidence of current source access. Retain pointers only.
  const citations: SourceReference[] = draft.citations.flatMap<SourceReference>(reference => reference?.kind === "document" && typeof reference.document_id === "string" && typeof reference.version_id === "string" ? [{kind:"document" as const,document_id:reference.document_id,version_id:reference.version_id}] : reference?.kind === "financial_snapshot" && typeof reference.snapshot_id === "string" && typeof reference.issuer_id === "string" ? [{kind:"financial_snapshot" as const,snapshot_id:reference.snapshot_id,issuer_id:reference.issuer_id}] : []);
  return {...item,draft:{...draft,citations}};
}
export function writeProjectDraft(storage: Pick<Storage,"setItem"> | null, value: TabDraft): boolean {
  const key = projectDraftKey(value.accountId,value.projectId); memory.set(key,value);
  try { if (!storage) return false; storage.setItem(key,JSON.stringify(value)); return true; } catch { return false; }
}
export function clearProjectDraft(storage: Pick<Storage,"removeItem"> | null, accountId:string, projectId:string): void {
  const key = projectDraftKey(accountId,projectId); memory.delete(key); try { storage?.removeItem(key); } catch { /* The next successful write supersedes a stale record. */ }
}
export function noteDraft(note: ProjectNote): NoteDraft { return {title:note.title,body:note.body,kind:note.kind,citations:note.citations}; }
