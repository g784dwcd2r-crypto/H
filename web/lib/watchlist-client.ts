"use client";
// The account's watchlist: one global preference (`watchlist`) holding the followed companies.
// The browser's list is merged in the first time a signed-in person touches it, then cleared.

import { watchlist as local, type Remembered } from "@/lib/local";

const IMPORTED = "fh:watchlist:imported";
let cache: Remembered[] | null = null;

async function fetchList(): Promise<Remembered[]> {
  try {
    const r = await fetch("/api/prefs");
    if (!r.ok) return [];
    const d = (await r.json()) as { prefs: { scope: string; key: string; value: unknown }[] };
    const p = d.prefs.find((x) => x.scope === "global" && x.key === "watchlist");
    return Array.isArray(p?.value) ? (p!.value as Remembered[]) : [];
  } catch {
    return [];
  }
}

async function write(list: Remembered[]): Promise<void> {
  cache = list;
  await fetch("/api/prefs", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scope: "global", scope_key: "", key: "watchlist", value: list }),
  });
}

export const accountWatchlist = {
  /** The account's list, importing the browser's followed companies the first time. */
  load: async (initial?: Remembered[]): Promise<Remembered[]> => {
    let list = cache ?? initial ?? (await fetchList());
    let imported = false;
    try {
      imported = window.localStorage.getItem(IMPORTED) === "1";
    } catch {
      imported = true;
    }
    if (!imported) {
      const mine = local.list();
      const merged = [...list, ...mine.filter((m) => !list.some((x) => x.cik === m.cik))];
      if (merged.length !== list.length) {
        list = merged;
        await write(list);
      }
      try {
        window.localStorage.setItem(IMPORTED, "1");
      } catch {
        /* ignore */
      }
    }
    cache = list;
    return list;
  },
  toggle: async (c: Remembered): Promise<boolean> => {
    const list = await accountWatchlist.load();
    const on = list.some((x) => x.cik === c.cik);
    await write(on ? list.filter((x) => x.cik !== c.cik) : [...list, c]);
    return !on;
  },
  remove: async (cik: number): Promise<Remembered[]> => {
    const list = await accountWatchlist.load();
    const next = list.filter((x) => x.cik !== cik);
    await write(next);
    return next;
  },
};
