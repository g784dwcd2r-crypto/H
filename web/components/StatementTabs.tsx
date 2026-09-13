"use client";

import { useEffect, useState } from "react";
import type { Grid } from "@/lib/api";

type Scale = "units" | "thousands" | "millions";
const FACTORS: Record<Scale, number> = { units: 1, thousands: 1e3, millions: 1e6 };

function fmt(v: number | null, unit: string | null, scale: Scale): string {
  if (v === null || v === undefined) return "";
  const perShare = !!unit && unit.includes("/");
  const shares = unit === "shares";
  const factor = perShare ? 1 : shares ? FACTORS[scale] : FACTORS[scale];
  const x = v / factor;
  const s = perShare
    ? Math.abs(x).toFixed(2)
    : Math.abs(x).toLocaleString("en-US", { maximumFractionDigits: factor === 1 ? 0 : x % 1 === 0 ? 0 : 1 });
  return x < 0 ? `(${s})` : s;
}

export default function StatementTabs({ grid, downloadHref }: { grid: Grid; downloadHref: string }) {
  const [active, setActive] = useState(grid.statements[0]?.code ?? "IS");
  const [scale, setScale] = useState<Scale>("millions");
  const stmt = grid.statements.find((s) => s.code === active) ?? grid.statements[0];
  useEffect(() => {
    // 1, 2, 3 switch statements; m / t / u change the scale
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const n = parseInt(e.key, 10);
      if (n >= 1 && n <= grid.statements.length) setActive(grid.statements[n - 1].code);
      else if (e.key === "m") setScale("millions");
      else if (e.key === "t") setScale("thousands");
      else if (e.key === "u") setScale("units");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [grid.statements]);
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
          <button key={s.code} role="tab" aria-selected={s.code === stmt.code} className={s.code === stmt.code ? "active" : ""} onClick={() => setActive(s.code)}>
            {s.name}
          </button>
        ))}
      </div>
      <div className="toolbar">
        <label className="muted">
          Show in{" "}
          <select value={scale} onChange={(e) => setScale(e.target.value as Scale)}>
            <option value="millions">millions</option>
            <option value="thousands">thousands</option>
            <option value="units">full units</option>
          </select>
        </label>
        <span className="muted">Per-share amounts are never scaled. Labels and line order are the company&apos;s own.</span>
        <a className="btn secondary" href={downloadHref} style={{ marginLeft: "auto" }}>Download Excel</a>
      </div>
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
