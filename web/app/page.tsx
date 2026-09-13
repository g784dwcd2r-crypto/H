import Link from "next/link";
import { redirect } from "next/navigation";
import RecentCompanies from "@/components/RecentCompanies";
import RegionRequest from "@/components/RegionRequest";
import SearchBox from "@/components/SearchBox";
import WorkspacePreview from "@/components/WorkspacePreview";
import HomeMotion from "@/components/HomeMotion";
import { ArrowIcon, DocumentIcon } from "@/components/Icons";
import { EXAMPLE_ANNUAL, EXAMPLE_RELEASE, EXAMPLE_SOURCE } from "@/lib/example-data";
import { api } from "@/lib/server-api";
import { fmtDate, type Company } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const { q } = await searchParams;
  const term = (q ?? "").trim();
  let results: Company[] | null = null;
  let searchUnavailable = false;
  if (term) {
    try { results = (await api.search(term)).results; } catch { searchUnavailable = true; }
  }
  if (results && term) {
    const exact = results.find((c) => (c.ticker ?? "").toUpperCase() === term.toUpperCase() || String(c.cik) === term);
    if (exact) redirect(`/companies/${exact.cik}`);
    if (results.length === 1) redirect(`/companies/${results[0].cik}`);
  }
  return (
    <>
      <HomeMotion />
      <section className="landing-hero" aria-labelledby="landing-title">
        <div className="landing-copy">
          <h1 id="landing-title">The filings.<br />The financials.<br />Ready for your<br className="headline-break" /> <span className="ink-accent">analysis.</span></h1>
          <p className="landing-lead">Find company filings, compare as-reported financials, and export selected periods to Excel.</p>
          <SearchBox initial={term} autoFocus={false} />
          <Link href="/companies/320193" className="example-link">Explore an example <ArrowIcon /></Link>
          <RecentCompanies />
        </div>
        <WorkspacePreview />
      </section>
      {(results || searchUnavailable) && <section className="search-results" aria-label="Company search results">
        <p className="eyebrow">{searchUnavailable ? "Search temporarily unavailable" : `${results!.length} result${results!.length === 1 ? "" : "s"} for “${term}”`}</p>
        {searchUnavailable ? <div className="empty"><h2>We couldn’t reach company search.</h2><p>Please try again shortly. You can still inspect the historical example above.</p></div> : results!.length === 0 ? <div className="empty"><h2>No matching company yet.</h2><p>Try a ticker, a CIK or a shorter company name.</p><Link href="/coverage">Check current coverage →</Link></div> : <div className="table-scroll"><table><thead><tr><th>Company</th><th>Ticker</th><th>Exchange</th><th>Industry</th><th>Last financial report</th></tr></thead><tbody>{results!.map((c) => <tr key={c.cik}><td><Link href={`/companies/${c.cik}`}>{c.name}</Link>{!c.is_active && <span className="chip">inactive</span>}</td><td>{c.ticker ?? "—"}</td><td>{c.exchange ?? "—"}</td><td>{c.sic_description ?? "—"}</td><td>{fmtDate(c.last_financial_report_date)}</td></tr>)}</tbody></table></div>}
      </section>}
      <section className="feature-triptych" id="how-it-works" aria-label="How Disclosure works">
        <article data-reveal><p className="eyebrow">01 / Discover</p><h2>One period. Related filings.</h2><div className="feature-docs"><span>FY 2024</span><div><a href={EXAMPLE_ANNUAL} target="_blank" rel="noreferrer"><DocumentIcon />Annual report</a><a href={EXAMPLE_RELEASE} target="_blank" rel="noreferrer"><DocumentIcon />Earnings release</a></div></div></article>
        <article data-reveal><p className="eyebrow">02 / Understand</p><h2>A number. Its evidence.</h2><a className="feature-evidence" href={EXAMPLE_SOURCE} target="_blank" rel="noreferrer"><span>Total net sales<strong>391,035</strong></span><small>FY 2024 · USD millions · Source document ↗</small></a></article>
        <article data-reveal><p className="eyebrow">03 / Export</p><h2>Your periods. Excel-ready.</h2><div className="feature-sheet"><div><DocumentIcon />AAPL_financials.xlsx <span>Example</span></div><table><thead><tr><th>Metric</th><th>FY 2024</th><th>FY 2023</th></tr></thead><tbody><tr><td>Total net sales</td><td>391,035</td><td>383,285</td></tr></tbody></table></div></article>
      </section>
      <section className="research-section" data-reveal>
        <p className="eyebrow">A more focused way to work</p><h2>Built around the way you research.</h2>
        <div className="research-grid"><p>Start with a company. Keep the documents, numbers and reporting periods together, with a direct route back to the evidence.</p><div><h3>Make the workspace yours.</h3><p>Follow the companies you care about. Save your preferred scale, statement view and export settings, then pick up where you left off.</p><Link href="/watchlist" className="text-link">Your research starts here <ArrowIcon /></Link></div></div>
      </section>
      <section className="coverage-callout" data-reveal><div><p className="eyebrow">Know what’s available</p><h2>Clear about coverage.<br />Closer to the source.</h2></div><div><p>Start with SEC registrants. Financial statement availability varies by company, period and source. See what is available before you begin.</p><Link href="/coverage" className="text-link">Explore coverage & sources <ArrowIcon /></Link><RegionRequest /></div></section>
    </>
  );
}
