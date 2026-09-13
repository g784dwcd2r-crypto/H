"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { recents, watchlist, type Remembered } from "@/lib/local";

export default function RecentCompanies() {
  const [recent, setRecent] = useState<Remembered[]>([]);
  const [watched, setWatched] = useState<Remembered[]>([]);
  useEffect(() => {
    setRecent(recents.list());
    setWatched(watchlist.list());
  }, []);
  if (!recent.length && !watched.length) return null;
  return (
    <div className="quick">
      {watched.length > 0 && (
        <div>
          <p className="eyebrow">Following</p>
          <p className="chips">
            {watched.map((c) => (
              <Link key={c.cik} href={`/companies/${c.cik}`} className="chip link">
                {c.ticker ?? c.name}
              </Link>
            ))}
            <Link href="/watchlist" className="chip link muted">
              what they filed →
            </Link>
          </p>
        </div>
      )}
      {recent.length > 0 && (
        <div>
          <p className="eyebrow">Recently opened</p>
          <p className="chips">
            {recent.map((c) => (
              <Link key={c.cik} href={`/companies/${c.cik}`} className="chip link">
                {c.ticker ?? c.name}
              </Link>
            ))}
          </p>
        </div>
      )}
    </div>
  );
}
