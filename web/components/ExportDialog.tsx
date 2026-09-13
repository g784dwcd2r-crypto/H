"use client";

import { useEffect, useRef, useState } from "react";
import { EXPORT_DEFAULTS, exportQuery, type ExportConfig } from "@/lib/api";
import { logEvent, scopeWords, type PrefContext, type Scope } from "@/lib/prefs-client";
import type { Prefs } from "@/lib/use-prefs";

const STATEMENTS: [string, string][] = [["IS", "Income statement"], ["BS", "Balance sheet"], ["CF", "Cash flow"], ["EQ", "Equity"], ["CI", "Comprehensive income"]];

/**
 * The export dialog. Pre-filled from the last export (company -> industry -> everywhere), with named
 * profiles kept as preferences in the `export` scope. Nothing is remembered until you say so.
 */
export default function ExportDialog({
  cik,
  ctx,
  prefs,
  signedIn,
  current,
  periods,
  open,
  onClose,
}: {
  cik: string;
  ctx: PrefContext;
  prefs: Prefs;
  signedIn: boolean;
  current: Partial<ExportConfig>; // the grid as shown right now (mode, restated, order, limit)
  periods?: string;
  open: boolean;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const remembered = prefs.get("export_config", ctx);
  const [cfg, setCfg] = useState<ExportConfig>({ ...EXPORT_DEFAULTS, ...current, ...((remembered?.value as Partial<ExportConfig>) ?? {}) });
  const [rememberScope, setRememberScope] = useState<Scope>("company");
  const [profileName, setProfileName] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const profiles = prefs.list.filter((p) => p.scope === "export" && p.key === "profile").map((p) => ({ name: p.scope_key, cfg: p.value as Partial<ExportConfig> }));

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  useEffect(() => {
    // on open: the remembered export settings, with the grid as it is shown right now on top
    if (open) setCfg({ ...EXPORT_DEFAULTS, ...((remembered?.value as Partial<ExportConfig>) ?? {}), ...current });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const upd = <K extends keyof ExportConfig>(k: K, v: ExportConfig[K]) => setCfg((c) => ({ ...c, [k]: v }));
  const download = async () => {
    setDownloading(true); setMsg(null);
    try {
      const response = await fetch(`/api/export?${exportQuery(cik, cfg, periods)}`);
      if (!response.ok) throw new Error("Export unavailable");
      const blob = await response.blob();
      const filename = response.headers.get("Content-Disposition")?.match(/filename="?([^";]+)"?/i)?.[1] ?? "Disclosure-financials.xlsx";
      const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = filename; document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 60000);
      logEvent("export.download", { layout: cfg.layout, orientation: cfg.orientation, subtotals: cfg.subtotals, period_mode: cfg.period_mode, scale: cfg.scale }, signedIn);
      setMsg("Your workbook is ready. Check your downloads.");
    } catch { setMsg("The workbook could not be generated. Please try again or choose fewer periods."); }
    finally { setDownloading(false); }
  };
  const remember = async () => {
    if (!await prefs.set("export_config", cfg, rememberScope, ctx)) { setMsg("Export settings could not be saved. Please try again."); return; }
    logEvent("export.remember", { scope: rememberScope }, signedIn);
    setMsg(`Export settings saved ${scopeWords(rememberScope)}.`);
  };
  const saveProfile = async () => {
    const name = profileName.trim().slice(0, 40);
    if (!name) return;
    if (!await prefs.set("profile", cfg, "export", { profile: name })) { setMsg("Profile could not be saved. Please try again."); return; } // the export scope's key is the profile name
    logEvent("export.profile.save", { name }, signedIn);
    setMsg(`Profile “${name}” saved.`);
    setProfileName("");
  };
  const loadProfile = (name: string) => {
    const p = profiles.find((x) => x.name === name);
    if (!p) return;
    setCfg({ ...EXPORT_DEFAULTS, ...p.cfg });
    logEvent("export.profile.load", { name }, signedIn);
    setMsg(`Loaded “${name}”.`);
  };
  const deleteProfile = async (name: string) => {
    if (!await prefs.reset("profile", "export", { profile: name })) { setMsg("Profile could not be removed. Please try again."); return; }
    setMsg(`Profile “${name}” removed.`);
  };

  return (
    <dialog ref={ref} className="exportdlg" onClose={onClose} aria-label="Export to Excel">
      <form method="dialog" onSubmit={(e) => e.preventDefault()}>
        <div className="dlg-head">
          <div>
            <p className="eyebrow">Export</p>
            <h2 className="h-small">Excel, your way</h2>
          </div>
          <button type="button" className="linkbtn" onClick={onClose}>Close</button>
        </div>

        {profiles.length > 0 && (
          <p className="chips profiles">
            {profiles.map((p) => (
              <span key={p.name} className="chip link">
                <button type="button" className="linkbtn plain" onClick={() => loadProfile(p.name)}>{p.name}</button>
                <button type="button" className="x" aria-label={`Delete profile ${p.name}`} onClick={() => void deleteProfile(p.name)}>×</button>
              </span>
            ))}
          </p>
        )}

        {periods && <p className="notice">Exporting your selected periods: {periods}. Open the full company financials to choose a different range.</p>}
        <div className="dlg-grid">
          <label>
            <span>Periods</span>
            <select value={cfg.period_mode} onChange={(e) => upd("period_mode", e.target.value as ExportConfig["period_mode"])}>
              <option value="as_filed">As filed</option>
              <option value="quarterly">Quarterly (Q4 derived)</option>
              <option value="annual">Annual only</option>
              <option value="ltm">Trailing twelve months</option>
            </select>
          </label>
          <label>
            <span>How many</span>
            <select disabled={!!periods} value={cfg.limit} onChange={(e) => upd("limit", parseInt(e.target.value, 10))}>
              {Array.from(new Set([cfg.limit, 4, 6, 8, 12, 16, 20, 40])).sort((a, b) => a - b).map((n) => <option key={n} value={n}>{n} periods</option>)}
            </select>
          </label>
          <label>
            <span>Column order</span>
            <select value={cfg.column_order} onChange={(e) => upd("column_order", e.target.value as ExportConfig["column_order"])}>
              <option value="newest_right">Oldest to newest</option>
              <option value="newest_left">Newest first</option>
            </select>
          </label>
          <label>
            <span>Layout</span>
            <select value={cfg.layout} onChange={(e) => upd("layout", e.target.value as ExportConfig["layout"])}>
              <option value="sheet_per_statement">One sheet per statement</option>
              <option value="one_sheet">Everything on one sheet</option>
            </select>
          </label>
          <label>
            <span>Orientation</span>
            <select value={cfg.orientation} onChange={(e) => upd("orientation", e.target.value as ExportConfig["orientation"])}>
              <option value="periods_across">Periods across, lines down</option>
              <option value="periods_down">Periods down, lines across</option>
            </select>
          </label>
          <label>
            <span>Subtotals</span>
            <select value={cfg.subtotals} onChange={(e) => upd("subtotals", e.target.value as ExportConfig["subtotals"])}>
              <option value="values">Values</option>
              <option value="formulas">Formulas where they add up</option>
            </select>
          </label>
          <label>
            <span>Numbers in</span>
            <select value={cfg.scale} onChange={(e) => upd("scale", e.target.value as ExportConfig["scale"])}>
              <option value="units">Full units</option>
              <option value="thousands">Thousands</option>
              <option value="millions">Millions</option>
              <option value="billions">Billions</option>
            </select>
          </label>
          <label>
            <span>Negatives</span>
            <select value={cfg.negative_style} onChange={(e) => upd("negative_style", e.target.value as ExportConfig["negative_style"])}>
              <option value="parentheses">(1,234)</option>
              <option value="minus">-1,234</option>
            </select>
          </label>
          <label className="wide">
            <span>File name</span>
            <input value={cfg.filename} onChange={(e) => upd("filename", e.target.value)} placeholder="{ticker}-statements" />
            <small className="muted">Use {"{ticker} {cik} {name} {mode} {date} {periods}"}</small>
          </label>
        </div>

        <fieldset className="dlg-checks">
          <legend className="muted">Include</legend>
          <label><input type="checkbox" checked={cfg.restated} onChange={(e) => upd("restated", e.target.checked)} /> latest-filed comparatives</label>
          <label><input type="checkbox" checked={cfg.include_source} onChange={(e) => upd("include_source", e.target.checked)} /> Source sheet</label>
          <label><input type="checkbox" checked={cfg.include_checks} onChange={(e) => upd("include_checks", e.target.checked)} /> arithmetic checks column</label>
          <label><input type="checkbox" checked={cfg.include_concepts} onChange={(e) => upd("include_concepts", e.target.checked)} /> XBRL concept names</label>
          <label><input type="checkbox" checked={cfg.include_filed_dates} onChange={(e) => upd("include_filed_dates", e.target.checked)} /> filing row under each column</label>
        </fieldset>
        <fieldset className="dlg-checks">
          <legend className="muted">Statements</legend>
          {STATEMENTS.map(([code, name]) => (
            <label key={code}>
              <input
                type="checkbox"
                checked={cfg.statements.includes(code)}
                onChange={(e) => upd("statements", e.target.checked ? [...cfg.statements, code] : cfg.statements.filter((s) => s !== code))}
              />{" "}
              {name}
            </label>
          ))}
        </fieldset>

        <div className="dlg-actions">
          <button type="button" className="btn" onClick={() => void download()} disabled={downloading || cfg.statements.length === 0}>{downloading ? "Preparing workbook…" : "Download Excel"}</button>
          <span className="row">
            <button type="button" className="btn secondary" onClick={() => void remember()}>Remember these settings</button>
            <select value={rememberScope} onChange={(e) => setRememberScope(e.target.value as Scope)} aria-label="Where to remember the export settings">
              <option value="company">for this company</option>
              {ctx.sic && <option value="sector">for this industry</option>}
              <option value="global">everywhere</option>
            </select>
          </span>
        </div>
        <div className="row profile-row">
          <input value={profileName} onChange={(e) => setProfileName(e.target.value)} aria-label="Export profile name" placeholder="Save as a named profile, e.g. Model input" maxLength={40} />
          <button type="button" className="btn secondary" onClick={() => void saveProfile()} disabled={!profileName.trim()}>Save profile</button>
        </div>
        {msg && <p className="muted small" role="status">{msg}</p>}
        {!signedIn && <p className="muted small">Settings and profiles are kept in this browser; sign in to keep them on every device.</p>}
      </form>
    </dialog>
  );
}
