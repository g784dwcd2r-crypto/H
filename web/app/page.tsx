import Link from "next/link";
import SearchForm from "@/components/SearchForm";
import { api, fmtDate } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const { q } = await searchParams;
  const results = q ? (await api.search(q)).results : null;
  return (
    <>
      <section className="hero">
        <p className="eyebrow">Every SEC registrant</p>
        <h1>Filings, organised the way analysts read them.</h1>
        <p className="lead">Find a company. See each fiscal period with its results filing and earnings release. Open the statements exactly as reported, or take them to Excel.</p>
        <SearchForm initial={q ?? ""} />
      </section>
      {results && (
        <>
          <p className="eyebrow">{results.length ? `${results.length} result${results.length === 1 ? "" : "s"} for “${q}”` : `Nothing found for “${q}”`}</p>
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
