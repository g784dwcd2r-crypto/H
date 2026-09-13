"use client";
import { useEffect, useId, useRef, useState } from "react";
import type { Company } from "@/lib/api";
import type { ResearchResult, ResearchResponse } from "@/lib/research";
import { citedRequest } from "@/lib/cited-research";
export type SelectedCompany = { cik: number; name: string; ticker?: string | null };
export type SelectedDocument = { version_id: string; title: string; cik: number; filed_date: string };

export default function CitedSourcePicker({ companies, documents, onCompanies, onDocuments, locked, maxCompanies, maxDocuments }: { companies: SelectedCompany[]; documents: SelectedDocument[]; onCompanies: (items: SelectedCompany[]) => void; onDocuments: (items: SelectedDocument[]) => void; locked: boolean; maxCompanies: number; maxDocuments: number }) {
  const [query, setQuery] = useState("");
  const [choices, setChoices] = useState<Company[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [error, setError] = useState<string | null>(null);
  const [documentQuery, setDocumentQuery] = useState("");
  const [results, setResults] = useState<ResearchResult[] | null>(null);
  const [documentBusy, setDocumentBusy] = useState(false);
  const [documentError, setDocumentError] = useState<string | null>(null);
  const documentSearch = useRef<HTMLButtonElement>(null);
  const listId = useId(); const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!query.trim()) { setChoices([]); return; }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try { const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`, { signal: controller.signal }); if (!response.ok) throw new Error(); const data = await response.json(); if (!controller.signal.aborted) { setChoices(data.results.filter((item: Company) => !companies.some(selected => selected.cik === item.cik))); setOpen(true); setError(null); } }
      catch { if (!controller.signal.aborted) setError("Company lookup is unavailable. Try again when the service is available."); }
    }, 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query, companies]);
  const choose = (company: Company) => { if (companies.length < maxCompanies) onCompanies([...companies, company]); setQuery(""); setChoices([]); setOpen(false); setActive(-1); input.current?.focus(); };
  return <div className="cited-source-picker"><div className="cited-field-heading"><h2>1. Choose your sources</h2><span>{locked ? "Scope fixed for follow-ups" : "Companies, documents, or both"}</span></div>
    <div className="cited-company-picker"><label htmlFor="cited-company">Companies</label><input id="cited-company" ref={input} disabled={locked || companies.length >= maxCompanies} value={query} onChange={event => { setQuery(event.target.value); setActive(-1); }} placeholder="Find a company or ticker" role="combobox" aria-autocomplete="list" aria-expanded={open && choices.length > 0} aria-controls={listId} aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined} onBlur={() => setOpen(false)} onFocus={() => choices.length > 0 && setOpen(true)} onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); if (!(open && active >= 0 && choices[active])) setError("Select a company from the suggestions before continuing."); } if (event.key === "Escape") setOpen(false); if (event.key === "ArrowDown" && choices.length) { event.preventDefault(); setOpen(true); setActive(value => Math.min(value + 1, choices.length - 1)); } if (event.key === "ArrowUp" && choices.length) { event.preventDefault(); setActive(value => Math.max(0, value - 1)); } if (event.key === "Enter" && open && active >= 0 && choices[active]) { event.preventDefault(); choose(choices[active]); } }}/>
      {open && choices.length > 0 && <ul className="company-options" id={listId} role="listbox" aria-label="Research company choices">{choices.map((item,index) => <li key={item.cik} id={`${listId}-${index}`} role="option" aria-selected={active === index} className={active === index ? "active" : ""} onMouseDown={event => { event.preventDefault(); choose(item); }} onMouseEnter={() => setActive(index)}><span>{item.name}</span><small>{item.ticker || `CIK ${item.cik}`}</small></li>)}</ul>}
      {error && <p className="err" role="status">{error}</p>}
    </div>
    {companies.length > 0 && <ul className="cited-selections" aria-label="Selected research companies">{companies.map(company => <li key={company.cik}><span>{company.name}<small>{company.ticker || `CIK ${company.cik}`}</small></span>{!locked && <button type="button" className="linkbtn" onClick={() => onCompanies(companies.filter(item => item.cik !== company.cik))} aria-label={`Remove ${company.name}`}>×</button>}</li>)}</ul>}
    {!locked && <details className="cited-documents-picker"><summary>Choose exact document versions <span>{documents.length ? `(${documents.length} selected)` : "optional"}</span></summary><p>Search the registered index, then choose the versions to include. Selecting companies and documents uses their intersection.</p><div className="cited-document-query"><label className="sr-only" htmlFor="cited-document-search">Find indexed documents</label><input id="cited-document-search" onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); documentSearch.current?.click(); } }} value={documentQuery} onChange={event => setDocumentQuery(event.target.value)} placeholder="Words in a filing, e.g. repurchase" maxLength={1000}/><button ref={documentSearch} type="button" className="btn secondary" disabled={documentBusy || !documentQuery.trim()} onClick={async () => { setDocumentBusy(true); setDocumentError(null); try { const response = await citedRequest<ResearchResponse>(`/search?q=${encodeURIComponent(documentQuery)}&limit=20`); setResults(response.results); } catch (cause) { setDocumentError(cause instanceof Error ? cause.message : "The index could not be searched."); } finally { setDocumentBusy(false); } }}>{documentBusy ? "Searching…" : "Find documents"}</button></div>{documentError && <p role="alert" className="err">{documentError}</p>}
      {results && <div className="cited-document-results">{!results.length ? <p>No indexed matches. This does not establish that relevant filings do not exist.</p> : results.map(result => { const selected = documents.some(item => item.version_id === result.version_id); return <label key={result.version_id}><input type="checkbox" checked={selected} disabled={!selected && documents.length >= maxDocuments} onChange={event => onDocuments(event.target.checked ? [...documents, result] : documents.filter(item => item.version_id !== result.version_id))}/><span><strong>{result.title || result.filename}</strong><small>{result.company_name || `CIK ${result.cik}`} · {result.form} · Filed {result.filed_date}</small></span></label>; })}</div>}
    </details>}
    {documents.length > 0 && <ul className="cited-document-selections" aria-label="Selected document versions">{documents.map(document => <li key={document.version_id}><span>{document.title}<small>CIK {document.cik} · Filed {document.filed_date}</small></span>{!locked && <button className="linkbtn" type="button" aria-label={`Remove document ${document.title}`} onClick={() => onDocuments(documents.filter(item => item.version_id !== document.version_id))}>Remove</button>}</li>)}</ul>}
    {locked && !documents.length && <p className="security-footnote">Eligible captured documents from the selected companies. Follow-ups retain the original cutoff and scope.</p>}
  </div>;
}
