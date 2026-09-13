import "server-only";
import { requestHeaders } from "@/lib/server-api";

const configured = process.env.FILINGS_API_URL || "http://localhost:8000";
const base = (/^https?:\/\//.test(configured) ? configured : `http://${configured}`).replace(/\/$/, "");

/** Private server transport. User-supplied identity headers never enter this request. */
export async function workspaceRequest<T>(path: string, method: "GET" | "POST" | "PATCH" | "DELETE" = "GET", body?: unknown):
  Promise<{ ok: boolean; status: number; data: T | null; error: string | null }> {
  try {
    const response = await fetch(`${base}${path}`, { method, headers: { ...await requestHeaders(), ...(body === undefined ? {} : { "Content-Type": "application/json" }) }, ...(body === undefined ? {} : { body: JSON.stringify(body) }), cache: "no-store", signal: AbortSignal.timeout(20_000) });
    const payload = await response.json().catch(() => null);
    const detail = typeof payload?.detail === "string" ? payload.detail : typeof payload?.error === "string" ? payload.error : null;
    return { ok: response.ok, status: response.status, data: response.ok ? payload as T : null, error: response.ok ? null : detail };
  } catch {
    return { ok: false, status: 502, data: null, error: null };
  }
}

export function sameOriginMutation(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (origin) return origin === new URL(request.url).origin;
  return request.headers.get("sec-fetch-site") !== "cross-site";
}
