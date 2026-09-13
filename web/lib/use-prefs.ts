"use client";
// Update the displayed preference only after persistence succeeds. Per-key writes are serialized.
import { useCallback, useEffect, useRef, useState } from "react";
import type { Pref } from "@/lib/api";
import { listLocalPrefs, resetPref, savePref, scopeKeyFor, type PrefContext, type PrefWrite, type Scope } from "@/lib/prefs-client";

export const RESOLUTION: Scope[] = ["statement", "company", "sector", "global"];
export type Where = { value: unknown; scope: string; scope_key: string; source: string };
export function resolveIn(list: PrefWrite[], key: string, ctx: PrefContext): Where | null {
  for (const scope of RESOLUTION) {
    const sk = scopeKeyFor(scope, ctx);
    if (sk === null) continue;
    const p = list.find((x) => x.scope === scope && x.scope_key === sk && x.key === key);
    if (p) return { value: p.value, scope, scope_key: sk, source: p.source ?? "explicit" };
  }
  return null;
}

export function usePrefs(initial: Pref[] | PrefWrite[], signedIn: boolean) {
  const [list, setList] = useState<PrefWrite[]>(initial as PrefWrite[]);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef(new Map<string, Promise<boolean>>());
  useEffect(() => { setList(signedIn ? initial as PrefWrite[] : listLocalPrefs()); }, [initial, signedIn]);
  const get = useCallback((key: string, ctx: PrefContext) => resolveIn(list, key, ctx), [list]);
  const enqueue = useCallback((identity: string, action: () => Promise<boolean>) => {
    const prior = pending.current.get(identity) ?? Promise.resolve(true);
    const next = prior.catch(() => false).then(action);
    pending.current.set(identity, next);
    void next.finally(() => { if (pending.current.get(identity) === next) pending.current.delete(identity); });
    return next;
  }, []);
  const set = useCallback(async (key: string, value: unknown, scope: Scope, ctx: PrefContext, source: PrefWrite["source"] = "explicit") => {
    const scope_key = scopeKeyFor(scope, ctx);
    if (scope_key === null) return false;
    const p: PrefWrite = { scope, scope_key, key, value, source };
    return enqueue(`${scope}|${scope_key}|${key}`, async () => {
      try {
        if (!await savePref(p, signedIn)) throw new Error("Preference save failed");
        setList((cur) => [...cur.filter((x) => !(x.scope === scope && x.scope_key === scope_key && x.key === key)), p]);
        setError(null); return true;
      } catch { setError("Your preference could not be saved. The previous saved setting is still in use."); return false; }
    });
  }, [signedIn, enqueue]);
  const reset = useCallback(async (key: string, scope: Scope, ctx: PrefContext) => {
    const scope_key = scopeKeyFor(scope, ctx);
    if (scope_key === null) return false;
    return enqueue(`${scope}|${scope_key}|${key}`, async () => {
      try {
        if (!await resetPref({ scope, scope_key, key }, signedIn)) throw new Error("Preference reset failed");
        setList((cur) => cur.filter((x) => !(x.scope === scope && x.scope_key === scope_key && x.key === key)));
        setError(null); return true;
      } catch { setError("Your preference could not be reset. The previous saved setting is still in use."); return false; }
    });
  }, [signedIn, enqueue]);
  return { list, get, set, reset, setList, error };
}
export type Prefs = ReturnType<typeof usePrefs>;
