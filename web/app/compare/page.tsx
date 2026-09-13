import Link from "next/link";
import { workspaceRequest } from "@/lib/workspace-api";
import type { ValueMetadata } from "@/lib/api";
import styles from "./page.module.css";

export const dynamic = "force-dynamic";
export const metadata = { title: "Compare companies · Disclosure" };
type Comparison = {
  concept: string; period: string; notes: string[];
  results: { cik: number; company: string | null; ticker?: string; status: string; reason?: string;
    label?: string; value: number | null; unit: string | null; evidence: ValueMetadata | null;
    period: { period_end: string; filed_date: string; accession: string; primary_doc_url?: string; is_provisional: boolean } | null }[];
};

export default async function ComparePage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const raw = await searchParams;
  const read = (key: string, fallback = "") => typeof raw[key] === "string" ? raw[key] as string : fallback;
  const companies = read("companies"), concept = read("concept", "NetIncomeLoss"), period = read("period", "FY2025");
  const statement = read("statement", "IS"), asOf = read("as_of");
  const query = new URLSearchParams({ companies, concept, period, statement });
  if (asOf) query.set("as_of", asOf);
  const response = companies ? await workspaceRequest<Comparison>(`/v1/compare?${query}`) : null;
  return <div className={styles.page}>
    <p className="eyebrow">Company comparisons</p><h1>The same question. Across companies.</h1>
    <p className="lead">Compare a reported concept for a chosen fiscal period, with its units and filing evidence in view.</p>
    <form action="/compare" className={styles.form}>
      <label className={styles.companies}>Companies<input name="companies" defaultValue={companies} placeholder="AAPL, MSFT, JPM" required maxLength={250}/><span>Up to 12 tickers or CIKs, separated by commas.</span></label>
      <label>Fiscal period<input name="period" defaultValue={period} placeholder="FY2025" required maxLength={40}/></label>
      <label>Statement<select name="statement" defaultValue={statement}><option value="IS">Income statement</option><option value="BS">Balance sheet</option><option value="CF">Cash flow</option></select></label>
      <label className={styles.companies}>Reported concept<input name="concept" defaultValue={concept} list="concept-examples" required maxLength={250}/><datalist id="concept-examples"><option value="NetIncomeLoss"/><option value="RevenueFromContractWithCustomerExcludingAssessedTax"/><option value="Assets"/><option value="NetCashProvidedByUsedInOperatingActivities"/></datalist><span>Use the XBRL concept shown in a statement’s evidence panel.</span></label>
      <label>Filings available by<input type="date" name="as_of" defaultValue={asOf}/><span>Optional; filing-date resolution.</span></label>
      <button className="btn" type="submit">Compare companies →</button>
    </form>
    {!response && <section className={styles.start}><h2>Keep the accounting context.</h2><p>A shared concept can answer a precise question. Fiscal calendars, reporting definitions and currencies can still differ; every result keeps that context visible.</p><Link href="/compare?companies=AAPL,JPM&amp;concept=NetIncomeLoss&amp;period=FY2025&amp;statement=IS">Explore net income for Apple and JPMorgan →</Link></section>}
    {response && !response.ok && <div role="alert" className="notice"><h2>Comparison unavailable</h2><p>{response.error || "The comparison could not be loaded. Check the companies and try again."}</p></div>}
    {response?.data && <>
      <div className={styles.resultHeading}><h2>{response.data.period} · {response.data.concept}</h2><span>As reported · Unscaled</span></div>
      <div className={styles.tableWrap}><table><thead><tr><th>Company</th><th>Reported value</th><th>Fiscal period end</th><th>Evidence</th></tr></thead><tbody>
        {response.data.results.map(row => <tr key={row.cik}><td><Link href={`/companies/${row.cik}`}>{row.company || `CIK ${row.cik}`}</Link><small>{row.ticker}</small></td><td>{row.status === "available" && row.value !== null ? <><strong>{row.value.toLocaleString("en-US", { maximumFractionDigits: 8 })}</strong><small>{row.unit} · {row.label}</small></> : <><span>Unavailable</span><small>{row.reason}</small></>}</td><td>{row.period?.period_end || "—"}{row.period?.is_provisional && <small>Provisional source</small>}</td><td>{row.evidence?.sources.map((source, i) => <div key={`${source.accession}-${i}`}><Link href={`/companies/${row.cik}/filings/${source.accession}`}>View filing →</Link><small>{source.filed_date}</small></div>) || <span>—</span>}</td></tr>)}
      </tbody></table></div>
      <aside className={styles.notes} aria-label="Comparison methodology">{response.data.notes.map(note => <p key={note}>{note}</p>)}</aside>
    </>}
  </div>;
}
