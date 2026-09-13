"use client";
import { useRef, useState } from "react";
import Link from "next/link";
import { launchRegions, type LaunchRegion } from "@/lib/launch-types";
import styles from "./Marketing.module.css";

export default function DemoRequestForm({ contact = false }: { contact?: boolean }) {
  const [form, setForm] = useState({ name:"", email:"", organisation:"", region:"ROW" as LaunchRegion, workflow:"" });
  const [busy,setBusy] = useState(false), [error,setError] = useState(""), [reference,setReference] = useState("");
  const requestId = useRef<string | null>(null);
  function update(key: keyof typeof form, value: string) { setForm(current=>({...current,[key]:value})); requestId.current=null; }
  async function submit(event: React.FormEvent) {
    event.preventDefault(); if(busy)return; setError("");
    if (!form.name.trim() || form.workflow.trim().length < 10) { setError("Please enter your name and a message of at least 10 characters."); return; }
    setBusy(true);
    requestId.current ||= crypto.randomUUID();
    try {
      const response = await fetch("/api/demo-requests",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...form,request_id:requestId.current})});
      const data = await response.json();
      if(!response.ok || data.received!==true || typeof data.reference!=="string")throw new Error(data.error || "We could not confirm receipt. Please try again.");
      setReference(data.reference);
    } catch(failure) { setError(failure instanceof Error ? failure.message : "Your request could not be confirmed. Please try again."); }
    finally {setBusy(false);}
  }
  if(reference)return <div className={styles.success} role="status"><p className="eyebrow">Request received</p><h2>{contact?"Your message is with us.":"Let’s make it relevant to you."}</h2><p>We received your {contact?"message":"demo request"}. We’ll use <strong>{form.email}</strong> to follow up. {contact?"":"A meeting has not been booked yet."}</p><p className={styles.note}>Reference: {reference}</p><Link href="/platform" className="text-link">Explore the platform →</Link></div>;
  return <form className={styles.form} onSubmit={submit} aria-label={contact?"Contact Disclosure":"Request a demo"}>
    <label>Full name<input name="name" autoComplete="name" required maxLength={120} value={form.name} disabled={busy} onChange={e=>update("name",e.target.value)}/></label>
    <label>Email address<input name="email" type="email" autoComplete="email" required maxLength={254} value={form.email} disabled={busy} onChange={e=>update("email",e.target.value)}/></label>
    <div className={styles.two}><label><span>Organisation <span className={styles.note}>(optional)</span></span><input name="organisation" autoComplete="organization" maxLength={160} value={form.organisation} disabled={busy} onChange={e=>update("organisation",e.target.value)}/></label><label>Region<select name="region" value={form.region} disabled={busy} onChange={e=>update("region",e.target.value)}>{launchRegions.map(region=><option key={region.value} value={region.value}>{region.label}</option>)}</select></label></div>
    <label>{contact?"What would you like to discuss?":"What would you like to explore?"}<textarea name="workflow" required minLength={10} maxLength={3000} rows={5} placeholder={contact?"Tell us how we can help.":"For example: comparing quarterly statements, following ownership changes, or researching a company with your team."} value={form.workflow} disabled={busy} onChange={e=>update("workflow",e.target.value)}/></label>
    <p className={styles.note}>We use these details to respond to your enquiry. This form does not subscribe you to marketing or reserve a founding-member place. <Link href="/privacy">How we handle your information</Link>.</p>
    {error&&<p className={styles.error} role="alert">{error} Your entered details are still here.</p>}
    <button className="btn" disabled={busy} type="submit">{busy?"Sending…":contact?"Send message":"Request a demo"}</button>
  </form>;
}
