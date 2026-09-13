"use client";

import { useState } from "react";
import type { PrefContext, Scope } from "@/lib/prefs-client";
import { scopeKeyFor, scopeWords } from "@/lib/prefs-client";
import type { Prefs } from "@/lib/use-prefs";

export type Option<T> = { value: T; label: string };

/**
 * One preference, one control. Shows the value, where it is set from ("set for this company",
 * "default"), and a scope selector for where the next change applies. Every preference control on the
 * site is this component, so they all behave the same way.
 */
export default function PrefControl<T extends string | number | boolean>({
  prefs,
  prefKey,
  label,
  options,
  fallback,
  valueOverride,
  ctx,
  scopes,
  defaultScope = "company",
  onChange,
  onSaved,
  title,
  kind = "select",
}: {
  prefs: Prefs;
  prefKey: string;
  label: string;
  options: Option<T>[];
  fallback: T;
  valueOverride?: T;
  ctx: PrefContext;
  scopes: Scope[];
  defaultScope?: Scope;
  onChange?: (value: T) => void;
  onSaved?: (text: string) => void;
  title?: string;
  kind?: "select" | "toggle";
}) {
  const where = prefs.get(prefKey, ctx);
  const value = (valueOverride !== undefined ? valueOverride : where && options.some((o) => o.value === where.value) ? where.value : fallback) as T;
  const available = scopes.filter((s) => scopeKeyFor(s, ctx) !== null);
  const [writeScope, setWriteScope] = useState<Scope>(() =>
    where && available.includes(where.scope as Scope) ? (where.scope as Scope) : available.includes(defaultScope) ? defaultScope : available[0],
  );
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async (v: T, scope: Scope = writeScope) => {
    setPending(true); setError(null);
    const ok = await prefs.set(prefKey, v, scope, ctx);
    setPending(false);
    if (!ok) { setError("Couldn’t save. Please try again."); return; }
    setWriteScope(scope);
    onSaved?.(`${label} saved ${scopeWords(scope)}`);
    onChange?.(v);
  };
  const parse = (raw: string): T => {
    const o = options.find((x) => String(x.value) === raw);
    return (o ? o.value : fallback) as T;
  };
  const setScope = (scope: Scope) => {
    // moving the current value to a different scope is itself a choice
    void save(value, scope);
  };
  const tag = where ? `set ${scopeWords(where.scope)}` : "default";
  return (
    <span className="prefctl" title={title}>
      {kind === "toggle" ? (
        <label className="muted check">
          <input type="checkbox" disabled={pending} checked={Boolean(value)} onChange={(e) => void save(e.target.checked as T)} /> {label}
        </label>
      ) : (
        <label className="muted">
          {label}{" "}
          <select disabled={pending} value={String(value)} onChange={(e) => void save(parse(e.target.value))}>
            {options.map((o) => (
              <option key={String(o.value)} value={String(o.value)}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="scopetag" title="Where this choice applies. Statement, then company, then industry, then everywhere; the most specific wins.">
        <select disabled={pending} value={writeScope} onChange={(e) => setScope(e.target.value as Scope)} aria-label={`Where ${label} applies`}>
          {available.map((s) => (
            <option key={s} value={s}>
              {scopeWords(s)}
            </option>
          ))}
        </select>
        <span className={"tag " + (where ? "set" : "")}>{tag}</span>
      </label>
      {error && <span className="err" role="alert">{error}</span>}
    </span>
  );
}
