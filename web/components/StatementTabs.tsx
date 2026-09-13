"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import ExportDialog from "@/components/ExportDialog";
import PrefControl from "@/components/PrefControl";
import ProposalStrip from "@/components/ProposalStrip";
import type { ColumnOrder, Grid, PeriodMode, Pref } from "@/lib/api";
import { logEvent, scopeWords, type PrefContext, type Scope } from "@/lib/prefs-client";
import { usePrefs } from "@/lib/use-prefs";

type Scale = "units" | "thousands" | "millions" | "billions";
const FACTORS: Record<Scale, number> = { units: 1, thousands: 1e3, millions: 1e6, billions: 1e9 };
const SCALES: Scale[] = ["units", "thousands", "millions", "billions"];
const ALL_SCOPES: Scope[] = ["statement", "company", "sector", "global"];
const MODE_WORDS: Record<PeriodMode, string> = { as_filed: "as filed", quarterly: "quarterly", annual: "annual", ltm: "trailing twelve months" };

function fmt(v: number | null, unit: string | null, scale: Scale, negative: string): string {
  if (v === null || v === undefined) return "";
  const perShare = !!unit && unit.includes("/");
  const factor = perShare ? 1 : FACTORS[scale];
  const x = v / factor;
  const s = perShare
    ? Math.abs(x).toFixed(2)
    : Math.abs(x).toLocaleString("en-US", { maximumFractionDigits: factor === 1 ? 0 : x % 1 === 0 ? 0 : 1 });
  return x < 0 ? (negative === "minus" ? `-${s}` : `(${s})`) : s;
}

