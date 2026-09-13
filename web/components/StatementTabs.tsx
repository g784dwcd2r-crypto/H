"use client";

import { useEffect, useState } from "react";
import type { Grid, Resolved } from "@/lib/api";
import { readLocalPref, savePref } from "@/lib/prefs-client";

type Scale = "units" | "thousands" | "millions" | "billions";
const FACTORS: Record<Scale, number> = { units: 1, thousands: 1e3, millions: 1e6, billions: 1e9 };
const SCALES: Scale[] = ["units", "thousands", "millions", "billions"];
type ScaleScope = "company" | "global";

function fmt(v: number | null, unit: string | null, scale: Scale): string {
  if (v === null || v === undefined) return "";
  const perShare = !!unit && unit.includes("/");
  const factor = perShare ? 1 : FACTORS[scale];
  const x = v / factor;
  const s = perShare
    ? Math.abs(x).toFixed(2)
    : Math.abs(x).toLocaleString("en-US", { maximumFractionDigits: factor === 1 ? 0 : x % 1 === 0 ? 0 : 1 });
  return x < 0 ? `(${s})` : s;
}

const scopeWords = (scope: string) =>
  scope === "company" ? "for this company" : scope === "statement" ? "for this statement" : scope === "sector" ? "for this industry" : scope === "global" ? "everywhere" : "default";

export default function StatementTabs({
  grid,
  downloadHref,
  cik,
  prefs,
  signedIn,
  periodsShown,
  explicitLimit,
}: {
  grid: Grid;
  downloadHref: string;
  cik: string;
  prefs: Resolved;
  signedIn: boolean;
  periodsShown: number;
  explicitLimit: boolean;
}) {
  const codes = grid.statements.map((s) => s.code);
  const preferredStmt = String(prefs.statement?.value ?? "IS");
  const [active, setActive] = useState(codes.includes(preferredStmt) ? preferredStmt : (codes[0] ?? "IS"));
  const [scale, setScale] = useState<Scale>((SCALES.includes(prefs.scale?.value as Scale) ? prefs.scale?.value : "millions") as Scale);
  const [scaleScope, setScaleScope] = useState<string>(prefs.scale?.scope ?? "default");
  const [writeScope, setWriteScope] = useState<ScaleScope>(prefs.scale?.scope === "global" ? "global" : "company");
  const [remembered, setRemembered] = useState<number | null>(prefs.periods_shown?.scope === "company" ? Number(prefs.periods_shown.value) : null);
  const [saved, setSaved] = useState<string | null>(null);

  // signed out: this browser remembers, statement -> company -> everywhere
  useEffect(() => {
    if (signedIn) return;
    const sc = readLocalPref<Scale>("scale", { cik });
    if (sc && SCALES.includes(sc.value)) {
      setScale(sc.value);
      setScaleScope(sc.scope);
      setWriteScope(sc.scope === "global" ? "global" : "company");
    }
    const st = readLocalPref<string>("statement", { cik });
    if (st && codes.includes(st.value)) setActive(st.value);
    const ps = readLocalPref<number>("periods_shown", { cik });
    if (ps) setRemembered(Number(ps.value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signedIn, cik]);

  const flash = (text: string) => {
    setSaved(text);
    setTimeout(() => setSaved(null), 1800);
  };
  const changeScale = async (s: Scale, scope: ScaleScope = writeScope) => {
    setScale(s);
    setScaleScope(scope);
    await savePref({ scope, scope_key: scope === "company" ? cik : "", key: "scale", value: s }, signedIn);
    flash(`Scale saved ${scopeWords(scope)}`);
  };
  const changeStatement = async (code: string) => {
    setActive(code);
    await savePref({ scope: "company", scope_key: cik, key: "statement", value: code }, signedIn);
  };
  const rememberPeriods = async () => {
    await savePref({ scope: "company", scope_key: cik, key: "periods_shown", value: periodsShown }, signedIn);
    setRemembered(periodsShown);
    flash(`${periodsShown} periods remembered for this company`);
  };

  const stmt = grid.statements.find((s) => s.code === active) ?? grid.statements[0];
  useEffect(() => {
    // 1, 2, 3 switch statements; u / t / m / b change the scale
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const n = parseInt(e.key, 10);
      if (n >= 1 && n <= grid.statements.length) void changeStatement(grid.statements[n - 1].code);
      else if (e.key === "m") void changeScale("millions");
      else if (e.key === "t") void changeScale("thousands");
      else if (e.key === "u") void changeScale("units");
      else if (e.key === "b") void changeScale("billions");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [grid.statements, writeScope, signedIn]);

  if (!stmt)
    return (
      <div className="empty">
        <p>No as-reported statements for these periods yet.</p>
        <p className="muted">Statements appear once the filing's XBRL is processed, usually the same day; provisional ones come from the company's facts before the SEC data set catches up.</p>
      </div>
    );
  return (
    <>
      <div className="tabs" role="tablist">
        {grid.statements.map((s) => (
          <button key={s.code} role="tab" aria-selected={s.code === stmt.code} className={s.code === stmt.code ? "active" : ""} onClick={() => void changeStatement(s.code)}>
            {s.name}
          </button>
        ))}
      </div>
      <div className="toolbar">
        <label className="muted">
          Show in{" "}
          <select value={scale} onChange={(e) => void changeScale(e.target.value as Scale)}>
            <option value="billions">billions</option>
            <option value="millions">millions</option>
            <option value="thousands">thousands</option>
            <option value="units">full units</option>
          </select>
        </label>
        <label className="scopetag" title="Where this scale applies. Statement, then company, then everywhere; the most specific wins.">
          <select value={writeScope} onChange={(e) => void changeScale(scale, e.target.value as ScaleScope)}>
            <option value="company">for this company</option>
            <option value="global">everywhere</option>
          </select>
          <span className={"tag " + (scaleScope === "default" ? "" : "set")}>{scaleScope === "default" ? "default" : `set ${scopeWords(scaleScope)}`}</span>
        </label>
        <span className="muted periods">
          {periodsShown} period{periodsShown === 1 ? "" : "s"}
          {remembered === periodsShown ? (
            <span className="tag set"> remembered here</span>
          ) : explicitLimit ? (
            <button type="button" className="linkbtn" onClick={() => void rememberPeriods()}>remember for this company</button>
          ) : null}
        </span>
        {saved && <span className="saved">{saved}</span>}
        <a className="btn secondary" href={downloadHref} style={{ marginLeft: "auto" }}>Download Excel</a>
      </div>
      <p className="muted small">Per-share amounts are never scaled. Labels and line order are the company&apos;s own.{!signedIn && " Choices are kept in this browser; sign in to keep them on every device."}</p>
      <div className="stmt">
        <table>
          <thead>
            <tr>
              <th>Line item</th>
              <th>Unit</th>
              {grid.periods.map((p) => (
                <th key={p.period_label} className="num">
                  {p.period_label}
                  {p.is_provisional && <span className="chip warn">provisional</span>}
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
                {grid.periods.map((p) => (
                  <td key={p.period_label} className={"num" + (p.is_provisional ? " provisional" : "")}>
                    {ln.is_abstract ? "" : fmt(ln.values[p.period_label] ?? null, ln.unit, scale)}
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
