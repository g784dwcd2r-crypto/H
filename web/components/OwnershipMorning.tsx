"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { FLOW_COPY, OWNERSHIP_FLOWS, type OwnershipFeed, type OwnershipFlow } from "@/lib/ownership";
import type { Remembered } from "@/lib/local";
import OwnershipCard from "./OwnershipCard";
import OwnershipCoverage from "./OwnershipCoverage";
import styles from "./Ownership.module.css";
type Result = {data: OwnershipFeed | null; error: string | null};
export default function OwnershipMorning({ companies, days }: { companies: Remembered[]; days: number }) {
  const [results,setResults] = useState<Partial<Record<OwnershipFlow,Result>>>({}), [retry,setRetry] = useState(0);
  const ciks=companies.map(company=>company.cik).sort((a,b)=>a-b).join(",");
  useEffect(()=>{
    setResults({});if(!ciks)return;const controller = new AbortController(),since=new Date();since.setUTCDate(since.getUTCDate()-days);
    for(const flow of OWNERSHIP_FLOWS) void fetch(`/api/ownership/recent?${new URLSearchParams({ciks,flow,since:since.toISOString().slice(0,10),limit:"50"})}`,{signal:controller.signal,cache:"no-store"}).then(async response=>{const body=await response.json();if(!response.ok)throw new Error(body.error || "Ownership activity could not be loaded.");if(!controller.signal.aborted)setResults(previous=>({...previous,[flow]:{data:body,error:null}}));}).catch(cause=>{if(!controller.signal.aborted)setResults(previous=>({...previous,[flow]:{data:null,error:cause instanceof Error?cause.message:"Ownership activity unavailable."}}));});
    return()=>controller.abort();
  },[ciks,days,retry]);
  if(!companies.length)return null;
  return <section className={styles.morning} aria-labelledby="ownership-morning-title"><div className={styles.flowHeading}><div><p className="eyebrow">Ownership morning view</p><h2 id="ownership-morning-title">Recently reported, separately.</h2><p>Disclosures filed in your selected window. A filing date does not identify the trading date.</p></div><button type="button" className="linkbtn" onClick={()=>setRetry(value=>value+1)}>Refresh ownership</button></div>{OWNERSHIP_FLOWS.map(flow=>{const result=results[flow];return <section className={styles.morningFlow} key={flow} aria-label={`Recent ${FLOW_COPY[flow].title.toLowerCase()}`}><h3>{FLOW_COPY[flow].title}</h3><p className={styles.note}>{FLOW_COPY[flow].description}</p>{!result ? <p role="status">Loading {FLOW_COPY[flow].title.toLowerCase()}…</p> : result.error ? <p role="alert" className={styles.unavailable}>{result.error} Coverage is unknown; this is not a zero result.</p> : result.data && <><OwnershipCoverage coverage={result.data.coverage} compact/>{result.data.items.length ? <div className={styles.cards}>{result.data.items.map(card=>{const company=companies.find(item=>item.cik===card.issuer_cik);if(!company)return null;return <div key={`${card.issuer_cik}:${card.id}`}><p className={styles.feedCompany}><Link href={`/companies/${company.cik}/ownership#${flow}`}>{company.name}{company.ticker?` · ${company.ticker}`:""} ↗</Link></p><OwnershipCard card={card} cik={company.cik} kind={flow} compact/></div>;})}</div> : <p className={styles.empty}>No parsed disclosures for these companies in this window. Coverage is partial.</p>}<p className={styles.note}>Up to 50 cards per disclosure type. Open a company’s ownership page for the full filtered view.</p></>}</section>;})}</section>;
}