export default function StatementTabs({
  grid,
  cik,
  sic,
  initialPrefs,
  signedIn,
  periodsShown,
  explicitLimit,
  periodsParam,
}: {
  grid: Grid;
  cik: string;
  sic: string | null;
  initialPrefs: Pref[];
  signedIn: boolean;
  periodsShown: number;
  explicitLimit: boolean;
  periodsParam?: string;
}) {
  const router = useRouter();
  const prefs = usePrefs(initialPrefs, signedIn);
  const codes = grid.statements.map((s) => s.code);
  const preferredStmt = String(prefs.get("statement", { cik })?.value ?? "IS");
  const [active, setActive] = useState(codes.includes(preferredStmt) ? preferredStmt : (codes[0] ?? "IS"));
  const [saved, setSaved] = useState<string | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
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

  const flash = (text: string) => {
    setSaved(text);
    setTimeout(() => setSaved(null), 1800);
  };
  const changeStatement = async (code: string) => {
    setActive(code);
    await prefs.set("statement", code, "company", { cik });
  };
  const rememberPeriods = async () => {
    await prefs.set("periods_shown", periodsShown, "company", { cik });
    flash(`${periodsShown} periods remembered for this company`);
  };
  // period mode and restated change what the API computes: save, then reload with the choice in the URL
  const reload = (mode: PeriodMode, restated: boolean, limit = periodsShown) => {
    const q = new URLSearchParams();
    if (periodsParam) q.set("periods", periodsParam);
    q.set("limit", String(limit));
    q.set("mode", mode);
    if (restated) q.set("restated", "1");
    router.push(`/companies/${cik}/statements?${q.toString()}`);
  };

  const stmt = grid.statements.find((s) => s.code === active) ?? grid.statements[0];
  const oldestFirst = useMemo(() => (grid.column_order === "newest_left" ? [...grid.periods].reverse() : grid.periods), [grid]);
  const periods = order === "newest_left" ? [...oldestFirst].reverse() : oldestFirst;

  useEffect(() => {
    // 1, 2, 3 switch statements; u / t / m / b change the scale
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const n = parseInt(e.key, 10);
      if (n >= 1 && n <= grid.statements.length) void changeStatement(grid.statements[n - 1].code);
      const key = ({ m: "millions", t: "thousands", u: "units", b: "billions" } as Record<string, Scale>)[e.key];
      if (key) {
        // the shortcut writes where the scale is currently set from (company when it is the default)
        const scope: Scope = ALL_SCOPES.includes(scaleWhere?.scope as Scope) ? (scaleWhere!.scope as Scope) : "company";
        void prefs.set("scale", key, scope, ctx);
        flash(`Scale saved ${scopeWords(scope)}`);
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
        <p className="muted">Statements appear once the filing&apos;s XBRL is processed, usually the same day; provisional ones come from the company&apos;s facts before the SEC data set catches up.</p>
      </div>
    );
  const derived = periods.some((p) => p.basis === "derived");
  const restatedCols = periods.filter((p) => p.basis === "restated");
  return (
    <>
      <ProposalStrip signedIn={signedIn} />
      <div className="tabs" role="tablist">
        {grid.statements.map((s) => (
          <button key={s.code} role="tab" aria-selected={s.code === stmt.code} className={s.code === stmt.code ? "active" : ""} onClick={() => void changeStatement(s.code)}>
            {s.name}
          </button>
        ))}
      </div>
      <div className="toolbar wrap">
        <PrefControl
          prefs={prefs}
          prefKey="scale"
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
          title="Per-share amounts are never scaled."
        />
        <PrefControl
          prefs={prefs}
          prefKey="period_mode"
          label="Periods"
          fallback={"as_filed" as PeriodMode}
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
            fallback={false}
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
        <span className="muted periods">
          <select value={periodsShown} onChange={(e) => reload(grid.period_mode, grid.restated, parseInt(e.target.value, 10))} aria-label="Number of periods">
            {[4, 6, 8, 12, 16, 20, 40].map((n) => (
              <option key={n} value={n}>{n} periods</option>
            ))}
          </select>
          {remembered && Number(remembered.value) === periodsShown ? (
            <span className="tag set"> remembered here</span>
          ) : explicitLimit ? (
            <button type="button" className="linkbtn" onClick={() => void rememberPeriods()}>remember for this company</button>
          ) : null}
        </span>
        {saved && <span className="saved">{saved}</span>}
        <button type="button" className="btn secondary" style={{ marginLeft: "auto" }} onClick={() => { setExportOpen(true); logEvent("export.open", {}, signedIn); }}>
          Export to Excel…
        </button>
      </div>
      <ExportDialog
        cik={cik}
        ctx={companyCtx}
        prefs={prefs}
        signedIn={signedIn}
        current={{ period_mode: grid.period_mode, restated: grid.restated, column_order: order, limit: periodsShown }}
        periods={periodsParam}
        open={exportOpen}
        onClose={() => setExportOpen(false)}
      />
      <p className="muted small">
        Per-share amounts are never scaled. Labels and line order are the company&apos;s own.
        {grid.period_mode !== "as_filed" && <> Showing {MODE_WORDS[grid.period_mode]}.</>}
        {derived && grid.period_mode === "quarterly" && <> Derived columns are shaded: Q4 is the fiscal year less nine months; cash flow quarters are differences of the year-to-date columns; derived per-share amounts are approximations.</>}
        {derived && grid.period_mode === "ltm" && <> LTM columns are shaded: year to date plus the prior fiscal year less the prior year to date; per-share amounts derived this way are approximations.</>}
        {restatedCols.length > 0 && <> Restated columns take their numbers from the latest filing that presents the period.</>}
        {!signedIn && " Choices are kept in this browser; sign in to keep them on every device."}
      </p>
      <div className="stmt">
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
                  {p.basis === "restated" && <span className="chip">restated</span>}
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
                  <td key={p.period_label} className={"num" + (p.is_provisional ? " provisional" : p.basis === "derived" ? " derived" : "")}>
                    {ln.is_abstract ? "" : fmt(ln.values[p.period_label] ?? null, ln.unit, scale, negative)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted" style={{ marginTop: 16 }}>
        Source: SEC EDGAR XBRL, via the SEC&apos;s Financial Statement Data Sets. Provisional columns are built from XBRL facts before the SEC publishes the quarter&apos;s data set and are replaced automatically.
      </p>
    </>
  );
}
