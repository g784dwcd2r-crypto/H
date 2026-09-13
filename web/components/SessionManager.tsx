"use client";
import { useState } from "react";
import Link from "next/link";
import type { AccountSession } from "@/lib/workspace-types";

function date(value: string) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? "Unavailable" : parsed.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC";
}

export default function SessionManager({ initial, initialError }: { initial: AccountSession[] | null; initialError?: string | null }) {
  const [sessions, setSessions] = useState(initial);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState(initialError ?? null);
  const [notice, setNotice] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [confirmOthers, setConfirmOthers] = useState(false);
  const load = async () => {
    setPending("load"); setError(null);
    try {
      const response = await fetch("/api/sessions", { cache: "no-store" });
      if (response.status === 401) { setExpired(true); throw new Error("Your session has expired. Sign in again to continue."); }
      if (!response.ok) throw new Error("Sessions could not be loaded. Please try again.");
      const data = await response.json();
      setSessions(data.sessions);
    } catch (e) { setError(e instanceof Error ? e.message : "Sessions could not be loaded."); }
    finally { setPending(null); }
  };
  const revoke = async (id?: string) => {
    setPending(id ?? "others"); setError(null); setNotice(null);
    try {
      const response = await fetch(id ? `/api/sessions?id=${encodeURIComponent(id)}` : "/api/sessions", { method: id ? "DELETE" : "POST" });
      if (response.status === 401) { setExpired(true); throw new Error("Your session has expired. Sign in again to continue."); }
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? "The session could not be revoked. Please try again.");
      if (data.current) { window.location.assign("/signin"); return; }
      setSessions(current => current?.filter(session => id ? session.id !== id : session.current) ?? null);
      setConfirmOthers(false);
      setNotice(id ? "Session signed out. Its access has been revoked." : `${data.revoked} other ${data.revoked === 1 ? "session" : "sessions"} signed out.`);
    } catch (e) { setError(e instanceof Error ? e.message : "The session could not be revoked."); }
    finally { setPending(null); }
  };
  const otherCount = sessions?.filter(session => !session.current).length ?? 0;
  return <div className="session-manager">
    <div className="section-heading"><div><h2>Active sessions</h2><p className="muted">Each sign-in is listed separately. Times are shown in UTC.</p></div><button className="btn secondary" onClick={() => void load()} disabled={!!pending}>Refresh</button></div>
    {error && <div className="notice" role="alert">{error}{expired && <> <Link href="/signin">Sign in again →</Link></>}</div>}
    {notice && <p className="saved session-notice" role="status">{notice}</p>}
    {sessions && sessions.length > 0 ? <ul className="session-list">{sessions.map(session => <li key={session.id}>
      <div className="device-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4"><rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/></svg></div>
      <div className="session-detail"><h3>{session.device_label || "Browser session"}{session.current && <span className="chip ok">This session</span>}</h3><dl><div><dt>Last active</dt><dd>{date(session.last_seen_at)}</dd></div><div><dt>Signed in</dt><dd>{date(session.created_at)}</dd></div><div><dt>Expires</dt><dd>{date(session.expires_at)}</dd></div></dl></div>
      <button type="button" className="btn secondary" disabled={!!pending || expired} onClick={() => void revoke(session.id)}>{pending === session.id ? "Signing out…" : session.current ? "Sign out this session" : "Sign out session"}</button>
    </li>)}</ul> : sessions && <div className="empty"><p>No active sessions were returned.</p><p>Refresh this list or sign in again.</p></div>}
    {otherCount > 0 && <div className="session-actions"><div><h3>Sign out everywhere else</h3><p>This session will stay signed in. Other browsers will need to sign in again.</p></div>{confirmOthers ? <div className="row"><button className="btn" disabled={!!pending} onClick={() => void revoke()}>{pending === "others" ? "Signing out…" : `Sign out ${otherCount} other ${otherCount === 1 ? "session" : "sessions"}`}</button><button className="linkbtn" disabled={!!pending} onClick={() => setConfirmOthers(false)}>Cancel</button></div> : <button className="btn secondary" disabled={!!pending || expired} onClick={() => setConfirmOthers(true)}>Sign out other sessions</button>}</div>}
    <p className="security-footnote">A session label describes the browser used to sign in. It does not verify a physical device or location. If you do not recognise a session, revoke it and secure the email or Google account you use to sign in.</p>
  </div>;
}
