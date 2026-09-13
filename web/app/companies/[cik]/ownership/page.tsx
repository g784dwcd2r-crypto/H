import Link from "next/link";
import { notFound } from "next/navigation";
import CompanyNav from "@/components/CompanyNav";
import OwnershipCard from "@/components/OwnershipCard";
import OwnershipCoverage from "@/components/OwnershipCoverage";
import OwnershipExport from "@/components/OwnershipExport";
import { api, NotFound } from "@/lib/server-api";
import { workspaceRequest } from "@/lib/workspace-api";
import { FLOW_COPY, OWNERSHIP_FLOWS, ownershipFilters, ownershipPagePath, ownershipQuery, type OwnershipResponse, type SearchValues } from "@/lib/ownership";
import styles from "@/components/Ownership.module.css";

export const dynamic = "force-dynamic";
export const metadata = { title: "Ownership disclosures" };
export default async function OwnershipPage({ params, searchParams }: { params: Promise<{ cik: string }>; searchParams: Promise<SearchValues> }) {
  const { cik } = await params;
  if (!/^\d+$/.test(cik)) notFound();
  const values = await searchParams;
  const [companyResult, ...responses] = await Promise.all([api.company(cik).catch(error => { if (error instanceof NotFound) notFound(); throw error; }), ...OWNERSHIP_FLOWS.map(kind => workspaceRequest<OwnershipResponse>(`/companies/${cik}/ownership/${kind}?${ownershipQuery(ownershipFilters(values,kind))}`))]);
  const company = companyResult as Awaited<ReturnType<typeof api.company>>;
  const returnTo = ownershipPagePath(cik, values);
  return <div className={styles.page}>
    <p className="crumb"><Link href={`/companies/${cik}`}>← {company.company.name}</Link></p>
    <div className={styles.pageHeading}><div><p className="eyebrow">Company ownership</p><h1>Who reported what.</h1><p className="lead">{company.company.name}{company.company.ticker ? ` · ${company.company.ticker}` : ""}</p></div><p className={styles.headingNote}>Three disclosure types.<br/>Three different perspectives.</p></div>
    <CompanyNav cik={cik}/>
    <nav className={styles.flowNav} aria-label="Ownership disclosure types">{OWNERSHIP_FLOWS.map(kind => <a key={kind} href={`#${kind}`}>{FLOW_COPY[kind].title} <span>↓</span></a>)}</nav>
    <p className={styles.intro}>These disclosures describe what was reported on a filing date. They do not establish current ownership, trading intent, a complete portfolio or investment performance.</p>
    {OWNERSHIP_FLOWS.map((kind,index) => {
      const copy = FLOW_COPY[kind], filters = ownershipFilters(values,kind), response = responses[index] as Awaited<ReturnType<typeof workspaceRequest<OwnershipResponse>>>, data = response.data;
      const otherQuery = new URL(ownershipPagePath(cik,values,{flow:kind,clear:true}),"https://disclosure.invalid").searchParams;
      return <section key={kind} id={kind} className={styles.flow} aria-labelledby={`${kind}-title`}>
        <div className={styles.flowHeading}><div><p className="eyebrow">{copy.eyebrow}</p><h2 id={`${kind}-title`}>{copy.title}</h2><p>{copy.description}</p></div><OwnershipExport cik={cik} flow={kind} query={ownershipQuery(filters,false)}/></div>
        <form className={styles.filters} action={`/companies/${cik}/ownership#${kind}`} method="get" aria-label={`Filter ${copy.title.toLowerCase()}`}>
          {[...otherQuery].map(([key,value]) => <input key={key} type="hidden" name={key} value={value}/>)}
          {kind === "insiders" && <label>Transaction filter<select name="insiders_direction" defaultValue={filters.direction}><option value="all">All reported activity</option><option value="buys">Purchases · code P</option><option value="sales">Sales · code S</option></select></label>}
          <label>Filed from<input name={`${kind}_from`} type="date" defaultValue={filters.from}/></label><label>Filed through<input name={`${kind}_to`} type="date" defaultValue={filters.to} min={filters.from || undefined}/></label>
          <button className="btn secondary" type="submit">Apply {kind === "events" ? "disclosure" : kind} filters</button><Link className="text-link" href={ownershipPagePath(cik,values,{flow:kind,clear:true})}>Clear {kind} filters</Link>
        </form>
        <p className={styles.note}>Dates filter when the disclosure was filed, not when the transaction occurred or the position was held. CSV includes matching results across pages; narrow the filters if more than 10,000 rows match.</p>
        {data ? <><OwnershipCoverage coverage={data.coverage}/>{kind === "insiders" && data.purchase_cluster && <aside className={styles.coverage} aria-label="Observed insider purchases"><strong>{data.purchase_cluster.unique_reporting_identities} observed purchasing {data.purchase_cluster.unique_reporting_identities === 1 ? "identity" : "identities"}</strong><p>Filing window {data.purchase_cluster.from} through {data.purchase_cluster.to}. {data.purchase_cluster.note}</p></aside>}<div className={styles.resultCount}><strong>{data.total} {kind === "insiders" ? "reporting people" : kind === "institutions" ? "manager / security positions" : "ownership disclosures"}</strong><span>{data.items.length ? `${data.offset + 1}–${data.offset + data.items.length} shown` : "No cards shown"}</span></div>
          {data.items.length ? <div className={styles.cards}>{data.items.map(card => <OwnershipCard key={card.id} card={card} cik={cik} kind={kind} returnTo={`${returnTo}#${kind}`}/>)}</div> : <div className={styles.empty}><h3>{filters.offset ? "No records on this page" : "No matching parsed disclosures"}</h3><p>{copy.empty}</p>{filters.offset > 0 && <Link href={ownershipPagePath(cik,values,{flow:kind,offset:0})}>Return to the first page →</Link>}</div>}
          {(data.offset > 0 || data.next_offset !== null) && <nav className={styles.pagination} aria-label={`${copy.title} pages`}>{data.offset > 0 ? <Link className="btn secondary" href={ownershipPagePath(cik,values,{flow:kind,offset:Math.max(0,data.offset-data.limit)})}>← Previous</Link> : <span/>}<span>Page {Math.floor(data.offset/data.limit)+1}</span>{data.next_offset !== null ? <Link className="btn secondary" href={ownershipPagePath(cik,values,{flow:kind,offset:data.next_offset})}>Next →</Link> : <span/>}</nav>}
        </> : <div className={styles.unavailable} role="alert"><h3>{response.status === 422 ? "Check these filters" : `${copy.title} unavailable`}</h3><p>{response.status === 422 && response.error ? response.error : "This deployment could not load parsed ownership records. Coverage is unknown; this is not a zero result."}</p><Link href={`${returnTo}#${kind}`}>Try this view again →</Link></div>}
      </section>;
    })}
  </div>;
}
