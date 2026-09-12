import Link from "next/link";
import { notFound } from "next/navigation";
import { api, fmtDate, NotFound } from "@/lib/api";

export const dynamic = "force-dynamic";

const RESULTS_FORMS = new Set(["10-K", "10-Q", "10-KT", "10-QT", "20-F", "40-F", "10-K/A", "10-Q/A", "20-F/A", "40-F/A"]);

export default async function CompanyPage({ params }: { params: Promise<{ cik: string }> }) {
  const { cik } = await params;
  let data, periods, filings;
  try {
    [data, periods, filings] = await Promise.all([api.company(cik), api.periods(cik), api.filings(cik)]);
  } catch (e) {
    if (e instanceof NotFound) notFound();
    throw e;
  }
  const c = data.company;
  const id = String(c.cik);
  const attached = new Set<string>();
  for (const p of periods.periods) {
    attached.add(p.results_accession);
    if (p.earnings_release_accession) attached.add(p.earnings_release_accession);
    for (const a of p.amendment_accessions ?? []) attached.add(a);
  }
  const other = filings.filings.filter((f) => !attached.has(f.accession) && !RESULTS_FORMS.has(f.form));
  const nxt = data.next_expected;

  return (
    <>
      <p className="muted"><Link href="/">← Search</Link></p>
      <h1>
        {c.name}
        {c.ticker && <span className="chip">{c.ticker}{c.exchange ? ` · ${c.exchange}` : ""}</span>}
      </h1>
      <p className="muted">{c.sic_description ?? ""}{c.fiscal_year_end ? ` · fiscal year ends ${fye(c.fiscal_year_end)}` : ""}</p>

      <div className="cards">
        <div className="card"><div className="k">Latest period</div><div className="v">{data.latest_period?.period_label ?? "–"}</div></div>
        <div className="card"><div className="k">Next expected results</div><div className="v">{nxt ? `${nxt.period_label} · ${fmtDate(nxt.expected_results_filed_date)}` : "–"}</div>{nxt?.expected_earnings_release_date && <div className="muted">earnings release ~{fmtDate(nxt.expected_earnings_release_date)}</div>}</div>
        <div className="card"><div className="k">Download</div><div className="v"><a href={`/api/export?cik=${id}&limit=8`}>Latest 8 periods (.xlsx)</a></div></div>
      </div>

      <h2>Periods</h2>
      {periods.periods.length === 0 ? (
        <div className="empty">No annual or quarterly results filings on record.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Period</th>
              <th>Period end</th>
              <th>Results filing</th>
              <th>Earnings release</th>
              <th>Statements</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {periods.periods.map((p) => (
              <tr key={p.period_label}>
                <td><strong>{p.period_label}</strong>{p.period_type === "transition" && <span className="chip">transition</span>}</td>
                <td>{fmtDate(p.period_end)}</td>
                <td>
                  <a href={p.results_primary_doc_url ?? p.results_filing_index_url ?? "#"} target="_blank" rel="noreferrer">
                    {p.results_form?.startsWith("10-K") || p.results_form?.endsWith("-F") ? "Annual report" : "Quarterly report"}
                  </a>
                  <span className="muted"> · filed {fmtDate(p.results_filed_date)}</span>
                  {(p.amendment_accessions?.length ?? 0) > 0 && <span className="chip">{p.amendment_accessions!.length} amendment{p.amendment_accessions!.length > 1 ? "s" : ""}</span>}
                </td>
                <td>
                  {p.earnings_release_primary_doc_url ? (
                    <><a href={p.earnings_release_primary_doc_url} target="_blank" rel="noreferrer">Earnings release</a><span className="muted"> · {fmtDate(p.earnings_release_filed_date)}</span></>
                  ) : (
                    <span className="muted">–</span>
                  )}
                </td>
                <td>
                  {p.statements_source ? (
                    <>
                      {p.statements_source === "facts_fallback" && <span className="chip warn">provisional</span>}
                      {p.checks_passed === true && <span className="chip ok">checks ✓</span>}
                      {p.checks_passed === false && <span className="chip bad">checks ✗</span>}
                    </>
                  ) : (
                    <span className="muted">not available</span>
                  )}
                </td>
                <td className="actions">
                  {p.statements_source && <Link href={`/companies/${id}/statements?periods=${encodeURIComponent(p.period_label)}`}>View statements</Link>}
                  {p.statements_source && <a href={`/api/export?cik=${id}&periods=${encodeURIComponent(p.period_label)}`}>Download</a>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <details>
        <summary>Other filings ({other.length})</summary>
        {other.length === 0 ? (
          <p className="muted">None.</p>
        ) : (
          <table>
            <thead><tr><th>Filed</th><th>What it is</th><th></th></tr></thead>
            <tbody>
              {other.map((f) => (
                <tr key={f.accession}>
                  <td>{fmtDate(f.filed_date)}</td>
                  <td>{f.label}</td>
                  <td><a href={f.primary_doc_url ?? f.filing_index_url ?? "#"} target="_blank" rel="noreferrer">Open</a></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </details>
    </>
  );
}

function fye(mmdd: string) {
  const m = parseInt(mmdd.slice(0, 2), 10);
  const d = parseInt(mmdd.slice(2), 10);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return Number.isFinite(m) && m >= 1 && m <= 12 ? `${months[m - 1]} ${d}` : mmdd;
}
