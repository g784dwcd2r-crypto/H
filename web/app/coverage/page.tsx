import Link from "next/link";
import { api } from "@/lib/server-api";
import { fmtDate, type Coverage } from "@/lib/api";

export const dynamic = "force-dynamic";
export const metadata = { title: "Coverage · Disclosure", description: "Measured coverage of company filings and financial statements in Disclosure." };
const n = (value: number) => value.toLocaleString("en-US");

export default async function CoveragePage() {
  let coverage: Coverage | null = null;
  try { coverage = await api.coverage(); } catch { /* Show an honest unavailable state. */ }
  return <div className="coverage-page">
    <p className="eyebrow">Coverage & methodology</p>
    <h1>Know what is behind the numbers.</h1>
    <p className="lead">SEC filings, organised by company and reporting period. These counts come from the data currently available in Disclosure.</p>
    {!coverage ? <div className="empty"><h2>Coverage is temporarily unavailable</h2><p>We could not retrieve the latest counts. Please try again shortly.</p><Link href="/coverage">Try again →</Link></div> : <>
      <p className="muted small">{coverage.jurisdiction} · Measured {new Date(coverage.as_of).toLocaleString("en-GB", { timeZone: "UTC" })} UTC</p>
      <div className="cards">
        <div className="card"><div className="k">Companies with statements</div><div className="v">{n(coverage.totals.companies_with_statements)}</div></div>
        <div className="card"><div className="k">Companies in the directory</div><div className="v">{n(coverage.totals.directory_companies)}</div></div>
        <div className="card"><div className="k">Filing records</div><div className="v">{n(coverage.totals.filings)}</div></div>
        <div className="card"><div className="k">Filings with statements</div><div className="v">{n(coverage.totals.filings_with_statements)}</div></div>
      </div>
      <p className="muted">Latest filing date: {fmtDate(coverage.totals.latest_filing_date)}. Last completed ingestion: {coverage.last_completed_ingestion ? new Date(coverage.last_completed_ingestion).toLocaleString("en-GB", { timeZone: "UTC" }) + " UTC" : "No completed run recorded"}.</p>
      <h2>Financial statements by fiscal year</h2>
      <p className="muted">Structured statements use the SEC financial statement datasets. Provisional statements use company facts. Unavailable means the period has no statement source yet.</p>
      <div style={{ overflowX: "auto" }}><table>
        <thead><tr><th>Fiscal year</th><th className="num">Periods</th><th className="num">Structured</th><th className="num">Provisional</th><th className="num">Unavailable</th></tr></thead>
        <tbody>{coverage.fiscal_years.map(y => <tr key={y.fiscal_year}><td>{y.fiscal_year}</td><td className="num">{n(y.periods)}</td><td className="num">{n(y.structured)}</td><td className="num">{n(y.provisional)}</td><td className="num">{n(y.unavailable)}</td></tr>)}</tbody>
      </table></div>
      {coverage.fiscal_years.length === 0 && <p className="muted">Financial statement periods have not been loaded yet.</p>}
      <h2>Read the number. Check the evidence.</h2>
      <p>Open a value in the financial statements to see whether it was reported, derived, or taken from a later presentation. Derived values include the calculation and its inputs. Unsupported calculations remain unavailable with an explanation.</p>
      <p>When source information is available, the evidence panel links to the filing. Excel exports include the same value metadata in cell comments.</p>
      <h2>What to know before you use the data</h2>
      <ul>{coverage.limitations.map(line => <li key={line}>{line}</li>)}</ul>
      <h2>Filing types available</h2>
      <p className="muted">{coverage.forms.map(f => f.form + " (" + n(f.filings) + ")").join(" · ") || "No filing records loaded yet."}</p>
    </>}
    <p><Link href="/">Find a company →</Link></p>
  </div>;
}
