"use client";
// One hook for every preference control: holds the person's preference list (the account's when signed
// in, this browser's otherwise), resolves a key for a context the same way the API does, and writes back.

import { useCallback, useEffect, useState } from "react";
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
  useEffect(() => {
    if (!signedIn) setList(listLocalPrefs());
  }, [signedIn]);

  const get = useCallback((key: string, ctx: PrefContext) => resolveIn(list, key, ctx), [list]);

  const set = useCallback(
    async (key: string, value: unknown, scope: Scope, ctx: PrefContext, source: PrefWrite["source"] = "explicit") => {
      const scope_key = scopeKeyFor(scope, ctx);
      if (scope_key === null) return false;
      const p: PrefWrite = { scope, scope_key, key, value, source };
      setList((cur) => [...cur.filter((x) => !(x.scope === scope && x.scope_key === scope_key && x.key === key)), p]);
      return savePref(p, signedIn);
    },
    [signedIn],
  );

  const reset = useCallback(
    async (key: string, scope: Scope, ctx: PrefContext) => {
      const scope_key = scopeKeyFor(scope, ctx);
      if (scope_key === null) return false;
      setList((cur) => cur.filter((x) => !(x.scope === scope && x.scope_key === scope_key && x.key === key)));
      return resetPref({ scope, scope_key, key }, signedIn);
    },
    [signedIn],
  );

  return { list, get, set, reset, setList };
}

export type Prefs = ReturnType<typeof usePrefs>;
