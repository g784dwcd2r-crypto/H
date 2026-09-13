"use client";
import { useState } from "react";
import type { Pref } from "@/lib/api";

const SCOPE_WORDS: Record<string, (k: string) => string> = { global: () => "Everywhere", sector: (k) => `Industry ${k}`, company: (k) => `Company ${k}`, statement: (k) => `Statement ${k.replace(":", " · ")}`, export: (k) => `Export profile ${k}` };
const KEY_WORDS: Record<string, string> = { scale: "Scale", statement: "Statement that opens first", periods_shown: "Periods shown", period_mode: "Period view", restated: "Latest-filed comparatives", column_order: "Column order", negative_style: "Negative numbers", headline_cards: "Headline cards", export_config: "Export settings", profile: "Export profile", watchlist: "Followed companies", proposals_dismissed: "Dismissed proposals" };
const showValue = (value: unknown): string => {
  if (Array.isArray(value)) return value.map((x) => typeof x === "object" && x !== null ? ((x as {ticker?: string; name?: string}).ticker ?? (x as {name?: string}).name ?? "") : String(x)).join(", ") || "Empty";
  if (typeof value === "object" && value !== null) return Object.entries(value).filter(([,x]) => typeof x !== "object").map(([k,x]) => `${k}: ${String(x)}`).join(" · ") || "Empty";
  return String(value);
};

export default function PrefsSettings({ initial, defaults }: { initial: Pref[]; defaults: Record<string, unknown> }) {
  const [prefs, setPrefs] = useState(initial);
  const [paste, setPaste] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const reload = async () => { const r = await fetch("/api/prefs"); if (!r.ok) throw new Error("Reload failed"); setPrefs(((await r.json()) as { prefs: Pref[] }).prefs); };
  const run = async (action: () => Promise<void>) => { setBusy(true); setMsg(null); try { await action(); } catch { setMsg("That action could not be completed. Please try again."); } finally { setBusy(false); } };
  const reset = (p: Pref) => run(async () => {
    const r = await fetch(`/api/prefs?${new URLSearchParams({ scope: p.scope, scope_key: p.scope_key, key: p.key })}`, { method: "DELETE" });
    if (!r.ok) throw new Error("Reset failed"); await reload(); setMsg(`${KEY_WORDS[p.key] ?? p.key} reset successfully.`);
  });
  const exportAll = () => run(async () => {
    const r = await fetch("/api/prefs/export", { method: "POST" }); if (!r.ok) throw new Error("Export failed");
    const text = JSON.stringify(await r.json(), null, 2); setPaste(text);
    try { await navigator.clipboard.writeText(text); setMsg("Copied to the clipboard. Your export is also shown below."); }
    catch { setMsg("Your export is shown below. Select and copy it to save it."); }
  });
  const importAll = () => run(async () => {
    let doc: { prefs?: Pref[] }; try { doc = JSON.parse(paste) as { prefs?: Pref[] }; } catch { setMsg("This is not valid JSON. Paste a preferences export to continue."); return; }
    if (!Array.isArray(doc?.prefs)) { setMsg("This is not a preferences export: a preferences list is required."); return; }
    const r = await fetch("/api/prefs/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prefs: doc.prefs }) });
    if (!r.ok) throw new Error("Import failed"); const data = await r.json() as { imported?: number }; await reload(); setMsg(`Imported ${data.imported ?? 0} preferences.`);
  });
  const resetAll = () => { if (!confirm("Reset all preferences, including followed companies and export profiles, to their defaults?")) return; void run(async () => { const r = await fetch("/api/prefs/reset", { method: "POST" }); if (!r.ok) throw new Error("Reset failed"); await reload(); setMsg("All preferences have been reset."); }); };
  const sorted = [...prefs].sort((a,b) => a.key.localeCompare(b.key) || a.scope.localeCompare(b.scope));
  return <>
    {sorted.length === 0 ? <div className="empty"><h2>A workspace that remembers.</h2><p>Your preferences will appear here when you customise a company, statement or export.</p></div> : <div className="table-scroll settings-table"><table className="prefs"><thead><tr><th>Preference</th><th>Value</th><th>Applies to</th><th>Origin</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>{sorted.map((p) => <tr key={`${p.scope}|${p.scope_key}|${p.key}`}><td>{KEY_WORDS[p.key] ?? p.key}</td><td className="small">{showValue(p.value)}</td><td>{(SCOPE_WORDS[p.scope] ?? ((k: string) => `${p.scope} ${k}`))(p.scope_key)}</td><td className="muted">{p.source === "explicit" ? "Your choice" : p.source === "inferred" ? "Accepted suggestion" : "Preset"}</td><td><button type="button" className="linkbtn" disabled={busy} onClick={() => void reset(p)}>Reset{typeof defaults[p.key] !== "undefined" ? ` (${String(defaults[p.key])})` : ""}</button></td></tr>)}</tbody></table></div>}
    <h2>Take your settings with you.</h2><p className="muted">Export your preferences, or import a previously saved configuration.</p>
    <div className="toolbar"><button type="button" className="btn secondary" disabled={busy} onClick={() => void exportAll()}>Export settings</button><button type="button" className="btn secondary" onClick={() => void importAll()} disabled={busy || !paste.trim()}>Import settings</button><button type="button" className="linkbtn" onClick={resetAll} disabled={busy || !prefs.length}>Reset all preferences</button></div>
    <textarea aria-label="Preferences JSON export or import" className="json" value={paste} onChange={(e) => setPaste(e.target.value)} placeholder="Export your settings to view them here, or paste a saved preferences export." rows={6} />
    {msg && <p className="notice" role="status">{msg}</p>}
  </>;
}
