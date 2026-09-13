import Link from "next/link";
import ResearchForm from "@/components/ResearchForm";
import ResearchResults from "@/components/ResearchResults";
import { api } from "@/lib/server-api";
import { workspaceRequest } from "@/lib/workspace-api";
import { researchError, researchQuery, type ResearchFilters, type ResearchResponse } from "@/lib/research";

export const dynamic = "force-dynamic";
export const metadata = { title: "Research filings" };
type Params = Record<string, string | string[] | undefined>;

export default async function ResearchPage({ searchParams }: { searchParams: Promise<Params> }) {
  const raw = await searchParams;
  const read = (key: string) => typeof raw[key] === "string" ? (raw[key] as string).trim() : "";
  const filters: ResearchFilters = { q: read("q"), cik: read("cik"), form: read("form"), from: read("from"), to: read("to"), offset: Math.max(0, parseInt(read("offset"), 10) || 0) };
  const [response, company] = await Promise.all([workspaceRequest<ResearchResponse>(`/research/search?${researchQuery(filters)}`), filters.cik && /^\d+$/.test(filters.cik) ? api.company(filters.cik).catch(() => null) : Promise.resolve(null)]);
  const data = response.data;
  const coverage = data?.coverage;
  const incomplete = coverage && (coverage.partial || !coverage.discovery_complete);
  return <div className="research-page">
    <div className="research-heading"><div><p className="eyebrow">Research workspace</p><h1>Find it in the filings.</h1><p className="lead">Search company disclosures across the public SEC documents in our index. Follow every result back to its source.</p></div><Link href="/coverage" className="text-link">Coverage & sources ↗</Link></div>
    <ResearchForm key={researchQuery(filters)} filters={filters} companyName={company?.company.name} />
    {coverage && <section className={"index-coverage" + (incomplete ? " incomplete" : "")} aria-label="Search index coverage">
      <div><span className="coverage-dot" aria-hidden="true"/><strong>{incomplete ? "Partial index" : "Registered index processed"}</strong><span>{coverage.indexed.toLocaleString("en-GB")} documents searchable</span><Link href="/coverage">About coverage</Link></div>
      <p>{incomplete ? "Results may omit documents that are still pending, failed or unsupported." : "This describes the documents registered with our index, not all SEC filings or all companies."} {coverage.last_indexed_at ? `Last indexed: ${coverage.last_indexed_at}.` : "No successful indexing time is available."}</p>
      <details><summary>Index details</summary><dl className="index-counts"><div><dt>Indexed</dt><dd>{coverage.indexed}</dd></div><div><dt>Pending</dt><dd>{coverage.pending}</dd></div><div><dt>Failed</dt><dd>{coverage.failed}</dd></div><div><dt>Unsupported</dt><dd>{coverage.unsupported}</dd></div><div><dt>Discovery scan</dt><dd>{coverage.discovery_complete ? "Completed" : "Incomplete"}</dd></div><div><dt>Known filings</dt><dd>{coverage.filings_known}</dd></div><div><dt>Inventories pending / failed</dt><dd>{coverage.inventories_pending} / {coverage.inventories_failed}</dd></div></dl><p>Counts describe the registered index. Document inventories determine which files are known; incomplete inventories can hide additional gaps.</p></details>
    </section>}
    {!response.ok && <div className="research-error notice" role="alert"><h2>{response.status === 422 || response.status === 400 ? "Check your search" : "Search unavailable"}</h2><p>{researchError(response.status, response.error)}</p><p>Index coverage could not be confirmed for this request.</p></div>}
    {data && !filters.q && <section className="research-start"><p className="eyebrow">Start with a question, search the words</p><h2>What are you looking for?</h2><p>Try an exact phrase or combine terms. Results reflect the language in the documents.</p><div>{[{ label: "Supply chain risks", q: '"supply chain" AND risk' }, { label: "Share repurchases", q: '"share repurchase"' }, { label: "Revenue recognition", q: '"revenue recognition"' }].map(example => <Link key={example.q} href={`/research?${researchQuery({ ...filters, q: example.q, offset: 0 })}`}>{example.label} →</Link>)}</div></section>}
    {data && filters.q && <>
      <div className="results-heading"><h2>{data.total.toLocaleString("en-GB")} {data.total === 1 ? "document" : "documents"} found</h2><p>{data.results.length ? `${data.offset + 1}–${data.offset + data.results.length} · ` : ""}Indexed text · Newest filings first</p></div>
      {!data.results.length ? <div className="empty"><h3>{data.offset > 0 ? "No results on this page" : "No matching indexed documents"}</h3><p>{data.offset > 0 ? <Link href={`/research?${researchQuery(filters, 0)}`}>Return to the first page</Link> : <>Try a shorter phrase, a synonym or fewer filters. A zero result does not establish that a company has never discussed the topic.</>}</p>{incomplete && <p>Indexing is incomplete. Some documents are not searchable yet.</p>}</div> : <ResearchResults key={researchQuery(filters)} results={data.results} returnTo={`/research?${researchQuery(filters)}`} />}
      {(data.offset > 0 || data.next_offset !== null) && <nav className="research-pagination" aria-label="Search result pages">{data.offset > 0 ? <Link className="btn secondary" href={`/research?${researchQuery(filters, Math.max(0, data.offset - data.limit))}`}>← Previous</Link> : <span/>}<span>Page {Math.floor(data.offset / data.limit) + 1}</span>{data.next_offset !== null ? <Link className="btn secondary" href={`/research?${researchQuery(filters, data.next_offset)}`}>Next →</Link> : <span/>}</nav>}
    </>}
  </div>;
}
