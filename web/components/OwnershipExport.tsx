"use client";
import { useState } from "react";
import type { OwnershipFlow } from "@/lib/ownership";
import styles from "./Ownership.module.css";
export default function OwnershipExport({ cik, flow, query }: { cik: string; flow: OwnershipFlow; query: string }) {
  const [busy,setBusy] = useState(false), [error,setError] = useState<string | null>(null);
  return <div className={styles.export}><button type="button" className="btn secondary" disabled={busy} onClick={async () => {
    setBusy(true);setError(null);
    try { const response = await fetch(`/api/ownership/${cik}/${flow}/export?${query}`,{cache:"no-store"});if(!response.ok){const body = await response.json().catch(()=>null);throw new Error(body?.error || "The export could not be generated. Try again.");}const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement("a");link.href=url;link.download=`disclosure-${cik}-${flow}.csv`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000); }
    catch(cause){setError(cause instanceof Error ? cause.message : "The export could not be downloaded.");}finally{setBusy(false);}
  }}>{busy ? "Preparing CSV…" : `Export ${flow === "events" ? "disclosures" : flow} CSV ↓`}</button>{error && <p className={styles.exportError} role="alert">{error}</p>}</div>;
}
