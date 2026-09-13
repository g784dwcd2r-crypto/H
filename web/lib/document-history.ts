export type DocumentVersion = {
  version_id: string; content_sha256: string; indexed_at: string; extractor_version: string;
  content_bytes: number; title: string; filename: string; source_url: string;
  cik: number; accession: string; form: string; filed_date: string;
};

export type DocumentVersions = {
  document_id: string; current_version_id: string; versions: DocumentVersion[];
  total: number; limit: number; offset: number; next_offset: number | null;
};

export type DocumentComparison = {
  comparison: string; document_id: string; before: DocumentVersion; after: DocumentVersion;
  text_identical: boolean; complete: boolean; input_truncated: boolean; output_truncated: boolean;
  total_hunks_in_compared_text: number;
  hunks: {
    before_start: number; before_count: number; after_start: number; after_count: number;
    lines: { kind: "context" | "delete" | "insert"; before_line: number | null; after_line: number | null; text: string }[];
  }[];
  coverage: { before_characters_total: number; after_characters_total: number; before_characters_compared: number; after_characters_compared: number };
  limitations: string[];
};

export function capturedDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("en-GB", { timeZone: "UTC", day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }) + " UTC";
}
