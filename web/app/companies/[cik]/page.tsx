import Link from "next/link";
import { notFound } from "next/navigation";
import CompanyNav from "@/components/CompanyNav";
import CompanyOwnership from "@/components/CompanyOwnership";
import { Suspense } from "react";
import FollowButton from "@/components/FollowButton";
import HeadlineCards from "@/components/HeadlineCards";
import { api, NotFound } from "@/lib/server-api";
import { fmtDate, fmtEps, fmtMoney, isAnnual, type Doc, type Period, type Pref } from "@/lib/api";
import type { Remembered } from "@/lib/local";
import { sessionToken } from "@/lib/session";

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
  const token = await sessionToken();
  let prefList: Pref[] = [];
  if (token) {
    try {
      prefList = (await api.listPrefs(token)).prefs;
    } catch {
      prefList = [];
    }
  }
  const followed = prefList.find((p) => p.scope === "global" && p.key === "watchlist");
  const initialWatch = Array.isArray(followed?.value) ? (followed!.value as Remembered[]) : undefined;
  const [docsResp, peersResp] = await Promise.all([
    api.documents(id, 10).catch(() => null),
    api.peers(id).catch(() => null),
  ]);
  const docs = docsResp?.documents ?? {};
  const attached = new Set<string>();
  for (const p of periods.periods) {
    attached.add(p.results_accession);
    if (p.earnings_release_accession) attached.add(p.earnings_release_accession);
    for (const a of p.amendment_accessions ?? []) attached.add(a);
  }
  const other = filings.filings.filter((f) => !attached.has(f.accession) && !RESULTS_FORMS.has(f.form));
  const nxt = data.next_expected;
  const latest = periods.periods[0];
  const latestAnnual = periods.periods.find((p) => isAnnual(p.results_form));
  const latestQuarter = periods.periods.find((p) => !isAnnual(p.results_form));
  const latestRelease = periods.periods.find((p) => p.earnings_release_accession);
  // the headline cards show the latest period that has numbers, against the same period a year earlier
  const hasNumbers = (p: Period) => !!p.metrics && Object.values(p.metrics).some((v) => v !== null && v !== undefined);
  const headline = periods.periods.find(hasNumbers);
  const yearAgo = headline
    ? periods.periods.find(
        (p) => p !== headline && hasNumbers(p) && p.period_label.replace(/\d{4}/, "") === headline.period_label.replace(/\d{4}/, "") && isAnnual(p.results_form) === isAnnual(headline.results_form),
      )
    : undefined;
  const release = (p: Period | undefined): Doc | undefined =>
    p?.earnings_release_accession ? (docs[p.earnings_release_accession] ?? []).find((d) => d.kind === "release") : undefined;
  const extras = (p: Period): Doc[] =>
    [...(docs[p.results_accession] ?? []), ...(p.earnings_release_accession ? docs[p.earnings_release_accession] ?? [] : [])].filter(
      (d) => d.kind === "presentation" || d.kind === "supplement" || d.kind === "letter" || d.kind === "transcript",
    );
  const readerHref = (acc: string, file?: string) => `/companies/${id}/filings/${acc}` + (file ? `?file=${encodeURIComponent(file)}` : "");
  const proxy = other.find((f) => f.form === "DEF 14A");

  return (
    <>
      <p className="crumb"><Link href="/">← Search</Link></p>
      <div className="title-row">
        <div>
          <p className="eyebrow">Company</p>
          <h1>
            {c.name}
            {c.ticker && <span className="chip">{c.ticker}{c.exchange ? ` · ${c.exchange}` : ""}</span>}
          </h1>
          <p className="meta">{c.sic_description ?? ""}{c.fiscal_year_end ? ` · fiscal year ends ${fye(c.fiscal_year_end)}` : ""}{!c.is_active && " · no financial report in the last 18 months"}</p>
        </div>
        <FollowButton company={{ cik: c.cik, name: c.name, ticker: c.ticker }} signedIn={!!token} initial={initialWatch} />
      </div>

      <CompanyNav cik={id} />

      {headline && (
        <HeadlineCards
          cik={id}
          sic={c.sic ?? null}
          signedIn={!!token}
          initialPrefs={prefList}
          preset={data.headline_preset}
          labels={data.metric_labels}
          latest={headline.metrics ?? null}
          prior={yearAgo?.metrics ?? null}
          periodLabel={headline.period_label}
          priorLabel={yearAgo?.period_label ?? null}
        />
      )}

      <section className="summary">
        <div className="block">
          <div className="k">Latest period</div>
          <div className="v">{latest?.period_label ?? "–"}</div>
          {latest && <div className="muted">{isAnnual(latest.results_form) ? "Annual report" : "Quarterly report"} filed {fmtDate(latest.results_filed_date)}</div>}
        </div>
        <div className="block">
          <div className="k">Next expected</div>
          <div className="v">{nxt ? nxt.period_label : "–"}</div>
          {nxt && <div className="muted">results ~{fmtDate(nxt.expected_results_filed_date)}{nxt.expected_earnings_release_date ? ` · release ~${fmtDate(nxt.expected_earnings_release_date)}` : ""}</div>}
        </div>
        <div className="block docs">
          <div className="k">Open</div>
          <ul>
            {latestAnnual && <li><Link href={readerHref(latestAnnual.results_accession)}>Latest annual report</Link> <span className="muted">{latestAnnual.period_label}</span></li>}
            {latestQuarter && <li><Link href={readerHref(latestQuarter.results_accession)}>Latest quarterly report</Link> <span className="muted">{latestQuarter.period_label}</span></li>}
            {latestRelease && (
              <li>
                {release(latestRelease) ? (
                  <Link href={readerHref(latestRelease.earnings_release_accession!, release(latestRelease)!.filename)}>Latest earnings release</Link>
                ) : (
                  <a href={latestRelease.earnings_release_primary_doc_url ?? readerHref(latestRelease.earnings_release_accession!)} target="_blank" rel="noreferrer">Latest earnings release</a>
                )}{" "}
                <span className="muted">{fmtDate(latestRelease.earnings_release_filed_date)}</span>
              </li>
            )}
            {proxy && <li><Link href={readerHref(proxy.accession)}>Latest proxy statement</Link> <span className="muted">{fmtDate(proxy.filed_date)}</span></li>}
            {!latestAnnual && !latestQuarter && <li className="muted">No results filings on record.</li>}
          </ul>
        </div>
        <div className="block">
          <div className="k">Take it with you</div>
          <div className="v small"><a href={`/api/export?cik=${id}&limit=8`}>Excel, latest 8 periods</a></div>
          <div className="muted"><Link href={`/companies/${id}/statements`}>View statements</Link></div>
        </div>
      </section>

      <Suspense fallback={<p role="status" className="muted">Loading ownership coverage…</p>}><CompanyOwnership cik={id}/></Suspense>

      <form className="findin" action={`/companies/${id}/search`} method="get">
        <input name="q" placeholder={`Search inside ${c.ticker ?? "the company"}'s filings, e.g. buyback, guidance, impairment`} aria-label="Search inside filings" minLength={2} required />
        <button className="btn secondary" type="submit">Find</button>
      </form>

      <h2 id="filings">Periods & filings</h2>
      {periods.periods.length === 0 ? (
        <div className="empty">
          <p>No annual or quarterly results filings on record for this registrant.</p>
          <p className="muted">Funds, trusts and shell registrants often file no financial statements. Everything they did file is under “Other filings” below.</p>
        </div>
      ) : (
        <div className="stmt">
          <table className="periods">
            <thead>
              <tr>
                <th>Period</th>
                <th>Filed</th>
                <th className="num">Revenue</th>
                <th className="num">Net income</th>
                <th className="num">Diluted EPS</th>
                <th>Documents</th>
                <th>Statements</th>
              </tr>
            </thead>
            <tbody>
              {periods.periods.map((p) => {
                const rel = release(p);
                const more = extras(p);
                return (
                  <tr key={p.period_label}>
                    <td>
                      <strong>{p.period_label}</strong>
                      {p.period_type === "transition" && <span className="chip">transition</span>}
                      <div className="muted small">{fmtDate(p.period_end)}</div>
                    </td>
                    <td className="nowrap">{fmtDate(p.results_filed_date)}</td>
                    <td className="num">{fmtMoney(p.metrics?.revenue)}</td>
                    <td className="num">{fmtMoney(p.metrics?.net_income)}</td>
                    <td className="num">{fmtEps(p.metrics?.eps_diluted)}</td>
                    <td className="docs-cell">
                      <Link href={readerHref(p.results_accession)}>{isAnnual(p.results_form) ? "Annual report" : "Quarterly report"}</Link>
                      {p.earnings_release_accession &&
                        (rel ? (
                          <Link href={readerHref(p.earnings_release_accession, rel.filename)}>Earnings release</Link>
                        ) : (
                          <a href={p.earnings_release_primary_doc_url ?? readerHref(p.earnings_release_accession)} target="_blank" rel="noreferrer">Earnings release</a>
                        ))}
                      {more.map((d) => (
                        <Link key={d.filename} href={readerHref(d.url.includes(p.results_accession.replace(/-/g, "")) ? p.results_accession : p.earnings_release_accession!, d.filename)}>
                          {d.label}
                        </Link>
                      ))}
                      {(p.amendment_accessions?.length ?? 0) > 0 && <span className="chip">{p.amendment_accessions!.length} amendment{p.amendment_accessions!.length > 1 ? "s" : ""}</span>}
                    </td>
                    <td className="actions">
                      {p.statements_source ? (
                        <>
                          <Link href={`/companies/${id}/statements?periods=${encodeURIComponent(p.period_label)}`}>View</Link>
                          <a href={`/api/export?cik=${id}&periods=${encodeURIComponent(p.period_label)}`}>Excel</a>
                          {p.statements_source === "facts_fallback" && <span className="chip warn">provisional</span>}
                          {p.checks_passed === false && <span className="chip bad">review needed</span>}
                        </>
                      ) : (
                        <span className="muted" title="No statement data is available for this period yet.">Unavailable</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {docsResp && !docsResp.fetch_enabled && <p className="muted small">Exhibit-level documents are shown when the API has EDGAR access; links above open the primary documents.</p>}

      {peersResp && peersResp.peers.length > 0 && (
        <>
          <h2>Peers</h2>
          <p className="muted">Same industry code{peersResp.sic_description ? ` (${peersResp.sic_description})` : ""}, biggest first by latest annual revenue.</p>
          <div className="table-scroll"><table className="peers">
            <thead>
              <tr>
                <th>Company</th>
                <th>Ticker</th>
                <th className="num">Revenue</th>
                <th className="num">Net income</th>
                <th className="num">Total assets</th>
                <th>Fiscal year</th>
              </tr>
            </thead>
            <tbody>
              {peersResp.peers.map((p) => (
                <tr key={p.cik}>
                  <td><Link href={`/companies/${p.cik}`}>{p.name}</Link></td>
                  <td>{p.ticker ?? "–"}</td>
                  <td className="num">{fmtMoney(p.revenue)}</td>
                  <td className="num">{fmtMoney(p.net_income)}</td>
                  <td className="num">{fmtMoney(p.total_assets)}</td>
                  <td>{p.fiscal_year ?? "–"}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </>
      )}

      <details>
        <summary>Other filings ({other.length})</summary>
        {other.length === 0 ? (
          <p className="muted">Nothing besides the results filings above.</p>
        ) : (
          <table>
            <thead><tr><th>Filed</th><th>What it is</th><th></th></tr></thead>
            <tbody>
              {other.map((f) => (
                <tr key={f.accession}>
                  <td className="nowrap">{fmtDate(f.filed_date)}</td>
                  <td>{f.label}</td>
                  <td className="actions">
                    {f.primary_doc_url?.match(/\.(htm|html|txt)$/i) ? <Link href={readerHref(f.accession)}>Read</Link> : null}
                    <a href={f.primary_doc_url ?? f.filing_index_url ?? "#"} target="_blank" rel="noreferrer">sec.gov</a>
                  </td>
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
