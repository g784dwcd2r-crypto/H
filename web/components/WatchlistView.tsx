"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { RecentFiling } from "@/lib/api";
import { fmtDate } from "@/lib/api";
import { watchlist, type Remembered } from "@/lib/local";
import { accountWatchlist } from "@/lib/watchlist-client";

export default function WatchlistView({ signedIn, initial }: { signedIn: boolean; initial: Remembered[] | null }) {
  const [list, setList] = useState<Remembered[] | null>(null);
  const [filings, setFilings] = useState<RecentFiling[] | null>(null);
  const [days, setDays] = useState(14);
  const [email, setEmail] = useState("");
  const [sub, setSub] = useState<"idle" | "sending" | "done" | "error" | "off">("idle");

  useEffect(() => {
    if (!signedIn) {
      setList(watchlist.list());
      return;
    }
    void accountWatchlist.load(initial ?? undefined).then(setList);
  }, [signedIn, initial]);
  const unfollow = async (c: Remembered) => {
    if (!signedIn) {
      watchlist.toggle(c);
      setList(watchlist.list());
      return;
    }
    setList(await accountWatchlist.remove(c.cik));
  };
  useEffect(() => {
    if (!list) return;
    if (!list.length) {
      setFilings([]);
      return;
    }
    setFilings(null);
    fetch(`/api/recent?ciks=${list.map((c) => c.cik).join(",")}&days=${days}`)
      .then((r) => r.json())
      .then((d: { filings: RecentFiling[] }) => setFilings(d.filings ?? []))
      .catch(() => setFilings([]));
  }, [list, days]);

  if (list === null) return null;
  if (!list.length)
    return (
      <div className="empty">
        <p>Nothing followed yet.</p>
        <p className="muted">Open a company and press “Follow”. This page then shows what your companies filed, and you can get the results filings by email.{signedIn ? " Companies you follow are kept on your account." : " Sign in to keep the list on every device."}</p>
        <Link href="/" className="btn">Find a company</Link>
      </div>
    );
  const results = (filings ?? []).filter((f) => f.is_results);
  const rest = (filings ?? []).filter((f) => !f.is_results);
  return (
    <>
      <p className="chips">
        {list.map((c) => (
          <span key={c.cik} className="chip link">
            <Link href={`/companies/${c.cik}`}>{c.ticker ?? c.name}</Link>
            <button type="button" className="x" aria-label={`Stop following ${c.name}`} onClick={() => void unfollow(c)}>×</button>
          </span>
        ))}
      </p>
      <div className="toolbar">
        <label className="muted">
          Show the last{" "}
          <select value={days} onChange={(e) => setDays(parseInt(e.target.value, 10))}>
            <option value={1}>day</option>
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
          </select>
        </label>
      </div>
      {filings === null ? (
        <p className="muted">Looking…</p>
      ) : (
        <>
          <h2 className="h-small">Results filings</h2>
          {results.length === 0 ? (
            <p className="muted">None of your companies filed results in this window.</p>
          ) : (
            <Table rows={results} />
          )}
          <h2 className="h-small">Everything else</h2>
          {rest.length === 0 ? <p className="muted">Quiet.</p> : <Table rows={rest} />}
        </>
      )}
      <section className="subscribe">
        <p className="eyebrow">Email me the results filings</p>
        {sub === "done" ? (
          <p className="muted">Done. Each weekday morning you get one email when any of these companies filed results.</p>
        ) : sub === "off" ? (
          <p className="muted">Email alerts are not switched on for this deployment yet.</p>
        ) : (
          <form
            className="row"
            onSubmit={async (e) => {
              e.preventDefault();
              setSub("sending");
              const r = await fetch("/api/subscribe", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, ciks: list.map((c) => c.cik) }) });
              setSub(r.ok ? "done" : r.status === 503 ? "off" : "error");
            }}
          >
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@fund.com" required />
            <button className="btn" type="submit" disabled={sub === "sending"}>Subscribe</button>
            {sub === "error" && <span className="muted">That did not go through; check the address.</span>}
          </form>
        )}
      </section>
    </>
  );
}

function Table({ rows }: { rows: RecentFiling[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Filed</th>
          <th>Company</th>
          <th>What it is</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {rows.map((f) => (
          <tr key={f.accession + f.cik}>
            <td className="nowrap">{fmtDate(f.filed_date)}</td>
            <td><Link href={`/companies/${f.cik}`}>{f.name ?? f.cik}</Link>{f.ticker && <span className="muted"> · {f.ticker}</span>}</td>
            <td>{f.is_results && f.form === "8-K" ? "Earnings release (8-K)" : f.label}</td>
            <td className="actions">
              <Link href={`/companies/${f.cik}/filings/${f.accession}`}>Read</Link>
              <a href={f.primary_doc_url ?? f.filing_index_url ?? "#"} target="_blank" rel="noreferrer">sec.gov</a>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
