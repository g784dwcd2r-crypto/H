export type AccountSession = {
  id: string;
  created_at: string;
  expires_at: string;
  last_seen_at: string;
  device_label: string;
  current: boolean;
};

export type SessionsResponse = {
  sessions: AccountSession[];
  current_session_id: string;
};

export type Project = { id: string; name: string; description: string; organization_id: string | null; owner_id: string; revision: number; created_at: string; updated_at: string; can_manage: boolean; starter_template?: { id: string; version: number } };
export type ProjectTemplate = { id: string; version: number; name: string; description: string; notes: { title: string; body: string; kind: "note" | "thesis" }[] };
export type OrganizationChoice = { id: string; name: string; role: string };
export type SourceReference = ({ kind: "document"; document_id: string; version_id: string } | { kind: "financial_snapshot"; snapshot_id: string; issuer_id: string }) & { status?: "available" | "unavailable" | "unresolved"; explanation?: string; title?: string; source_url?: string };
export type ProjectNote = { id: string; project_id: string; title: string; body: string; kind: "note" | "thesis"; authorship: "user" | "template"; origin?: { kind: "starter_template"; template_id: string; template_version: number }; citations: SourceReference[]; revision: number; created_by: string; created_at: string; updated_at: string };
