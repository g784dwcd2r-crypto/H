// Server-side session: the signed token lives in an httpOnly cookie; the API verifies it.
import { cookies } from "next/headers";
import { api } from "@/lib/server-api";
import { type Resolved, type User } from "@/lib/api";

export const SESSION_COOKIE = "fh_session";
export const SESSION_DAYS = 30;

export const DEFAULTS: Record<string, unknown> = {
  scale: "millions",
  statement: "IS",
  periods_shown: 8,
  negative_style: "parentheses",
  column_order: "newest_right",
  period_mode: "as_filed",
  restated: false,
  headline_cards: ["revenue", "net_income", "eps_diluted", "operating_cash_flow"],
  export_config: {},
};

export async function sessionToken(): Promise<string | null> {
  try {
    const jar = await cookies();
    return jar.get(SESSION_COOKIE)?.value ?? null;
  } catch {
    return null;
  }
}

export async function currentUser(): Promise<User | null> {
  const token = await sessionToken();
  if (!token) return null;
  try {
    return (await api.me(token)).user;
  } catch {
    return null;
  }
}

/** Resolved preferences for a context; system defaults when signed out or the API is unreachable. */
export async function resolvedPrefs(ctx: { cik?: string | number; sic?: string | null; statement?: string }): Promise<{ prefs: Resolved; signedIn: boolean }> {
  const token = await sessionToken();
  const fallback: Resolved = Object.fromEntries(
    Object.entries(DEFAULTS).map(([k, v]) => [k, { value: v, scope: "default", scope_key: "", source: "default" }]),
  );
  if (!token) return { prefs: fallback, signedIn: false };
  try {
    const r = await api.resolvePrefs(token, { ...ctx, sic: ctx.sic ?? undefined });
    return { prefs: { ...fallback, ...r.prefs }, signedIn: true };
  } catch {
    return { prefs: fallback, signedIn: false };
  }
}
