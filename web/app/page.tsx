import Link from "next/link";
import { redirect } from "next/navigation";
import RecentCompanies from "@/components/RecentCompanies";
import RegionRequest from "@/components/RegionRequest";
import SearchBox from "@/components/SearchBox";
import { api, fmtDate } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const { q } = await searchParams;
  const term = (q ?? "").trim();
  const results = term ? (await api.search(term)).results : null;
  if (results && term) {
    // an exact ticker (or CIK) is not a search, it is a destination
    const exact = results.find((c) => (c.ticker ?? "").toUpperCase() === term.toUpperCase() || String(c.cik) === term);
    if (exact) redirect(`/companies/${exact.cik}`);
    if (results.length === 1) redirect(`/companies/${results[0].cik}`);
  }
  return (
    <>
      <section className="hero">
        <p className="eyebrow">Every SEC registrant</p>
        <h1>Filings, organised the way analysts read them.</h1>
        <p className="lead">Type a name, a ticker or a CIK. Land on the company: each fiscal period with its results filing, earnings release and the numbers, statements exactly as reported, Excel one click away.</p>
        <SearchBox initial={term} />
        <RecentCompanies />
        <RegionRequest />
      </section>
      {results && (
        <>
          <p className="eyebrow">{results.length ? `${results.length} result${results.length === 1 ? "" : "s"} for “${term}”` : `Nothing found for “${term}”`}</p>
          {results.length === 0 && (
            <div className="empty">
              <p>No company matches. Try the ticker (AAPL), the exact CIK (320193), or a shorter piece of the name.</p>
              <p className="muted">Only SEC registrants are here for now. UK and European companies are coming; say which ones you need above.</p>
            </div>
          )}
          {results.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Ticker</th>
                  <th>Exchange</th>
                  <th>Industry</th>
                  <th>Last financial report</th>
                </tr>
              </thead>
              <tbody>
                {results.map((c) => (
                  <tr key={c.cik}>
                    <td>
                      <Link href={`/companies/${c.cik}`}>{c.name}</Link>
                      {!c.is_active && <span className="chip">inactive</span>}
                    </td>
                    <td>{c.ticker ?? "–"}</td>
                    <td>{c.exchange ?? "–"}</td>
                    <td>{c.sic_description ?? "–"}</td>
                    <td>{fmtDate(c.last_financial_report_date)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </>
  );
}
