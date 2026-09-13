"use client";

import { useState } from "react";
import { fmtEps, fmtMoney, type Metrics, type Pref } from "@/lib/api";
import { logEvent, scopeWords, type PrefContext, type Scope } from "@/lib/prefs-client";
import { usePrefs } from "@/lib/use-prefs";

const SLOTS = 4;
const fmt = (key: string, v: number | null | undefined): string => {
  if (key.startsWith("eps")) return fmtEps(v);
  if (key === "shares_diluted") return v === null || v === undefined ? "–" : `${(v / 1e6).toFixed(1)}M`;
  return fmtMoney(v);
};

/**
 * The company page's headline numbers. Four slots, each swappable to any metric the statements carry;
 * the industry preset (banks: net interest income, provisions...) is the starting point and the choice
 * is remembered for the company, the industry or everywhere.
 */
export default function HeadlineCards({
  cik,
  sic,
  signedIn,
  initialPrefs,
  preset,
  labels,
  latest,
  prior,
  periodLabel,
  priorLabel,
}: {
  cik: string;
  sic: string | null;
  signedIn: boolean;
  initialPrefs: Pref[];
  preset: string[];
  labels: Record<string, string>;
  latest: Metrics | null;
  prior: Metrics | null;
  periodLabel: string | null;
  priorLabel: string | null;
}) {
  const ctx: PrefContext = { cik, sic };
  const prefs = usePrefs(initialPrefs, signedIn);
  const where = prefs.get("headline_cards", ctx);
  const chosen = Array.isArray(where?.value) ? (where!.value as string[]).filter((k) => k in labels) : [];
  const cards = [...chosen, ...preset.filter((k) => !chosen.includes(k))].slice(0, SLOTS);
  const [scope, setScope] = useState<Scope>((where?.scope as Scope) || "company");
  const [editing, setEditing] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const available = Object.keys(labels).filter((k) => latest && latest[k] !== null && latest[k] !== undefined);

  const save = async (next: string[], s: Scope = scope) => {
    setScope(s);
    if (!await prefs.set("headline_cards", next, s, ctx)) return;
    setMsg(`Cards saved ${scopeWords(s)}`);
    setTimeout(() => setMsg(null), 1800);
  };
  const swap = (i: number, key: string) => {
    const next = [...cards];
    next[i] = key;
    logEvent("card.swap", { slot: i, metric: key }, signedIn);
    void save(next);
  };
  const usePreset = async () => {
    if (!await prefs.reset("headline_cards", "company", ctx)) return;
    logEvent("card.preset", {}, signedIn);
    setMsg("Industry preset restored for this company");
    setTimeout(() => setMsg(null), 1800);
  };

  return (
    <section className="headline">
      <div className="cards tight">
        {cards.map((key, i) => {
          const v = latest?.[key];
          const p = prior?.[key];
          const delta = v !== null && v !== undefined && p !== null && p !== undefined && p !== 0 ? ((v - p) / Math.abs(p)) * 100 : null;
          return (
            <div key={`${i}-${key}`} className="card">
              <div className="k">
                {editing ? (
                  <select value={key} onChange={(e) => swap(i, e.target.value)} aria-label={`Card ${i + 1}`}>
                    {(available.length ? available : Object.keys(labels)).map((k) => (
                      <option key={k} value={k}>{labels[k]}</option>
                    ))}
                  </select>
                ) : (
                  labels[key] ?? key
                )}
              </div>
              <div className="v">{fmt(key, v)}</div>
              <div className="muted small">
                {periodLabel ?? "–"}
                {delta !== null && priorLabel ? <> · {delta >= 0 ? "+" : ""}{delta.toFixed(1)}% vs {priorLabel}</> : null}
              </div>
            </div>
          );
        })}
      </div>
      <p className="muted small cardsbar">
        <button type="button" className="linkbtn" onClick={() => setEditing((e) => !e)}>{editing ? "Done" : "Change the numbers shown"}</button>
        {editing && (
          <>
            {" · remember "}
            <select value={scope} onChange={(e) => void save(cards, e.target.value as Scope)} aria-label="Where the cards apply">
              <option value="company">for this company</option>
              {sic && <option value="sector">for this industry</option>}
              <option value="global">everywhere</option>
            </select>
            {" · "}
            <button type="button" className="linkbtn" onClick={() => void usePreset()}>use the industry preset</button>
          </>
        )}
        <span className={"tag " + (where ? "set" : "")}>{where ? `set ${scopeWords(where.scope)}` : "industry preset"}</span>
        {msg && <span className="saved"> {msg}</span>}
      </p>
      {prefs.error && <p className="notice" role="alert">{prefs.error}</p>}
    </section>
  );
}
