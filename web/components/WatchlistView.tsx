"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { RecentFiling } from "@/lib/api";
import { fmtDate } from "@/lib/api";
import { watchlist, type Remembered } from "@/lib/local";
import { accountWatchlist } from "@/lib/watchlist-client";
import OwnershipMorning from "@/components/OwnershipMorning";
import { OWNERSHIP_FLOWS, FLOW_COPY, type OwnershipFlow } from "@/lib/ownership";

export default function WatchlistView({ signedIn, initial }: { signedIn: boolean; initial: Remembered[] | null }) {
  const [list, setList] = useState<Remembered[] | null>(null);
  const [filings, setFilings] = useState<RecentFiling[] | null>(null);
  const [days, setDays] = useState(14);
  const [error, setError] = useState<string | null>(null);
  const [filingError, setFilingError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [removing, setRemoving] = useState<number | null>(null);
  const [sub, setSub] = useState<"loading" | "idle" | "sending" | "done" | "error" | "off">(signedIn ? "loading" : "idle");
  const [subscribed, setSubscribed] = useState(false);
  const [alertMessage, setAlertMessage] = useState<string | null>(null);
  const [subscribedCiks, setSubscribedCiks] = useState<number[]>([]);
  const [ownershipFlows, setOwnershipFlows] = useState<OwnershipFlow[]>([]);
  useEffect(() => {
    if (!signedIn) return;
    const controller = new AbortController();
    fetch("/api/subscribe", { signal: controller.signal }).then((response) => { if (!response.ok) throw new Error("Alerts unavailable"); return response.json(); }).then((data: { subscribed: boolean; ciks: number[]; ownership_flows?: OwnershipFlow[] }) => {
      if (controller.signal.aborted) return;
      setSubscribed(data.subscribed); setSubscribedCiks(data.ciks ?? []); setOwnershipFlows((data.ownership_flows ?? []).filter(flow => OWNERSHIP_FLOWS.includes(flow))); setSub("idle");
    }).catch(() => { if (!controller.signal.aborted) setSub("error"); });
    return () => controller.abort();
  }, [signedIn]);
  const saveAlerts = async (enable: boolean) => {
    setSub("sending"); setAlertMessage(null);
    try {
      const response = await fetch("/api/subscribe", { method: enable ? "POST" : "DELETE", headers: { "Content-Type": "application/json" }, ...(enable ? { body: JSON.stringify({ ciks: (list ?? []).map((company) => company.cik), ownership_flows: ownershipFlows }) } : {}) });
      if (response.status === 503) { setSub("off"); return; }
      if (!response.ok) throw new Error("Alerts could not be saved");
      setSubscribed(enable); setSubscribedCiks(enable ? (list ?? []).map((company) => company.cik) : []); setSub("done");
      setAlertMessage(enable ? `Alerts are enabled for this list, using your verified account email.${ownershipFlows.length ? ` Selected ownership groups: ${ownershipFlows.map(flow => FLOW_COPY[flow].title.toLowerCase()).join(", ")}.` : " Ownership alerts are not selected."}` : "Email alerts are paused.");
    } catch { setSub("error"); }
  };

  useEffect(() => {
    if (!signedIn) {
      setList(watchlist.list());
      return;
    }
    let alive = true;
    setError(null);
    void accountWatchlist.load(initial ?? undefined).then((value) => { if (alive) setList(value); }).catch(() => { if (alive) setError("Your watchlist could not be loaded. Please try again."); });
    return () => { alive = false; };
  }, [signedIn, initial, retry]);
  const unfollow = async (c: Remembered) => {
    if (!signedIn) {
      watchlist.toggle(c);
      setList(watchlist.list());
      return;
    }
    setRemoving(c.cik); setError(null);
    try { setList(await accountWatchlist.remove(c.cik)); }
    catch { setError("The company could not be removed. Your watchlist has not been changed."); }
    finally { setRemoving(null); }
  };
  useEffect(() => {
    if (!list) return;
    if (!list.length) {
      setFilings([]);
      return;
    }
    setFilings(null); setFilingError(false);
    const controller = new AbortController();
    fetch(`/api/recent?ciks=${list.map((c) => c.cik).join(",")}&days=${days}`, { signal: controller.signal })
      .then((r) => { if (!r.ok) throw new Error("Unavailable"); return r.json(); })
      .then((d: { filings: RecentFiling[] }) => { if (!controller.signal.aborted) setFilings(d.filings ?? []); })
      .catch(() => { if (!controller.signal.aborted) setFilingError(true); });
    return () => controller.abort();
  }, [list, days, retry]);

  if (list === null) return error ? <div className="notice" role="alert">{error} <button className="linkbtn" onClick={() => setRetry((n) => n + 1)}>Try again</button></div> : <p className="muted" role="status">Loading your watchlist…</p>;
  const results = (filings ?? []).filter((f) => f.is_results);
  const rest = (filings ?? []).filter((f) => !f.is_results);
  return (
    <>
      {!list.length && <div className="empty"><h2>A place for your companies.</h2><p>Follow a company to collect its latest results and filings here.</p><p className="muted">{signedIn ? "Your watchlist is saved to your account." : "Sign in to keep your list across devices, or get started in this browser."}</p><Link href="/" className="btn">Find a company</Link></div>}
      {error && <p className="notice" role="alert">{error}</p>}
      <p className="eyebrow watchlist-count">{list.length} compan{list.length === 1 ? "y" : "ies"} followed{signedIn ? " · Saved to your account" : " · Saved in this browser"}</p>
      <p className="chips">
        {list.map((c) => (
          <span key={c.cik} className="chip link">
            <Link href={`/companies/${c.cik}`}>{c.ticker ?? c.name}</Link>
            <button type="button" className="x" disabled={removing !== null} aria-label={`Stop following ${c.name}`} onClick={() => void unfollow(c)}>×</button>
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
      {filingError ? <div className="notice" role="alert">Recent filings could not be loaded. <button className="linkbtn" onClick={() => setRetry((n) => n + 1)}>Try again</button></div> : filings === null ? (
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
      <OwnershipMorning companies={list} days={days}/>
      <section className="subscribe">
        <p className="eyebrow">Email filing alerts</p>
        {!signedIn ? <p className="muted"><Link href="/signin">Sign in</Link> to send filing alerts to your verified account email.</p> : <>
          <p className="muted">{subscribed ? "Email alerts are enabled." : "Receive results filings at your verified account email."} Following changes your watchlist; use “Update alert companies” to apply the current list to email alerts.</p>
          <fieldset disabled={sub === "loading" || sub === "sending"} style={{border:"1px solid var(--line)",padding:"16px",margin:"18px 0"}}><legend>Optional ownership alerts</legend><p className="muted small">Select each disclosure type explicitly. Results filing alerts remain included; ownership groups are kept separate in the digest.</p>{OWNERSHIP_FLOWS.map(flow => <label key={flow} style={{display:"flex",alignItems:"center",gap:10,margin:"10px 0",fontSize:14}}><input type="checkbox" checked={ownershipFlows.includes(flow)} onChange={event => {setOwnershipFlows(previous => event.target.checked ? [...previous,flow] : previous.filter(item => item !== flow));setAlertMessage("Ownership alert choices changed. Enable or update alerts to save them.");}}/>{FLOW_COPY[flow].title}</label>)}</fieldset>
          {sub === "loading" ? <p role="status" className="muted">Loading alert settings…</p> : <div className="row">
            <button className="btn" type="button" disabled={sub === "sending" || !list.length} onClick={() => void saveAlerts(true)}>{sub === "sending" ? "Saving…" : subscribed ? "Update alert companies" : "Enable email alerts"}</button>
            {(subscribed || sub === "error") && <button className="btn secondary" type="button" disabled={sub === "sending"} onClick={() => void saveAlerts(false)}>Pause alerts</button>}
          </div>}
          {subscribed && <p className="muted small">Alerts currently include {subscribedCiks.length} compan{subscribedCiks.length === 1 ? "y" : "ies"}.</p>}
          {alertMessage && <p className="muted" role="status">{alertMessage}</p>}
          {sub === "off" && <p className="notice" role="status">Email alerts are not available on this deployment yet.</p>}
          {sub === "error" && <p className="err" role="alert">Alert settings could not be loaded or saved. Please try again.</p>}
        </>}
      </section>
    </>
  );
}

function Table({ rows }: { rows: RecentFiling[] }) {
  return (
    <div className="table-scroll"><table>
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
    </table></div>
  );
}
