import Link from "next/link";
import SearchForm from "@/components/SearchForm";
import { api, fmtDate } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const { q } = await searchParams;
  const results = q ? (await api.search(q)).results : null;
  return (
    <>
      <h1>Find a company</h1>
      <p className="muted">Every SEC registrant. Type a name, a ticker or a CIK.</p>
      <SearchForm initial={q ?? ""} />
      {results && (
        <>
          <h2>{results.length ? `Results for “${q}”` : `Nothing found for “${q}”`}</h2>
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
