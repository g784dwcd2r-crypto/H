import WatchlistView from "@/components/WatchlistView";
import { api } from "@/lib/server-api";
import type { Remembered } from "@/lib/local";
import { sessionToken } from "@/lib/session";

export const dynamic = "force-dynamic";
export const metadata = { title: "Watchlist · Disclosure" };

export default async function WatchlistPage() {
  const token = await sessionToken();
  let initial: Remembered[] | null = null;
  if (token) {
    try {
      const p = (await api.listPrefs(token)).prefs.find((x) => x.scope === "global" && x.key === "watchlist");
      initial = Array.isArray(p?.value) ? (p!.value as Remembered[]) : [];
    } catch {
      initial = [];
    }
  }
  return (
    <>
      <p className="eyebrow">Watchlist</p>
      <h1>Your companies. What’s new.</h1>
      <p className="lead">A focused view of the companies you follow. Review recent results and related filings, then go straight to the source.</p>
      <WatchlistView signedIn={!!token} initial={initial} />
    </>
  );
}
