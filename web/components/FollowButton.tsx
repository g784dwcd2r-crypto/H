"use client";

import { useEffect, useState } from "react";
import { recents, watchlist, type Remembered } from "@/lib/local";

// Remembers the visit and toggles the company on the browser's watchlist.
export default function FollowButton({ company }: { company: Remembered }) {
  const [on, setOn] = useState(false);
  useEffect(() => {
    recents.remember(company);
    setOn(watchlist.has(company.cik));
  }, [company]);
  return (
    <button type="button" className={"btn secondary follow" + (on ? " on" : "")} onClick={() => setOn(watchlist.toggle(company))}>
      {on ? "✓ Following" : "+ Follow"}
    </button>
  );
}
