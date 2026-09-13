"use client";
// Fetch the current owner and let the server apply atomic changes across tabs/devices.
import type { Remembered } from "@/lib/local";
type Snapshot = { user_id: string; companies: Remembered[] };

async function fetchList(): Promise<Snapshot> {
  const r = await fetch("/api/watchlist", { cache: "no-store" });
  if (!r.ok) throw new Error("Your watchlist could not be loaded. Please try again.");
  return await r.json() as Snapshot;
}

async function change(action: "toggle" | "remove", cik: number): Promise<Snapshot & { followed: boolean }> {
  const { user_id } = await fetchList();
  const r = await fetch("/api/watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, cik, expected_user_id: user_id }),
  });
  if (!r.ok) throw new Error(r.status === 409 ? "Your account changed. Reload this page before changing your watchlist." : "Your watchlist could not be saved. Please try again.");
  return await r.json();
}

export const accountWatchlist = {
  load: async (_initial?: Remembered[]): Promise<Remembered[]> => (await fetchList()).companies,
  toggle: async (company: Remembered): Promise<boolean> => (await change("toggle", company.cik)).followed,
  remove: async (cik: number): Promise<Remembered[]> => (await change("remove", cik)).companies,
};
