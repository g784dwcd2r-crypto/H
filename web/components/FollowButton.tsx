"use client";

import { useEffect, useState } from "react";
import { recents, watchlist, type Remembered } from "@/lib/local";
import { logEvent } from "@/lib/prefs-client";
import { accountWatchlist } from "@/lib/watchlist-client";
import { StarIcon } from "@/components/Icons";

export default function FollowButton({ company, signedIn, initial }: { company: Remembered; signedIn: boolean; initial?: Remembered[] }) {
  const [on, setOn] = useState(false);
  const [busy, setBusy] = useState(signedIn);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    recents.remember(company);
    if (!signedIn) { setOn(watchlist.has(company.cik)); setBusy(false); return; }
    setBusy(true);
    void accountWatchlist.load(initial).then((list) => { if (alive) { setOn(list.some((x) => x.cik === company.cik)); setError(null); } }).catch(() => { if (alive) setError("Your watchlist couldn’t load. Try again."); }).finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [company, signedIn, initial]);
  const toggle = async () => {
    setBusy(true); setError(null);
    try {
      if (!signedIn) { setOn(watchlist.toggle(company)); return; }
      const next = await accountWatchlist.toggle(company); setOn(next);
      logEvent(next ? "follow.add" : "follow.remove", { cik: company.cik }, true);
    } catch { setError("Couldn’t save your watchlist. Please try again."); }
    finally { setBusy(false); }
  };
  return <div className="follow-control"><button type="button" disabled={busy} aria-pressed={on} className={"btn secondary follow" + (on ? " on" : "")} onClick={() => void toggle()}><StarIcon />{busy ? "Loading…" : on ? "Following" : "Follow company"}</button>{error && <p className="err" role="alert">{error}</p>}</div>;
}
