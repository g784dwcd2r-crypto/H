import Link from "next/link";
import { notFound } from "next/navigation";
import StatementTabs from "@/components/StatementTabs";
import { api, NotFound } from "@/lib/api";
import { resolvedPrefs } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function StatementsPage({
  params,
  searchParams,
}: {
  params: Promise<{ cik: string }>;
  searchParams: Promise<{ periods?: string; limit?: string }>;
}) {
  const { cik } = await params;
  const { periods, limit } = await searchParams;
  const { prefs, signedIn } = await resolvedPrefs({ cik });
  const remembered = Number(prefs.periods_shown?.value) || 8;
  const n = Math.min(Math.max(parseInt(limit ?? String(remembered), 10) || remembered, 1), 40);
  let grid;
  try {
    grid = await api.statements(cik, periods, n);
  } catch (e) {
    if (e instanceof NotFound) notFound();
    throw e;
  }
  const id = String(grid.cik);
  const download = `/api/export?cik=${id}&limit=${n}` + (periods ? `&periods=${encodeURIComponent(periods)}` : "");
  return (
    <>
      <p className="crumb"><Link href={`/companies/${id}`}>← {grid.company_name}</Link></p>
      <p className="eyebrow">As reported</p>
      <h1>{grid.company_name}{grid.ticker && <span className="chip">{grid.ticker}</span>}</h1>
      <p className="meta">
        As-reported statements · {grid.periods.length} period{grid.periods.length === 1 ? "" : "s"}
        {periods ? "" : <> · <Link href={`/companies/${id}/statements?limit=${Math.min(n + 8, 40)}`}>show more periods</Link></>}
      </p>
      <StatementTabs grid={grid} downloadHref={download} cik={id} prefs={prefs} signedIn={signedIn} periodsShown={n} explicitLimit={!!limit} />
    </>
  );
}
