import Link from "next/link";
import { notFound } from "next/navigation";
import { workspaceRequest } from "@/lib/workspace-api";
import { ownershipReturnPath, ownershipValue, FLOW_COPY, type OwnershipRow, type OwnershipSource } from "@/lib/ownership";
import { safeSourceUrl } from "@/lib/research";
import { OwnershipFacts } from "@/components/OwnershipCard";
import CompanyNav from "@/components/CompanyNav";
import styles from "@/components/Ownership.module.css";
export const dynamic = "force-dynamic";
export const metadata = { title: "Ownership filing source" };
export default async function OwnershipSourcePage({ params, searchParams }: { params: Promise<{ cik: string; document_id: string }>; searchParams: Promise<{ return_to?: string }> }) {
  const { cik, document_id } = await params, query = await searchParams;
  if (!/^\d+$/.test(cik) || !/^[a-f0-9]{64}$/.test(document_id)) notFound();
  const returnTo = ownershipReturnPath(cik,query.return_to);
  const result = await workspaceRequest<OwnershipSource>(`/companies/${cik}/ownership/documents/${document_id}`);
  if (result.status === 404) notFound();
  const data = result.data;
  if (!data) return <section className={styles.unavailable} role="alert"><h1>Ownership source unavailable</h1><p>The saved filing could not be loaded. No source facts are being inferred.</p><Link href={returnTo}>← Return to ownership disclosures</Link></section>;
  const document = data.document, filing = data.filing, event = data.event, source = safeSourceUrl(document.source_url);
  const facts = ["issuer_name", "issuer_cik", "manager_name", "manager_cik", "report_period", "is_amendment", "amendment_type", "confidential_omitted"].filter(key => filing[key] !== null && filing[key] !== undefined && filing[key] !== "");
  return <div className={styles.sourcePage}><p className="crumb"><Link href={returnTo}>← Return to ownership disclosures</Link></p><div className={styles.pageHeading}><div><p className="eyebrow">{FLOW_COPY[data.kind].title} · Original filing record</p><h1>Form {document.form}</h1><p className="lead">Filed {document.filed_date} · {document.filename}</p></div>{source && <a className="btn secondary" href={source} target="_blank" rel="noreferrer">Open SEC source ↗</a>}</div><CompanyNav cik={cik}/><p className={styles.intro}>These facts were extracted from the captured filing. Reported positions, transaction dates and filing dates are distinct. Read the original text and footnotes before drawing a conclusion.</p>
    <dl className={styles.filingFacts}><div><dt>Accession</dt><dd>{document.accession}</dd></div>{facts.map(key => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{key.endsWith("_cik") ? String(filing[key]) : ownershipValue(filing[key])}</dd></div>)}</dl>
    {Array.isArray(filing.warnings) && filing.warnings.length > 0 && <aside className={styles.coverage}><strong>Source qualifications</strong><ul>{filing.warnings.map((warning,i) => <li key={i}>{ownershipValue(warning)}</li>)}</ul></aside>}
    {data.linkage?.type === "adjacent_quarter_comparison" && <aside className={styles.coverage} aria-label="Comparison source linkage"><strong>This filing is a comparison source, not a current issuer position.</strong><p>{data.linkage.note || "The previous quarter established the issuer linkage. An absence in this filing is not a confirmed exit."}</p>{data.linkage.prior_accession && <p>Prior accession: {data.linkage.prior_accession}</p>}</aside>}
    <section aria-label="Extracted ownership facts"><h2>Reported facts</h2>{data.rows.length > 0 ? <OwnershipFacts rows={data.rows} kind={data.kind}/> : !event && <p className={styles.missing}>No structured rows are available for this source.</p>}
      {event && <><dl className={styles.filingFacts}>{["issuer_name", "cusip", "security_title", "event_date", "filing_category"].map(key => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{key === "cusip" ? String(event[key] ?? "Not reported") : ownershipValue(event[key])}</dd></div>)}</dl>{Array.isArray(event.reporting_people) && <OwnershipFacts rows={event.reporting_people as OwnershipRow[]} kind="events"/>}{["purpose", "contracts"].map(key => event[key] ? <section className={styles.sourceText} key={key}><h3>{key === "purpose" ? "Reported purpose" : "Reported contracts and arrangements"}</h3><p>{ownershipValue(event[key])}</p></section> : null)}<p className={styles.note}>This disclosure is not automatically classified as activist. An investor letter is available only when identified in the filing's exhibits.</p></>}
      {data.rows.some(row => Array.isArray(row.footnotes) && row.footnotes.length > 0) && <section className={styles.footnotes}><h3>Footnotes</h3>{data.rows.map((row,i) => Array.isArray(row.footnotes) && row.footnotes.length ? <p key={i}>{ownershipValue(row.footnotes)}</p> : null)}</section>}
      {event && !event.cusip && Array.isArray(event.cusips) && event.cusips.length > 0 && <div><h3>Reported CUSIPs</h3><ul>{event.cusips.map((cusip,i) => <li key={i}>{String(cusip)}</li>)}</ul></div>}
      {event && Array.isArray(event.exhibits) && event.exhibits.length > 0 && <section><h3>Reported exhibit references</h3><ul>{event.exhibits.map((value,i) => { const exhibit=typeof value === "object" && value !== null ? value as OwnershipRow : {description:String(value)}; const url=typeof exhibit.url === "string" ? safeSourceUrl(exhibit.url) : typeof exhibit.source_url === "string" ? safeSourceUrl(exhibit.source_url) : null;const title=String(exhibit.title || exhibit.description || exhibit.filename || "Exhibit reference"); return <li key={i}>{url ? <a href={url} target="_blank" rel="noreferrer">{title} ↗</a> : title}</li>;})}</ul></section>}
    </section><details className={styles.rawSource}><summary>Inspect captured source text / XML</summary><p>Saved source bytes rendered as text; scripts and XML instructions are not executed.</p>{data.raw_truncated && <p role="status" className={styles.missing}>This preview is truncated. Open the SEC source to inspect the full document.</p>}<pre tabIndex={0} aria-label="Captured ownership source text">{data.raw_text}</pre></details><p className={styles.documentId}>Document identifier: {document_id}</p><Link className="text-link" href={returnTo}>← Return to the same ownership filters</Link>
  </div>;
}
