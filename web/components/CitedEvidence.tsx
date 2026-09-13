"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { citedRequest, type ResearchPassage } from "@/lib/cited-research";
import { exactEvidenceSpan, evidenceNumbers, type ExactSpan, type EvidenceNumber } from "@/lib/evidence-span";
import { safeSourceUrl, type IndexedDocument } from "@/lib/research";

export default function CitedEvidence({ passage, onClose, onNumber, canCalculate }: { passage: ResearchPassage; onClose: () => void; onNumber: (number: EvidenceNumber, passage: ResearchPassage) => void; canCalculate: boolean }) {
  const closeButton = useRef<HTMLButtonElement>(null);
  const close = useRef(onClose); close.current = onClose;
  useEffect(() => { const previous = document.activeElement as HTMLElement | null; closeButton.current?.focus(); const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { event.preventDefault(); close.current(); } }; document.addEventListener("keydown", escape); return () => { document.removeEventListener("keydown", escape); if (previous?.isConnected) previous.focus(); }; }, []);
  const [source, setSource] = useState<ResearchPassage | null>(null);
  const [span, setSpan] = useState<ExactSpan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    setSource(null); setSpan(null); setError(null); setLoading(true);
    void (async () => {
      try {
        const fresh = await citedRequest<ResearchPassage>(`/spans/${encodeURIComponent(passage.span_id)}`);
        const document = await citedRequest<IndexedDocument>(fresh.projection_id ? `/projections/${encodeURIComponent(fresh.projection_id)}` : `/documents/${encodeURIComponent(fresh.version_id)}`);
        const exact = exactEvidenceSpan(document.text_content, fresh.start, fresh.end, fresh.text);
        if (!exact || fresh.version_id !== passage.version_id || fresh.document_id !== passage.document_id || fresh.span_id !== passage.span_id) throw new Error("The source passage could not be matched to its recorded version. No passage is highlighted.");
        if (active) { setSource(fresh); setSpan(exact); }
      } catch (cause) { if (active) setError(cause instanceof Error ? cause.message : "The source could not be inspected."); }
      finally { if (active) setLoading(false); }
    })();
    return () => { active = false; };
  }, [passage]);
  const numbers = source && canCalculate ? evidenceNumbers(source.text, source.start) : [];
  return <aside className="cited-evidence" aria-label="Exact source passage"><div className="cited-evidence-top"><div><p className="eyebrow">Inspect the evidence</p><h2>{passage.title}</h2></div><button ref={closeButton} type="button" className="linkbtn" onClick={onClose} aria-label="Close exact source passage">Close ×</button></div>
    {loading && <p role="status">Checking the saved source version and exact text…</p>}
    {error && <p className="notice err" role="alert">{error}</p>}
    {source && span && <><p className="cited-source-meta">{source.form} · Filed {source.filed_date}<br/>Captured {source.indexed_at}</p><div className="exact-source-context"><span>{span.before}</span><mark>{span.quote}</mark><span>{span.after}</span></div><p className="source-match">Exact indexed text · Characters {span.start}–{span.end} (Unicode code points)</p><p className="security-footnote">Matching a passage establishes where the words occur. It does not establish that a generated claim follows from them.</p><Link className="btn secondary" href={`/research/documents/${encodeURIComponent(source.version_id)}${source.projection_id ? `?projection=${encodeURIComponent(source.projection_id)}` : ""}`}>Open this source version</Link>{safeSourceUrl(source.source_url) && <a className="text-link" href={safeSourceUrl(source.source_url)!} target="_blank" rel="noreferrer">Original document ↗</a>}<details className="cited-source-ids"><summary>Source identifiers</summary><dl><dt>Document</dt><dd>{source.document_id}</dd><dt>Version</dt><dd>{source.version_id}</dd><dt>Passage</dt><dd>{source.span_id}</dd></dl></details>
      {numbers.length > 0 && <details className="source-numbers"><summary>Use source numbers in a calculation</summary><p>Choose a literal from this passage, then set its unit and check the period in context. Years and other non-financial numbers may appear here too.</p><ul>{numbers.map(number => <li key={`${number.start}-${number.end}`}><button type="button" onClick={() => onNumber(number, source)}>Use {number.text}</button><span>{number.context}</span></li>)}</ul></details>}
    </>}
  </aside>;
}
