export type ExactSpan = { before: string; quote: string; after: string; start: number; end: number };

/** Source offsets count Unicode code points. A quotation must match before it is highlighted. */
export function exactEvidenceSpan(text: string, start: number, end: number, quote: string, context = 280): ExactSpan | null {
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start) return null;
  const points = Array.from(text);
  if (end > points.length) return null;
  const captured = points.slice(start, end).join("");
  if (captured !== quote) return null;
  const radius = Math.max(0, Math.min(1000, Number.isFinite(context) ? Math.floor(context) : 280));
  return { before: (start > radius ? "…" : "") + points.slice(Math.max(0, start - radius), start).join(""), quote: captured, after: points.slice(end, end + radius).join("") + (end + radius < points.length ? "…" : ""), start, end };
}

export type EvidenceNumber = { text: string; start: number; end: number; context: string };
/** Suggestions identify source substrings only. Their units and economic meaning are never inferred. */
export function evidenceNumbers(text: string, absoluteStart: number): EvidenceNumber[] {
  const pattern = /(?<![\p{L}\p{N}_,.−‐‑‒–—﹣－-])(?:\(\d[\d,]*(?:\.\d+)?\)|[-−]?\d[\d,]*(?:\.\d+)?)(?![\p{L}\p{N}_]|[.,]\d)/gu;
  return Array.from(text.matchAll(pattern)).filter(match => !/[-−‐‑‒–—﹣－(]\s*$/.test(text.slice(0, match.index)) && !/^\s*\)/.test(text.slice(match.index + match[0].length))).slice(0, 80).map(match => ({ text: match[0], start: absoluteStart + Array.from(text.slice(0, match.index)).length, end: absoluteStart + Array.from(text.slice(0, match.index + match[0].length)).length, context: text.slice(Math.max(0, match.index - 35), match.index + match[0].length + 35).replace(/\s+/g, " ") }));
}
