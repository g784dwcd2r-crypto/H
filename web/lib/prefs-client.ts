"use client";
// Preference writes from the browser: to the account when signed in, to this browser otherwise.

export type PrefWrite = { scope: "global" | "company" | "sector" | "statement"; scope_key: string; key: string; value: unknown };

const localKey = (p: Omit<PrefWrite, "value">) => `fh:pref:${p.scope}:${p.scope_key}:${p.key}`;

export async function savePref(p: PrefWrite, signedIn: boolean): Promise<boolean> {
  if (!signedIn) {
    try {
      window.localStorage.setItem(localKey(p), JSON.stringify(p.value));
    } catch {
      /* ignore */
    }
    return true;
  }
  const r = await fetch("/api/prefs", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(p) });
  return r.ok;
}

export async function resetPref(p: Omit<PrefWrite, "value">, signedIn: boolean): Promise<boolean> {
  if (!signedIn) {
    try {
      window.localStorage.removeItem(localKey(p));
    } catch {
      /* ignore */
    }
    return true;
  }
  const q = new URLSearchParams({ scope: p.scope, scope_key: p.scope_key, key: p.key });
  const r = await fetch(`/api/prefs?${q}`, { method: "DELETE" });
  return r.ok;
}

/** Browser-only resolution for signed-out visitors: statement -> company -> global. */
export function readLocalPref<T>(key: string, ctx: { cik?: string | number; statement?: string }): { value: T; scope: string } | null {
  const tries: [string, string][] = [];
  if (ctx.cik !== undefined && ctx.statement) tries.push(["statement", `${ctx.cik}:${ctx.statement}`]);
  if (ctx.cik !== undefined) tries.push(["company", String(ctx.cik)]);
  tries.push(["global", ""]);
  for (const [scope, scope_key] of tries) {
    try {
      const raw = window.localStorage.getItem(localKey({ scope: scope as PrefWrite["scope"], scope_key, key }));
      if (raw !== null) return { value: JSON.parse(raw) as T, scope };
    } catch {
      /* ignore */
    }
  }
  return null;
}
