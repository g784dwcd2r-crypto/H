import { api, fmtDate, type Dashboard, type TouchReport } from "@/lib/api";

export const dynamic = "force-dynamic";
export const metadata = { title: "Metrics · Disclosure" };

const n = (v: number | null | undefined) => (v === null || v === undefined ? "–" : v.toLocaleString("en-US"));
const VALUE_WORDS = (v: unknown) => (typeof v === "object" && v !== null ? "settings" : String(v));

export default async function MetricsPage({ searchParams }: { searchParams: Promise<{ days?: string }> }) {
  const { days: d } = await searchParams;
  const days = Math.min(Math.max(parseInt(d ?? "30", 10) || 30, 1), 365);
  let dash: Dashboard | null = null;
  let touch: TouchReport | null = null;
  try {
    [dash, touch] = await Promise.all([api.dashboard(days), api.touchReport(days)]);
  } catch {
    /* rendered as unavailable below */
  }
  return (
    <>
      <p className="eyebrow">Metrics</p>
      <h1>How the hub is doing</h1>
      <p className="lead">Coverage and freshness of the lake, then which options people actually touch. Last {days} days.</p>
      <p className="muted small">
        Window:{" "}
        {[7, 30, 90].map((k) => (
          <a key={k} href={`/metrics?days=${k}`} style={{ marginRight: 10, fontWeight: k === days ? 600 : 400 }}>
            {k} days
          </a>
        ))}
      </p>
      {!dash ? (
        <div className="empty"><p>The API did not answer.</p></div>
      ) : (
        <>
          <div className="cards">
            <div className="card"><div className="k">Companies</div><div className="v">{n(dash.totals.companies)}</div></div>
            <div className="card"><div className="k">Filings</div><div className="v">{n(dash.totals.filings)}</div></div>
            <div className="card"><div className="k">Periods</div><div className="v">{n(dash.totals.periods)}</div></div>
            <div className="card"><div className="k">Filings with statements</div><div className="v">{n(dash.totals.filings_with_statements)}</div></div>
          </div>
          <h2>Refresh runs</h2>
          {dash.runs.length === 0 ? (
            <p className="muted">No refresh has run yet on this deployment.</p>
          ) : (
            <table>
              <thead><tr><th>Started</th><th>Kind</th><th>Status</th><th className="num">Seconds</th><th className="num">New filings</th><th className="num">Companies</th><th className="num">Statements</th></tr></thead>
              <tbody>
                {dash.runs.slice(0, 15).map((r) => (
                  <tr key={r.run_id}>
                    <td className="nowrap">{r.started_at?.slice(0, 16).replace("T", " ")}</td>
                    <td>{r.kind}</td>
                    <td><span className={"chip " + (r.status === "ok" ? "ok" : "bad")}>{r.status}</span></td>
                    <td className="num">{n(r.duration_seconds)}</td>
                    <td className="num">{n(r.new_filings)}</td>
                    <td className="num">{n(r.ciks_refreshed)}</td>
                    <td className="num">{n(r.statements_built)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <h2>Arithmetic checks by fiscal year</h2>
          <table>
            <thead><tr><th>Fiscal year</th><th className="num">Periods</th><th className="num">Checked</th><th className="num">Pass rate</th><th className="num">Provisional</th></tr></thead>
            <tbody>
              {dash.checks_by_fiscal_year.map((c) => (
                <tr key={c.fiscal_year}>
                  <td>{c.fiscal_year}</td>
                  <td className="num">{n(c.periods)}</td>
                  <td className="num">{n(c.applicable)}</td>
                  <td className="num">{c.pass_rate === null ? "–" : `${(c.pass_rate * 100).toFixed(1)}%`}</td>
                  <td className="num">{n(c.provisional)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h2>Filings per day</h2>
          <p className="muted small">{dash.filings_per_day.slice(-14).map((f) => `${fmtDate(f.filed_date)}: ${f.filings}`).join(" · ") || "nothing yet"}</p>
        </>
      )}

      <h2>Which options people touch</h2>
      {!touch ? (
        <p className="muted">Unavailable.</p>
      ) : touch.events === 0 ? (
        <p className="muted">No preference or UI events in this window.</p>
      ) : (
        <>
          <p className="muted">{n(touch.events)} events from {n(touch.users)} signed-in {touch.users === 1 ? "person" : "people"}. Preference writes first, then UI events.</p>
          <table className="prefs">
            <thead><tr><th>Preference</th><th className="num">Writes</th><th className="num">People</th><th className="num">Accepted proposals</th><th>Scopes</th><th>Most chosen</th></tr></thead>
            <tbody>
              {touch.prefs.map((p) => (
                <tr key={p.key}>
                  <td>{p.key}</td>
                  <td className="num">{n(p.writes)}</td>
                  <td className="num">{n(p.users)}</td>
                  <td className="num">{n(p.inferred)}</td>
                  <td className="muted small">{Object.entries(p.scopes).map(([s, k]) => `${s} ${k}`).join(", ")}</td>
                  <td className="muted small">{p.top_values.map((v) => `${VALUE_WORDS(v.value)} (${v.n})`).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {touch.ui.length > 0 && (
            <table className="prefs" style={{ marginTop: 20 }}>
              <thead><tr><th>UI event</th><th className="num">Count</th><th className="num">People</th></tr></thead>
              <tbody>
                {touch.ui.map((u) => (
                  <tr key={u.name}><td>{u.name}</td><td className="num">{n(u.count)}</td><td className="num">{n(u.users)}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </>
  );
}
