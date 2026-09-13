"use client";
import { useState } from "react";
import Link from "next/link";
import { DocumentIcon } from "@/components/Icons";
import { safeSourceUrl, indexedDocumentHref, type ResearchResult } from "@/lib/research";

export default function ResearchResults({ results, returnTo }: { results: ResearchResult[]; returnTo: string }) {
  const [selected, setSelected] = useState<ResearchResult | null>(null);
  return <div className={"research-results-layout" + (selected ? " with-evidence" : "")}>
    <ol className="research-results">{results.map(result => <li key={result.version_id} className={selected?.version_id === result.version_id ? "is-selected" : ""}>
      <div className="result-meta"><Link href={`/companies/${result.cik}`}>{result.company_name || `CIK ${result.cik}`}</Link><span>{result.form}</span><span>Filed {result.filed_date || "date unavailable"}</span></div>
      <h2><Link href={indexedDocumentHref(result.version_id, returnTo)}>{result.title || result.filename || "Filing document"}</Link></h2>
      <p className="result-snippet">{result.snippet || "No text preview is available for this match."}</p>
      <div className="result-actions"><button className="linkbtn" type="button" aria-expanded={selected?.version_id === result.version_id} aria-controls="research-evidence" onClick={() => setSelected(current => current?.version_id === result.version_id ? null : result)}><DocumentIcon /> Inspect source</button><Link href={indexedDocumentHref(result.version_id, returnTo)}>Read indexed text →</Link></div>
    </li>)}</ol>
    {selected && <aside id="research-evidence" className="research-evidence" aria-label="Selected search result evidence">
      <div className="evidence-top"><button className="linkbtn evidence-close" type="button" aria-label="Close search evidence" onClick={() => setSelected(null)}>Close ×</button><p className="eyebrow">Source evidence</p><h3>{selected.title || selected.filename}</h3></div>
      <p className="evidence-company">{selected.company_name || `CIK ${selected.cik}`}</p><blockquote>{selected.snippet}</blockquote>
      <dl><div><dt>Filing</dt><dd>{selected.form} · {selected.filed_date}</dd></div><div><dt>Document</dt><dd>{selected.filename}</dd></div><div><dt>Accession</dt><dd>{selected.accession}</dd></div><div><dt>Indexed version</dt><dd className="version-id">{selected.version_id}</dd></div></dl>
      <Link className="btn secondary" href={indexedDocumentHref(selected.version_id, returnTo)}>Read this indexed version</Link>
      {safeSourceUrl(selected.source_url) && <a className="source-original" href={safeSourceUrl(selected.source_url)!} target="_blank" rel="noreferrer">Open original source ↗</a>}
      <p className="security-footnote">This excerpt comes from the indexed document. Open the original source to check its presentation and surrounding context.</p>
    </aside>}
  </div>;
}
