"use client";
// Preference writes from the browser: to the account when signed in, to this browser otherwise.

export type Scope = "global" | "sector" | "company" | "statement" | "export";
export type PrefWrite = { scope: Scope; scope_key: string; key: string; value: unknown; source?: "explicit" | "inferred" | "preset" };
export type PrefContext = { cik?: string | number; sic?: string | null; statement?: string; profile?: string };

const localKey = (p: Omit<PrefWrite, "value" | "source">) => `fh:pref:${p.scope}:${p.scope_key}:${p.key}`;

/** The scope_key a context has at a scope; null when the context lacks it (mirrors accounts.scope_key_for). */
export function scopeKeyFor(scope: Scope, ctx: PrefContext): string | null {
  if (scope === "global") return "";
  if (scope === "sector") return ctx.sic || null;
  if (scope === "company") return ctx.cik !== undefined ? String(ctx.cik) : null;
  if (scope === "statement") return ctx.cik !== undefined && ctx.statement ? `${ctx.cik}:${ctx.statement}` : null;
  if (scope === "export") return ctx.profile || null; // export profiles: the scope_key is the profile name
  return null;
}

export const scopeWords = (scope: string): string =>
  scope === "company" ? "for this company" : scope === "statement" ? "for this statement" : scope === "sector" ? "for this industry" : scope === "global" ? "everywhere" : "default";

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

export async function resetPref(p: Omit<PrefWrite, "value" | "source">, signedIn: boolean): Promise<boolean> {
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

/** Browser-only resolution for signed-out visitors: statement -> company -> sector -> global. */
export function readLocalPref<T>(key: string, ctx: PrefContext): { value: T; scope: string; scope_key: string } | null {
  for (const scope of ["statement", "company", "sector", "global"] as Scope[]) {
    const scope_key = scopeKeyFor(scope, ctx);
    if (scope_key === null) continue;
    try {
      const raw = window.localStorage.getItem(localKey({ scope, scope_key, key }));
      if (raw !== null) return { value: JSON.parse(raw) as T, scope, scope_key };
    } catch {
      /* ignore */
    }
  }
  return null;
}

/** Every browser-kept preference, in the API's shape (used to import them into a new account). */
export function listLocalPrefs(): PrefWrite[] {
  const out: PrefWrite[] = [];
  try {
    for (let i = 0; i < window.localStorage.length; i++) {
      const k = window.localStorage.key(i);
      if (!k || !k.startsWith("fh:pref:")) continue;
      const [, , scope, scope_key, ...rest] = k.split(":");
      const key = rest.join(":");
      if (!scope || !key) continue;
      out.push({ scope: scope as Scope, scope_key: scope_key ?? "", key, value: JSON.parse(window.localStorage.getItem(k) ?? "null") });
    }
  } catch {
    /* ignore */
  }
  return out;
}

/** A UI event for the touch report. Signed-out visitors are not tracked. Never throws, never awaited. */
export function logEvent(name: string, props: Record<string, unknown> = {}, signedIn = true): void {
  if (!signedIn) return;
  try {
    void fetch("/api/events", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, props }), keepalive: true }).catch(() => null);
  } catch {
    /* ignore */
  }
}
