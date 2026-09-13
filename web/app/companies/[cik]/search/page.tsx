import Link from "next/link";
import { notFound } from "next/navigation";
import { api, fmtDate, NotFound } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function FilingSearchPage({
  params,
  searchParams,
}: {
  params: Promise<{ cik: string }>;
  searchParams: Promise<{ q?: string }>;
}) {
  const { cik } = await params;
  const { q } = await searchParams;
  const term = (q ?? "").trim();
  let company;
  try {
    company = await api.company(cik);
  } catch (e) {
    if (e instanceof NotFound) notFound();
    throw e;
  }
  const id = String(company.company.cik);
  const name = company.company.name;
  const res = term.length >= 2 ? await api.searchFilings(id, term).catch(() => null) : null;
  return (
    <>
      <p className="crumb"><Link href={`/companies/${id}`}>← {name}</Link></p>
      <p className="eyebrow">Search inside filings</p>
      <h1>{name}</h1>
      <form className="findin" action={`/companies/${id}/search`} method="get">
        <input name="q" defaultValue={term} placeholder="A word or phrase, e.g. buyback, restructuring, guidance" aria-label="Search inside filings" minLength={2} required autoFocus />
        <button className="btn" type="submit">Find</button>
      </form>
      {res === null && term.length >= 2 && (
        <div className="empty">
          <p>The search could not run right now.</p>
          <p className="muted">The filings are fetched from EDGAR the first time a company is searched; try again in a moment.</p>
        </div>
      )}
      {res && (
        <>
          <p className="muted">
            {res.results.length ? `Found in ${res.results.length} of ${res.searched} results filings` : `Not found in the last ${res.searched} results filings`}, newest first.
            {!res.fetch_enabled && " (The API has no EDGAR access; only cached filings were searched.)"}
          </p>
          {res.results.length === 0 && (
            <div className="empty">
              <p>No mention of “{term}” in the annual reports, quarterly reports and earnings releases searched.</p>
              <p className="muted">Try a shorter phrase, a synonym (“repurchase” for “buyback”), or the company's own wording.</p>
            </div>
          )}
          {res.results.map((r) => (
            <section key={r.accession} className="hitgroup">
              <h2 className="h-small">
                <Link href={`/companies/${id}/filings/${r.accession}?file=${encodeURIComponent(r.filename)}`}>{r.label}</Link>
                <span className="muted"> · {r.form} · filed {fmtDate(r.filed_date)}</span>
              </h2>
              <ul className="hits">
                {r.hits.map((h, i) => (
                  <li key={i}>
                    {h.before}
                    <mark>{h.match}</mark>
                    {h.after}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </>
      )}
    </>
  );
}
