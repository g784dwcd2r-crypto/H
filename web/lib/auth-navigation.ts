import { validLoginRegion, type LoginRegion } from "./public-navigation";

export const REGION_COOKIE = "fh_region";
export const OAUTH_COOKIE = "fh_oauth_state";
export const OAUTH_COOKIE_PATH = "/auth/google/callback";
const ALLOWED = /^\/(?:research|companies|watchlist|projects|compare|coverage|settings|early-access|platform|solutions|resources|security|privacy|company|demo)(?:\/|$)/;

/** Authentication may resume only a known local product page, never an auth/API route or another origin. */
export function safeAuthNext(value: unknown, fallback = "/"): string {
  if (typeof value !== "string" || value.length > 2048 || !value.startsWith("/") || value.startsWith("//") || /[\\\u0000-\u0020\u007f]/.test(value)) return fallback;
  try {
    const parsed = new URL(value, "https://disclosure.local");
    const decodedPath = decodeURIComponent(parsed.pathname);
    if (parsed.origin !== "https://disclosure.local" || /[\\\u0000-\u0020\u007f]/.test(decodedPath) || decodedPath.includes("//") || decodedPath.split("/").some(part => part === "." || part === "..")) return fallback;
    if (decodedPath !== "/" && !ALLOWED.test(decodedPath)) return fallback;
    // Encoded separators can be interpreted differently by a proxy and the web router.
    if (/%(?:2f|5c|25)/i.test(parsed.pathname)) return fallback;
    return parsed.pathname + parsed.search + parsed.hash;
  } catch { return fallback; }
}

export function authRegion(value: unknown, remembered?: unknown): LoginRegion | null {
  return validLoginRegion(value) ? value : validLoginRegion(remembered) ? remembered : null;
}

export function authHref(path: "/signin" | "/signup" | "/auth/google", next: string, region: LoginRegion | null, error?: string) {
  const query = new URLSearchParams();
  if (next !== "/") query.set("next", safeAuthNext(next));
  if (region) query.set("region", region);
  if (error) query.set("error", error);
  return path + (query.size ? "?" + query.toString() : "");
}

export type OAuthContext = { state: string; next: string; region: LoginRegion | null };

/** Context lives together in an httpOnly cookie, bound to the random state sent to Google. */
export function readOAuthContext(cookie: string | undefined, returnedState: string): OAuthContext | null {
  if (!cookie || !returnedState) return null;
  try {
    const context = JSON.parse(cookie) as Partial<OAuthContext>;
    if (typeof context.state !== "string" || context.state.length < 20 || context.state !== returnedState) return null;
    return { state: context.state, next: safeAuthNext(context.next), region: authRegion(context.region) };
  } catch { return null; }
}
