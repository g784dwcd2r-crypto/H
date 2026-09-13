"use client";

import { useState } from "react";
import type { Pref } from "@/lib/api";

const SCOPE_WORDS: Record<string, (k: string) => string> = {
  global: () => "everywhere",
  sector: (k) => `all companies in industry ${k}`,
  company: (k) => `company ${k}`,
  statement: (k) => `statement ${k.replace(":", " · ")}`,
  export: (k) => `export profile ${k}`,
};
const KEY_WORDS: Record<string, string> = { scale: "Scale", statement: "Statement that opens first", periods_shown: "Periods shown" };

export default function PrefsSettings({ initial, defaults }: { initial: Pref[]; defaults: Record<string, unknown> }) {
  const [prefs, setPrefs] = useState(initial);
  const [paste, setPaste] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const reload = async () => {
    const r = await fetch("/api/prefs");
    if (r.ok) setPrefs(((await r.json()) as { prefs: Pref[] }).prefs);
  };
  const reset = async (p: Pref) => {
    await fetch(`/api/prefs?${new URLSearchParams({ scope: p.scope, scope_key: p.scope_key, key: p.key })}`, { method: "DELETE" });
    await reload();
  };
  const exportAll = async () => {
    const r = await fetch("/api/prefs/export", { method: "POST" });
    const text = JSON.stringify(await r.json(), null, 2);
    await navigator.clipboard.writeText(text).catch(() => null);
    setPaste(text);
    setMsg("Copied to the clipboard, and shown below so you can save it.");
  };
  const importAll = async () => {
    try {
      const doc = JSON.parse(paste) as { prefs?: Pref[] };
      const r = await fetch("/api/prefs/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prefs: doc.prefs ?? [] }) });
      const d = (await r.json()) as { imported?: number };
      setMsg(`Imported ${d.imported ?? 0} preference${d.imported === 1 ? "" : "s"}.`);
      await reload();
    } catch {
      setMsg("That is not a preferences export.");
    }
  };
  const resetAll = async () => {
    if (!confirm("Reset every preference to its default?")) return;
    await fetch("/api/prefs/reset", { method: "POST" });
    await reload();
  };

  const sorted = [...prefs].sort((a, b) => a.key.localeCompare(b.key) || a.scope.localeCompare(b.scope));
  return (
    <>
      {sorted.length === 0 ? (
        <div className="empty">
          <p>Nothing set yet. Everything is at its default.</p>
          <p className="muted">Change the scale or the statement on any company and it lands here, with the scope it applies to.</p>
        </div>
      ) : (
        <table className="prefs">
          <thead>
            <tr>
              <th>Preference</th>
              <th>Value</th>
              <th>Applies to</th>
              <th>How</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((p) => (
              <tr key={`${p.scope}|${p.scope_key}|${p.key}`}>
                <td>{KEY_WORDS[p.key] ?? p.key}</td>
                <td>{String(p.value)}</td>
                <td>{(SCOPE_WORDS[p.scope] ?? ((k: string) => `${p.scope} ${k}`))(p.scope_key)}</td>
                <td className="muted">{p.source === "explicit" ? "you set it" : p.source === "inferred" ? "suggested, you accepted" : "preset"}</td>
                <td className="actions">
                  <button type="button" className="linkbtn" onClick={() => reset(p)}>
                    Reset to default{typeof defaults[p.key] !== "undefined" ? ` (${String(defaults[p.key])})` : ""}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="toolbar" style={{ marginTop: 20 }}>
        <button type="button" className="btn secondary" onClick={exportAll}>Export as JSON</button>
        <button type="button" className="btn secondary" onClick={importAll} disabled={!paste.trim()}>Import from the box</button>
        <button type="button" className="btn secondary" onClick={resetAll} disabled={!prefs.length}>Reset everything</button>
      </div>
      <textarea className="json" value={paste} onChange={(e) => setPaste(e.target.value)} placeholder="Paste a preferences export here to import it, or export yours to see it." rows={6} />
      {msg && <p className="muted">{msg}</p>}
    </>
  );
}
