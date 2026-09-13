import Link from "next/link";
import { notFound } from "next/navigation";
import CompanyNav from "@/components/CompanyNav";
import StatementTabs from "@/components/StatementTabs";
import { api, NotFound } from "@/lib/server-api";
import { type PeriodMode, type Pref } from "@/lib/api";
import { resolvedPrefs, sessionToken } from "@/lib/session";
import { validFilingDate } from "@/lib/filing-cutoff";

export const dynamic = "force-dynamic";
const MODES: PeriodMode[] = ["as_filed", "quarterly", "annual", "ltm"];

export default async function StatementsPage({
  params,
  searchParams,
}: {
  params: Promise<{ cik: string }>;
  searchParams: Promise<{ periods?: string; limit?: string; mode?: string; restated?: string; as_of?: string }>;
}) {
  const { cik } = await params;
  const { periods, limit, mode, restated, as_of: asOf } = await searchParams;
  if (asOf && !validFilingDate(asOf)) return <div className="page-error"><h1>Check the filing cutoff</h1><p>Use a valid date in YYYY-MM-DD format.</p><Link href={`/companies/${encodeURIComponent(cik)}/statements`}>Return to current financials</Link></div>;
  let sic: string | null = null;
  try {
    sic = (await api.company(cik)).company.sic ?? null;
  } catch {
    /* the statements call below reports unknown companies */
  }
  const { prefs, signedIn } = await resolvedPrefs({ cik, sic });
  const token = signedIn ? await sessionToken() : null;
  let list: Pref[] = [];
  if (token) {
    try {
      list = (await api.listPrefs(token)).prefs;
    } catch {
      list = [];
    }
  }
  const remembered = Number(prefs.periods_shown?.value) || 8;
  const n = Math.min(Math.max(parseInt(limit ?? String(remembered), 10) || remembered, 1), 40);
  const periodMode = (MODES.includes(mode as PeriodMode) ? mode : MODES.includes(prefs.period_mode?.value as PeriodMode) ? prefs.period_mode?.value : "as_filed") as PeriodMode;
  const wantRestated = restated !== undefined ? restated === "1" || restated === "true" : prefs.restated?.value === true;
  const columnOrder = prefs.column_order?.value === "newest_left" ? "newest_left" : "newest_right";
  let grid;
  try {
    grid = await api.statements(cik, periods, n, { period_mode: periodMode, restated: wantRestated, column_order: columnOrder, as_of: asOf });
  } catch (e) {
    if (e instanceof NotFound) notFound();
    throw e;
  }
  const id = String(grid.cik);
  const more = new URLSearchParams({ limit: String(Math.min(n + 8, 40)), mode: periodMode });
  more.set("restated", wantRestated ? "1" : "0");
  if (asOf) more.set("as_of", asOf);
  return (
    <>
      <p className="crumb"><Link href={`/companies/${id}`}>← {grid.company_name}</Link></p>
      <p className="eyebrow">Company financials</p>
      <h1>{grid.company_name}{grid.ticker && <span className="chip">{grid.ticker}</span>}</h1>
      <p className="meta">
        As-reported statements · {grid.periods.length} period{grid.periods.length === 1 ? "" : "s"}
        {periods ? "" : <> · <Link href={`/companies/${id}/statements?${more.toString()}`}>show more periods</Link></>}
      </p>
      <CompanyNav cik={id} />
      <StatementTabs grid={grid} cik={id} sic={sic} initialPrefs={list} signedIn={signedIn} periodsShown={n} explicitLimit={!!limit} periodsParam={periods} asOf={asOf} />
    </>
  );
}
