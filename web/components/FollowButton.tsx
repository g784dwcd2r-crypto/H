"use client";

import { useEffect, useState } from "react";
import { recents, watchlist, type Remembered } from "@/lib/local";
import { logEvent } from "@/lib/prefs-client";
import { accountWatchlist } from "@/lib/watchlist-client";

/**
 * Remembers the visit and toggles the company on the watchlist: the account's when signed in (the
 * browser's list is imported into the account the first time), this browser's otherwise.
 */
export default function FollowButton({ company, signedIn, initial }: { company: Remembered; signedIn: boolean; initial?: Remembered[] }) {
  const [on, setOn] = useState(false);
  useEffect(() => {
    recents.remember(company);
    if (!signedIn) {
      setOn(watchlist.has(company.cik));
      return;
    }
    void accountWatchlist.load(initial).then((list) => setOn(list.some((x) => x.cik === company.cik)));
  }, [company, signedIn, initial]);
  const toggle = async () => {
    if (!signedIn) {
      setOn(watchlist.toggle(company));
      return;
    }
    const next = await accountWatchlist.toggle(company);
    setOn(next);
    logEvent(next ? "follow.add" : "follow.remove", { cik: company.cik }, true);
  };
  return (
    <button type="button" className={"btn secondary follow" + (on ? " on" : "")} onClick={() => void toggle()}>
      {on ? "✓ Following" : "+ Follow"}
    </button>
  );
}
