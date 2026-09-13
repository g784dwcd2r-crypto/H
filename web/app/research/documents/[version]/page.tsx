import Link from "next/link";
import { notFound } from "next/navigation";
import { workspaceRequest } from "@/lib/workspace-api";
import { documentVersionParam, researchReturnPath, indexedPageTexts, safeSourceUrl, type IndexedDocument } from "@/lib/research";
import SaveSource from "@/components/SaveSource";
import DocumentHistory from "@/components/DocumentHistory";

export const dynamic = "force-dynamic";
export const metadata = { title: "Indexed document" };

export default async function IndexedDocumentPage({ params, searchParams }: { params: Promise<{ version: string }>; searchParams: Promise<{ before?: string; history_offset?: string; return_to?: string }> }) {
  const { version } = await params;
  const query = await searchParams;
  const normalizedVersion = documentVersionParam(version);
  if (!normalizedVersion) notFound();
  const response = await workspaceRequest<IndexedDocument>(`/research/documents/${encodeURIComponent(normalizedVersion)}`);
  if (response.status === 404) notFound();
  const doc = response.data;
  if (!doc) return <div className="page-error"><p className="eyebrow">Indexed document</p><h1>This document could not be loaded.</h1><p>The indexed source is temporarily unavailable. Try again, or return to your search.</p><Link href="/research" className="btn secondary">Return to research</Link></div>;
  const original = safeSourceUrl(doc.source_url);
  const returnTo = researchReturnPath(query.return_to);
  const pages = indexedPageTexts(doc.text_content, doc.pages);
  return <article className="indexed-document">
    <p className="crumb"><Link href={returnTo || `/research?cik=${doc.cik}`}>{returnTo ? "← Back to search results" : `← Search ${doc.company_name || `CIK ${doc.cik}`} filings`}</Link></p>
    <p className="eyebrow">Indexed source · {doc.form}</p><h1>{doc.title || doc.filename}</h1>
    <p className="lead"><Link href={`/companies/${doc.cik}`}>{doc.company_name || `CIK ${doc.cik}`}</Link> · Filed {doc.filed_date}</p>
    <div className="indexed-document-actions">{original && <a className="btn secondary" href={original} target="_blank" rel="noreferrer">Open original document ↗</a>}<SaveSource documentId={doc.document_id} versionId={doc.version_id} title={doc.title || doc.filename}/><span>Text captured {doc.indexed_at}</span></div>
    <details className="indexed-provenance"><summary>Source & indexed version</summary><dl><div><dt>Accession</dt><dd>{doc.accession}</dd></div><div><dt>Filename</dt><dd>{doc.filename}</dd></div><div><dt>Document ID</dt><dd>{doc.document_id}</dd></div><div><dt>Version</dt><dd>{doc.version_id}</dd></div><div><dt>Content SHA-256</dt><dd>{doc.content_sha256}</dd></div><div><dt>Extractor</dt><dd>{doc.extractor_version}</dd></div></dl></details>
    <div className="notice">This is the extracted text used for search, preserved as an indexed version. Tables and layout may differ from the original. Use the original document to verify formatting and figures.</div>
    <DocumentHistory returnTo={returnTo} version={normalizedVersion} before={query.before} offset={/^\d{1,6}$/.test(query.history_offset || "") ? Number(query.history_offset) : 0}/>
    {doc.pages.length > 0 && <nav className="indexed-pages" aria-label="Document pages"><span>Jump to page</span>{doc.pages.map(page => <a key={page.page} href={`#document-page-${page.page}`}>{page.page}</a>)}</nav>}
    <section className="indexed-text" aria-label="Extracted filing text">{pages.length > 0 ? pages.map(page => <section key={page.page} id={`document-page-${page.page}`}><h2>Page {page.page}</h2><pre>{page.text}</pre></section>) : <pre>{doc.text_content}</pre>}</section>
  </article>;
}
