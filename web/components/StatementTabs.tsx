"use client";

import Link from "next/link";
import { DocumentIcon } from "@/components/Icons";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import ExportDialog from "@/components/ExportDialog";
import PrefControl from "@/components/PrefControl";
import ProposalStrip from "@/components/ProposalStrip";
import type { ColumnOrder, Grid, PeriodMode, Pref } from "@/lib/api";
import { logEvent, scopeWords, type PrefContext, type Scope } from "@/lib/prefs-client";
import { usePrefs } from "@/lib/use-prefs";
import { formatFinancialValue as fmt, isUnscaled, type Scale } from "@/lib/number-format";

const SCALES: Scale[] = ["units", "thousands", "millions", "billions"];
const ALL_SCOPES: Scope[] = ["statement", "company", "sector", "global"];
const MODE_WORDS: Record<PeriodMode, string> = { as_filed: "as filed", quarterly: "quarterly", annual: "annual", ltm: "trailing twelve months" };

export default function StatementTabs({
  grid,
  cik,
  sic,
  initialPrefs,
  signedIn,
  periodsShown,
  explicitLimit,
  periodsParam,
  asOf,
}: {
  grid: Grid;
  cik: string;
  sic: string | null;
  initialPrefs: Pref[];
  signedIn: boolean;
  periodsShown: number;
  explicitLimit: boolean;
  periodsParam?: string;
  asOf?: string;
}) {
  const router = useRouter();
  const prefs = usePrefs(initialPrefs, signedIn);
  const codes = grid.statements.map((s) => s.code);
  const preferredStmt = String(prefs.get("statement", { cik })?.value ?? "IS");
  const [active, setActive] = useState(codes.includes(preferredStmt) ? preferredStmt : (codes[0] ?? "IS"));
  const [saved, setSaved] = useState<string | null>(null);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [cutoffDraft, setCutoffDraft] = useState(asOf ?? "");
  useEffect(() => setCutoffDraft(asOf ?? ""), [asOf]);
  const [exportOpen, setExportOpen] = useState(false);
  const [selected, setSelected] = useState<{ line: string; period: string } | null>(null);
  useEffect(() => {
    const st = String(prefs.get("statement", { cik })?.value ?? "");
    if (st && codes.includes(st)) setActive(st);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefs.list.length, signedIn]);

  const ctx: PrefContext = { cik, sic, statement: active };
  const companyCtx: PrefContext = { cik, sic };
  const scaleWhere = prefs.get("scale", ctx);
  const scale = (SCALES.includes(scaleWhere?.value as Scale) ? scaleWhere!.value : "millions") as Scale;
  const negative = String(prefs.get("negative_style", companyCtx)?.value ?? "parentheses");
  const order = (prefs.get("column_order", companyCtx)?.value === "newest_left" ? "newest_left" : "newest_right") as ColumnOrder;
  const remembered = prefs.get("periods_shown", { cik });
  const displayedPeriodCount = periodsParam ? grid.periods.length : periodsShown;
  const fullViewQuery = new URLSearchParams({mode:grid.period_mode,restated:grid.restated ? "1" : "0",limit:String(periodsShown)});
  if (asOf) fullViewQuery.set("as_of",asOf);

  const flash = (text: string) => {
    setSaved(text);
    setTimeout(() => setSaved(null), 1800);
  };
  const changeStatement = async (code: string) => {
    if (await prefs.set("statement", code, "company", { cik })) { setActive(code); setSelected(null); }
  };
  const rememberPeriods = async () => {
    if (!await prefs.set("periods_shown", periodsShown, "company", { cik })) return;
    flash(`${periodsShown} periods remembered for this company`);
  };
  // period mode and restated change what the API computes: save, then reload with the choice in the URL
  const reload = (mode: PeriodMode, restated: boolean, limit = periodsShown, cutoff = asOf) => {
    const q = new URLSearchParams();
    if (periodsParam) q.set("periods", periodsParam);
    q.set("limit", String(limit));
    q.set("mode", mode);
    q.set("restated", restated ? "1" : "0");
    if (cutoff) q.set("as_of", cutoff);
    router.push(`/companies/${cik}/statements?${q.toString()}`);
  };

  const stmt = grid.statements.find((s) => s.code === active) ?? grid.statements[0];
  const oldestFirst = useMemo(() => (grid.column_order === "newest_left" ? [...grid.periods].reverse() : grid.periods), [grid]);
  const periods = order === "newest_left" ? [...oldestFirst].reverse() : oldestFirst;

  useEffect(() => {
    // 1, 2, 3 switch statements; u / t / m / b change the scale
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const n = parseInt(e.key, 10);
      if (n >= 1 && n <= grid.statements.length) void changeStatement(grid.statements[n - 1].code);
      const key = ({ m: "millions", t: "thousands", u: "units", b: "billions" } as Record<string, Scale>)[e.key];
      if (key) {
        // the shortcut writes where the scale is currently set from (company when it is the default)
        const scope: Scope = ALL_SCOPES.includes(scaleWhere?.scope as Scope) ? (scaleWhere!.scope as Scope) : "company";
        void prefs.set("scale", key, scope, ctx).then((ok) => { if (ok) flash(`Scale saved ${scopeWords(scope)}`); });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [grid.statements, signedIn, active]);

  if (!stmt)
    return (
      <div className="empty">
        <p>No as-reported statements for these periods yet.</p>
        <p className="muted">Availability depends on the filing and its processing status. Check the company’s filings or coverage page for available documents.</p>
        {asOf && <p>Only filings available by {asOf} were included. <button className="linkbtn" type="button" onClick={() => reload(grid.period_mode, grid.restated, periodsShown, "")}>Clear the filing cutoff</button></p>}
      </div>
    );
  const derived = periods.some((p) => p.basis === "derived");
  const restatedCols = periods.filter((p) => p.basis === "restated");
  const selectedLine = selected ? stmt.lines.find((line) => line.key === selected.line) : undefined;
  const selectedPeriod = selected ? periods.find((period) => period.period_label === selected.period) : undefined;
  const metadata = selectedLine && selectedPeriod ? selectedLine.value_metadata?.[selectedPeriod.period_label] : undefined;
  const selectedValue = selectedLine && selectedPeriod ? selectedLine.values[selectedPeriod.period_label] : null;
  const sourceStatus = metadata?.status === "derived" ? "Calculated from reported inputs" : metadata?.status === "latest_presentation" ? "Latest available presentation" : metadata?.status === "unavailable" || selectedValue == null ? "Value unavailable" : "Reported observation";
  return (
    <>
      <ProposalStrip signedIn={signedIn} />
      <div className="tabs" role="tablist" aria-label="Financial statements" onKeyDown={(e) => {
        const buttons = Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
        const next = e.key === "ArrowRight" ? (index + 1) % buttons.length : e.key === "ArrowLeft" ? (index + buttons.length - 1) % buttons.length : e.key === "Home" ? 0 : e.key === "End" ? buttons.length - 1 : -1;
        if (next >= 0) { e.preventDefault(); buttons[next].focus(); buttons[next].click(); }
      }}>
        {grid.statements.map((s) => (
          <button key={s.code} role="tab" id={`statement-tab-${s.code}`} aria-controls="statement-panel" tabIndex={s.code === stmt.code ? 0 : -1} aria-selected={s.code === stmt.code} className={s.code === stmt.code ? "active" : ""} onClick={() => void changeStatement(s.code)}>
            {s.name}
          </button>
        ))}
      </div>
      <div className="toolbar statement-primary">
        <PrefControl
          prefs={prefs}
          prefKey="scale"
          showScope={false}
          label="Show in"
          fallback={"millions" as Scale}
          options={[
            { value: "billions", label: "billions" },
            { value: "millions", label: "millions" },
            { value: "thousands", label: "thousands" },
            { value: "units", label: "full units" },
          ]}
          ctx={ctx}
          scopes={["statement", "company", "sector", "global"]}
          onSaved={flash}
          title="Per-share amounts and share counts are never scaled."
        />
        <PrefControl
          prefs={prefs}
          prefKey="period_mode"
          showScope={false}
          label="Periods"
          fallback={grid.period_mode}
          valueOverride={grid.period_mode}
          options={[
            { value: "as_filed", label: "as filed" },
            { value: "quarterly", label: "quarterly (Q4 derived)" },
            { value: "annual", label: "annual only" },
            { value: "ltm", label: "trailing twelve months" },
          ]}
          ctx={companyCtx}
          scopes={["company", "sector", "global"]}
          onSaved={flash}
          onChange={(m) => reload(m, grid.restated)}
          title="As filed shows each filing's own column. Quarterly derives Q4 from the fiscal year; cash flow quarters are differences of the year-to-date columns."
        />
        <span className="muted periods">
          <select disabled={!!periodsParam} title={periodsParam ? "This view uses explicitly selected periods. Open the full financials to change the count." : undefined} value={displayedPeriodCount} onChange={(e) => reload(grid.period_mode, grid.restated, parseInt(e.target.value, 10))} aria-label="Number of periods">
            {Array.from(new Set([displayedPeriodCount, 4, 6, 8, 12, 16, 20, 40])).sort((a,b) => a-b).map((n) => (
              <option key={n} value={n}>{n} periods</option>
            ))}
          </select>
          {periodsParam && <Link className="linkbtn" href={`/companies/${cik}/statements?${fullViewQuery}`}>All periods</Link>}
        </span>
        <button className="btn secondary display-options-button" type="button" aria-expanded={optionsOpen} aria-controls="statement-display-options" onClick={() => setOptionsOpen(open => !open)}>Display options <span aria-hidden="true">{optionsOpen ? "−" : "+"}</span></button>
        <button type="button" className="btn secondary" style={{ marginLeft: "auto" }} onClick={() => { setExportOpen(true); logEvent("export.open", {}, signedIn); }}>
          Export to Excel…
        </button>
      </div>
      <div id="statement-display-options" className="statement-options" hidden={!optionsOpen}>
        <div className="options-intro"><h3>Display & saved preferences</h3><p>Adjust presentation and choose where your settings apply. The most specific setting wins: statement, company, sector, then everywhere.</p></div>
        <form className="filing-cutoff" onSubmit={event => { event.preventDefault(); reload(grid.period_mode, grid.restated, periodsShown, cutoffDraft); }}>
          <label>Filings available by<input type="date" value={cutoffDraft} onChange={event => setCutoffDraft(event.target.value)} aria-describedby="cutoff-help"/></label><button className="btn secondary" type="submit">Apply cutoff</button>{asOf && <button className="linkbtn" type="button" onClick={() => reload(grid.period_mode, grid.restated, periodsShown, "")}>Clear cutoff</button>}
          <p id="cutoff-help">Include filings dated on or before this day. This is a filing-date cutoff, not an intraday replay. Company information remains current; historical amendment-to-period mapping may be incomplete. The date applies to this view and its export and is never saved as a preference.</p>
        </form>
        <div className="advanced-controls">
        <PrefControl
          prefs={prefs}
          prefKey="column_order"
          label="Order"
          fallback={"newest_right" as ColumnOrder}
          options={[
            { value: "newest_right", label: "oldest to newest" },
            { value: "newest_left", label: "newest first" },
          ]}
          ctx={companyCtx}
          scopes={["company", "sector", "global"]}
          onSaved={flash}
        />
        <PrefControl
          prefs={prefs}
          prefKey="negative_style"
          label="Negatives"
          fallback="parentheses"
          options={[
            { value: "parentheses", label: "(1,234)" },
            { value: "minus", label: "-1,234" },
          ]}
          ctx={companyCtx}
          scopes={["company", "sector", "global"]}
          onSaved={flash}
        />
        {(grid.period_mode === "as_filed" || grid.period_mode === "annual") && (
          <PrefControl
            prefs={prefs}
            prefKey="restated"
            label="latest-filed comparatives"
            kind="toggle"
            fallback={grid.restated}
            valueOverride={grid.restated}
            options={[
              { value: true, label: "on" },
              { value: false, label: "off" },
            ]}
            ctx={companyCtx}
            scopes={["company", "sector", "global"]}
            onSaved={flash}
            onChange={(r) => reload(grid.period_mode, r)}
            title="Take each column's numbers from the newest later filing that presents the period (restated or reclassified prior years)."
          />
        )}
          <PrefControl prefs={prefs} prefKey="scale" label="Scale preference" fallback={"millions" as Scale} options={SCALES.map(value => ({ value, label: value }))} ctx={ctx} scopes={ALL_SCOPES} showValue={false} onSaved={flash} />
          <PrefControl prefs={prefs} prefKey="period_mode" label="Period preference" fallback={grid.period_mode} valueOverride={grid.period_mode} options={Object.entries(MODE_WORDS).map(([value, label]) => ({ value: value as PeriodMode, label }))} ctx={companyCtx} scopes={["company", "sector", "global"]} showValue={false} onSaved={flash} onChange={mode => reload(mode, grid.restated)} />
          <div className="period-memory"><span className="muted">Column count</span>
          {remembered && Number(remembered.value) === periodsShown ? (
            <span className="tag set"> remembered here</span>
          ) : explicitLimit ? (
            <button type="button" className="linkbtn" onClick={() => void rememberPeriods()}>remember for this company</button>
          ) : null}
          {!remembered && !explicitLimit && <button className="linkbtn" type="button" onClick={() => void rememberPeriods()}>Remember {periodsShown} periods for this company</button>}
          </div>
        </div>
      </div>
      <div className="preference-feedback" role="status" aria-live="polite">{saved}</div>
      {asOf && <p className="notice cutoff-notice">Filings available by <strong>{asOf}</strong>, through the end of that filing date. <button className="linkbtn" type="button" onClick={() => reload(grid.period_mode, grid.restated, periodsShown, "")}>Clear cutoff</button></p>}
      {prefs.error && <p className="notice" role="alert">{prefs.error}</p>}
      <ExportDialog
        cik={cik}
        ctx={companyCtx}
        prefs={prefs}
        signedIn={signedIn}
        current={{ period_mode: grid.period_mode, restated: grid.restated, column_order: order, limit: periodsShown, scale, negative_style: negative === "minus" ? "minus" : "parentheses" }}
        periods={periodsParam}
        asOf={asOf}
        open={exportOpen}
        onClose={() => setExportOpen(false)}
      />
      <p className="muted small">
        Per-share amounts and share counts are never scaled. Labels and line order are the company&apos;s own.
        {grid.period_mode !== "as_filed" && <> Showing {MODE_WORDS[grid.period_mode]}.</>}
        {derived && grid.period_mode === "quarterly" && <> Derived columns are shaded: Q4 is the fiscal year less nine months; cash flow quarters are differences of the year-to-date columns; unsupported per-share and non-additive calculations remain unavailable.</>}
        {derived && grid.period_mode === "ltm" && <> LTM columns are shaded: year to date plus the prior fiscal year less the prior year to date; unsupported per-share and non-additive calculations remain unavailable.</>}
        {restatedCols.length > 0 && <> Latest-presentation columns use the newest filing that presents the period; a later presentation may be a reclassification rather than a restatement.</>}
        {!signedIn && " Choices are kept in this browser; sign in to keep them on every device."}
      </p>
      <p className="source-hint">Select a number to inspect its reporting period, source and calculation. A dash means unavailable; select it for details.</p>
      <div id="statement-panel" role="tabpanel" aria-labelledby={`statement-tab-${stmt.code}`} className={"statement-workspace" + (selectedLine && selectedPeriod ? " has-evidence" : "")}><div className="stmt">
        <table>
          <thead>
            <tr>
              <th>Line item</th>
              <th>Unit</th>
              {periods.map((p) => (
                <th key={p.period_label} className="num" title={p.basis_note ?? undefined}>
                  {p.period_label}
                  {p.is_provisional && <span className="chip warn">provisional</span>}
                  {p.basis === "derived" && <span className="chip derived">derived</span>}
                  {p.basis === "restated" && <span className="chip">latest presentation</span>}
                  <div className="muted" style={{ fontWeight: 400, textTransform: "none" }}>{p.period_end}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {stmt.lines.map((ln) => (
              <tr key={ln.key} className={ln.is_abstract ? "abstract" : ln.is_subtotal ? "subtotal" : ""}>
                <td>{ln.label}</td>
                <td className="muted">{ln.is_abstract ? "" : ln.unit ?? ""}</td>
                {periods.map((p) => (
                  <td key={p.period_label} className={"num" + (!ln.is_abstract ? " inspectable" : "") + (p.is_provisional ? " provisional" : p.basis === "derived" ? " derived" : "")}>
                    {ln.is_abstract ? "" : <button type="button"
                      className={"cell-value" + (selected?.line === ln.key && selected?.period === p.period_label ? " selected" : "") + (ln.values[p.period_label] == null ? " unavailable" : "")}
                      aria-pressed={selected?.line === ln.key && selected?.period === p.period_label}
                      aria-label={`${ln.label}, ${p.period_label}: ${fmt(ln.values[p.period_label] ?? null, ln.unit, scale, negative, ln.concept) || "unavailable"}. Inspect evidence.`}
                      aria-controls="statement-evidence"
                      onClick={() => setSelected({ line: ln.key, period: p.period_label })}>
                      {fmt(ln.values[p.period_label] ?? null, ln.unit, scale, negative, ln.concept) || "—"}
                    </button>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <section id="statement-evidence" aria-label="Selected number evidence" aria-live="polite">
        {selectedLine && selectedPeriod && <div className="evidence-panel">
          <div className="evidence-top"><button className="evidence-close linkbtn" type="button" onClick={() => setSelected(null)} aria-label="Close number evidence">Close ×</button><div><p className="eyebrow">{sourceStatus}</p><h3>{selectedLine.labels?.[selectedPeriod.period_label] ?? selectedLine.label}</h3><p>{selectedPeriod.period_label} · Period ending {selectedPeriod.period_end}</p></div><div className="evidence-value">{fmt(selectedValue ?? null, selectedLine.unit, scale, negative, selectedLine.concept) || "Unavailable"}<p>{selectedLine.unit ?? "Unit not specified"}{isUnscaled(selectedLine.unit, selectedLine.concept) ? "" : ` · ${scale}`}</p></div></div>
          {selectedLine.labels?.[selectedPeriod.period_label] && selectedLine.labels[selectedPeriod.period_label] !== selectedLine.label && <p>Displayed row: {selectedLine.label}. The heading above preserves this period’s original wording.</p>}
          {metadata?.reason && <p>{metadata.reason}</p>}
          {metadata?.formula && <p className="evidence-formula">Calculation: {metadata.formula}</p>}
          {metadata?.sources.length ? <ul className="evidence-sources">{metadata.sources.map((source, i) => <li key={`${source.accession}-${source.concept}-${source.period_end}-${i}`}>
            <DocumentIcon /><div className="source-detail"><strong>{source.concept}</strong><span>{source.period_start ? `${source.period_start} to ` : "Ending "}{source.period_end ?? "date unavailable"}{source.qtrs != null ? ` · ${source.qtrs === 0 ? "At a date" : `${source.qtrs} quarter${source.qtrs === 1 ? "" : "s"}`}` : ""}{source.filed_date ? ` · Filed ${source.filed_date}` : ""}</span><span>Reported input: {source.value == null ? "unavailable" : source.value.toLocaleString("en-US", { maximumFractionDigits: 6 })} {source.unit ?? ""}{source.coefficient != null && source.coefficient !== 1 ? ` · coefficient ${source.coefficient}` : ""}</span>{source.unit_note && <span>{source.unit_note}</span>}{source.date_note && <span>{source.date_note}</span>}</div><Link href={`/companies/${cik}/filings/${encodeURIComponent(source.accession)}`}>Read filing →</Link>{source.document_url && /^https?:\/\//.test(source.document_url) && <a href={source.document_url} target="_blank" rel="noreferrer">Original ↗</a>}
          </li>)}</ul> : <p>Detailed source observations are not available for this value.{selectedPeriod.accession && <> <Link href={`/companies/${cik}/filings/${encodeURIComponent(selectedPeriod.accession)}`}>Open the period’s filing →</Link></>}</p>}
          <p>Sources open the supporting filing. An exact table or page location is shown only when it is available.</p>
        </div>}
      </section></div>
      <p className="muted" style={{ marginTop: 16 }}>
        Source: SEC EDGAR XBRL, via the SEC&apos;s Financial Statement Data Sets. Provisional columns are built from XBRL facts before the SEC publishes the quarter&apos;s data set and are replaced automatically.
      </p>
    </>
  );
}
