"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import styles from "./AdminConsole.module.css";

type Session = { username: string; csrf: string; must_change_password: boolean; expires_at: string; mfa: string };
type Data = Record<string, any>;
type View = "overview" | "users" | "organizations" | "research" | "jobs" | "sources" | "configuration" | "audit" | "security";
type Review = { path: string; action: string; target: string; label: string; summary: string; values: Data };
const views: [View, string][] = [["overview", "Overview"], ["users", "Accounts"], ["organizations", "Organizations"], ["research", "Research index"], ["jobs", "Research jobs"], ["sources", "Source readiness"], ["configuration", "Configuration"], ["audit", "Audit history"], ["security", "Operator security"]];
const labels = Object.fromEntries(views);
function date(value: unknown) { return typeof value === "string" && value ? new Date(value).toLocaleString() : "Not observed"; }
function label(value: unknown) { return String(value ?? "Unavailable").replaceAll("_", " "); }

async function call(path: string, csrf?: string, body?: Data): Promise<Data> {
  const response = await fetch(`/api/platform-admin/${path}`, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json", "X-Admin-CSRF": csrf || "" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const data = await response.json();
  if (!response.ok) throw Object.assign(new Error(data.error || "The request failed."), { status: response.status });
  return data;
}

function Badge({ value }: { value: unknown }) {
  const state = String(value ?? "unknown");
  const good = ["active", "available", "completed", "indexed", "implemented"].includes(state);
  return <span className={`${styles.badge} ${good ? styles.good : styles.caution}`}>{label(state)}</span>;
}

function Empty({ children }: { children: React.ReactNode }) { return <div className={styles.empty}>{children}</div>; }

export default function AdminConsole() {
  const [session, setSession] = useState<Session | null>(null);
  const [initializing, setInitializing] = useState(true);
  const [view, setView] = useState<View>("overview");
  const [data, setData] = useState<Data | null>(null);
  const [detail, setDetail] = useState<Data | null>(null);
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [username, setUsername] = useState("disclosure");
  const [password, setPassword] = useState("");
  const [replacement, setReplacement] = useState("");
  const [repeat, setRepeat] = useState("");
  const [review, setReview] = useState<Review | null>(null);
  const [reason, setReason] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [newMember, setNewMember] = useState("");
  const [newRole, setNewRole] = useState("member");
  const sequence = useRef(0);
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    call("session").then(result => setSession(result as Session)).catch(failure => { if (failure.status !== 401) setError(failure.message); }).finally(() => setInitializing(false));
  }, []);

  async function load(selected = view, query = search, start = offset) {
    if (selected === "security") { setData(null); return; }
    const id = ++sequence.current;
    setLoading(true);
    try {
      const result = await call(`${selected}?q=${encodeURIComponent(query)}&limit=25&offset=${start}`);
      if (id === sequence.current) { setData(result); setError(""); }
    } catch (failure) { if (id === sequence.current) setError((failure as Error).message); }
    finally { if (id === sequence.current) setLoading(false); }
  }

  useEffect(() => { if (session && !session.must_change_password) void load(); }, [session?.username, session?.must_change_password, view, search, offset]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (review && dialog.current && !dialog.current.open) dialog.current.showModal(); }, [review]);

  async function authenticate(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      if (session) {
        if (replacement !== repeat) throw new Error("The replacement passwords do not match.");
        const result = await call("password", session.csrf, { current_password: password, new_password: replacement });
        setSession(result as Session); setReplacement(""); setRepeat(""); setNotice("Password changed. Earlier administrator sessions were revoked.");
        setView("overview");
      } else {
        const result = await call("login", undefined, { username, password });
        setView("overview"); setOffset(0); setSearch(""); setQ(""); setSession(result as Session); setNotice("");
      }
    } catch (failure) { setError((failure as Error).message); }
    finally { setPassword(""); setBusy(false); }
  }

  async function logout() {
    if (!session) return;
    setBusy(true); setError("");
    try { await call("logout", session.csrf, {}); setSession(null); setData(null); setDetail(null); setNotice("Administrator session revoked. You are signed out."); }
    catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }

  function navigate(next: View) {
    ++sequence.current; setView(next); setData(null); setDetail(null); setSearch(""); setQ(""); setOffset(0); setError(""); setNotice("");
  }

  async function inspect(kind: "users" | "organizations", id: string) {
    setBusy(true); setError("");
    try { setDetail(await call(`${kind}/${id}`)); }
    catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }

  function prepare(change: Review) { setReview(change); setReason(""); setReviewed(false); setPassword(""); setError(""); }

  async function apply(event: React.FormEvent) {
    event.preventDefault();
    if (!review || !session || !reviewed) return;
    setBusy(true); setError("");
    try {
      const renewed = await call("reauthenticate", session.csrf, { password });
      setSession(renewed as Session); setPassword("");
      await call(review.path, renewed.csrf, { ...review.values, reason, confirmation: `${review.action}:${review.target}` });
      setReview(null); setNotice(`${review.label} completed and recorded in audit history.`);
      await load();
      if (detail?.user) await inspect("users", detail.user.id);
      if (detail?.organization) await inspect("organizations", detail.organization.id);
    } catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); setPassword(""); }
  }

  function changeMember(member: Data, role: string | null) {
    const org = detail?.organization.id;
    prepare({ path: `organizations/${org}/members/${member.user_id}`, action: "membership.change", target: `${org}:${member.user_id}`,
      label: role ? "Change organization role" : "Remove organization membership", summary: `${member.email || member.user_id}: ${member.role || "No membership"} → ${role || "No access"} in ${detail?.organization.name}.`, values: { role, expected_version: member.version || "absent" } });
  }

  const loginOrChange = !session || session.must_change_password;
  const page = view === "research" ? data?.failures : data;
  const tableItems: Data[] = page?.items || [];
  return <div className={styles.console}>
    <header className={styles.top}><Link href="/" className={styles.brand}><span>Disclosure</span></Link><span className={styles.environment}>Platform administration</span>{session && <button onClick={logout} disabled={busy}>Sign out operator</button>}</header>
    {initializing ? <div className={styles.auth}><p role="status">Checking administrator session…</p></div> : loginOrChange ? <section className={styles.auth}>
      <p className={styles.eyebrow}>Separate operator access</p><h1>{session ? "Choose your own password." : "Manage the platform."}</h1>
      <p>{session ? "Your initial credential cannot open management controls. Choose a unique passphrase to finish setup." : "Accounts, source health and privileged changes in one operational workspace."}</p>
      {error && <p className={styles.error} role="alert">{error}</p>}{notice && <p role="status" className={styles.notice}>{notice}</p>}
      <form onSubmit={authenticate} className={styles.form}>
        {!session && <label>Administrator username<input autoComplete="username" value={username} onChange={event => setUsername(event.target.value)} required /></label>}
        <label>{session ? "Initial or current password" : "Administrator password"}<input type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required /></label>
        {session && <><label>New password<input type="password" autoComplete="new-password" minLength={16} maxLength={256} value={replacement} onChange={event => setReplacement(event.target.value)} required /></label><label>Repeat new password<input type="password" autoComplete="new-password" value={repeat} onChange={event => setRepeat(event.target.value)} required /></label><small>16–256 characters with at least 8 distinct characters. Use a password manager or a unique passphrase.</small></>}
        <button className={styles.primary} disabled={busy}>{busy ? "Checking…" : session ? "Change password and continue" : "Sign in to administration"}</button>
      </form><p className={styles.muted}>A team owner or ordinary Disclosure account does not grant this access.</p>
    </section> : <div className={styles.workspace}>
      <aside className={styles.sidebar}><p className={styles.eyebrow}>Control plane</p><nav aria-label="Administration sections">{views.map(([key, title]) => <button key={key} className={view === key ? styles.selected : ""} aria-current={view === key ? "page" : undefined} onClick={() => navigate(key)}>{title}</button>)}</nav><div className={styles.operator}><strong>{session.username}</strong><span>Platform superadmin</span><small>Expires {date(session.expires_at)}</small></div></aside>
      <section className={styles.content}>
        <div className={styles.heading}><div><p className={styles.eyebrow}>Operational workspace</p><h1>{labels[view]}</h1></div>{view !== "security" && <button onClick={() => void load()} disabled={loading || busy}>Refresh</button>}</div>
        {error && <p role="alert" className={styles.error}>{error} {data && "The displayed data may be stale."}</p>}{notice && <p role="status" className={styles.notice}>{notice}</p>}
        {loading && <p role="status" className={styles.loading}>Reading current platform state…</p>}
        {["users", "organizations", "research", "jobs", "audit"].includes(view) && <form className={styles.search} onSubmit={event => { event.preventDefault(); setSearch(q); setOffset(0); if (q === search && offset === 0) void load(); }}><label className={styles.srOnly} htmlFor="admin-search">Search {labels[view]}</label><input id="admin-search" value={q} maxLength={150} placeholder={`Search ${labels[view].toLowerCase()}…`} onChange={event => setQ(event.target.value)} /><button>Search</button></form>}
        {view === "overview" && data && <>
          <div className={styles.metrics}><article><span>Accounts</span><strong>{data.users}</strong><button onClick={() => navigate("users")}>Manage accounts →</button></article><article><span>Organizations</span><strong>{data.organizations}</strong><button onClick={() => navigate("organizations")}>Review access →</button></article><article><span>Indexed documents</span><strong>{data.research?.coverage?.indexed ?? "—"}</strong><Badge value={data.research?.coverage?.partial ? "partial" : data.research?.state} /></article></div>
          <div className={styles.twoColumns}><article className={styles.card}><h2>Serving data</h2><Badge value={data.publication?.state} /><p>Backend: {label(data.backend)}</p><p>Last publication: {date(data.publication?.publication?.published_at)}</p><small>Observed {date(data.observed_at)}</small></article><article className={styles.card}><h2>Research freshness</h2><Badge value={data.research?.freshness || data.research?.state} /><p>Last discovery: {date(data.research?.coverage?.last_discovery_at)}</p><p>{data.research?.freshness_note || data.research?.reason}</p></article></div>
          <article className={styles.card}><h2>Recent ingestion runs</h2>{data.recent_ingest_runs?.length ? <div className={styles.tableScroll}><table><thead><tr><th>Run</th><th>Status</th><th>Started</th><th>Finished</th></tr></thead><tbody>{data.recent_ingest_runs.map((row: Data) => <tr key={row.run_id}><td>{row.run_id}</td><td><Badge value={row.status} /></td><td>{date(row.started_at)}</td><td>{date(row.finished_at)}</td></tr>)}</tbody></table></div> : <Empty>No ingestion run was observed in this serving database.</Empty>}</article><p className={styles.muted}>{data.assurance}</p>
        </>}
        {(view === "users" || view === "organizations") && data && <>
          <div className={styles.tableScroll}><table><thead><tr>{(view === "users" ? ["Account", "Company", "Status", "Created"] : ["Organization", "Identifier", "Created"]).map(title => <th key={title}>{title}</th>)}</tr></thead><tbody>{tableItems.map(row => <tr key={row.id}>{view === "users" ? <><td><button className={styles.textButton} disabled={busy} onClick={() => inspect("users", row.id)}>{row.email}</button><small>{row.first_name} {row.last_name}</small></td><td>{row.company || "—"}</td><td><Badge value={row.status} /></td><td>{date(row.created_at)}</td></> : <><td><button className={styles.textButton} disabled={busy} onClick={() => inspect("organizations", row.id)}>{row.name}</button></td><td className={styles.code}>{row.id}</td><td>{date(row.created_at)}</td></>}</tr>)}</tbody></table></div>{tableItems.length === 0 && <Empty>No matching {view === "users" ? "accounts" : "organizations"}.</Empty>}
        </>}
        {detail?.user && view === "users" && <article className={styles.detail} aria-label="Account details"><div className={styles.heading}><h2>{detail.user.email}</h2><button onClick={() => setDetail(null)}>Close details</button></div><p className={styles.code}>{detail.user.id}</p><div className={styles.actions}><Badge value={detail.user.status} /><button disabled={busy} onClick={() => prepare({ path: `users/${detail.user.id}/status`, action: "account.status", target: detail.user.id, label: detail.user.status === "active" ? "Suspend account" : "Resume account", summary: `${detail.user.email}: ${detail.user.status} → ${detail.user.status === "active" ? "suspended" : "active"}. Suspension revokes current sessions and blocks new sign-ins.`, values: { status: detail.user.status === "active" ? "suspended" : "active", expected_revision: detail.user.revision } })}>{detail.user.status === "active" ? "Review suspension" : "Review account restoration"}</button><button disabled={busy || !detail.sessions.length} onClick={() => prepare({ path: `users/${detail.user.id}/revoke-sessions`, action: "sessions.revoke", target: detail.user.id, label: "Revoke account sessions", summary: `Sign out all ${detail.sessions.length} active sessions for ${detail.user.email}.`, values: { expected_revision: detail.user.revision } })}>Review session revocation</button></div><h3>Active sessions · {detail.sessions.length}</h3>{detail.sessions.length ? <ul className={styles.records}>{detail.sessions.map((row: Data) => <li key={row.id}><strong>{row.device_label || "Unknown device"}</strong><span>Last seen {date(row.last_seen_at)} · expires {date(row.expires_at)}</span></li>)}</ul> : <p>No active sessions.</p>}<h3>Organization memberships · {detail.memberships.length}</h3><ul className={styles.records}>{detail.memberships.map((row: Data) => <li key={row.id}><span className={styles.code}>{row.organization_id}</span><Badge value={row.role} /></li>)}</ul><p className={styles.muted}>{detail.note}</p></article>}
        {detail?.organization && view === "organizations" && <article className={styles.detail} aria-label="Organization details"><div className={styles.heading}><h2>{detail.organization.name}</h2><button onClick={() => setDetail(null)}>Close details</button></div><p>{detail.note}</p><div className={styles.tableScroll}><table><thead><tr><th>Member</th><th>Role</th><th>Review change</th></tr></thead><tbody>{detail.members.map((row: Data) => <tr key={row.id}><td>{row.email || row.user_id}</td><td><Badge value={row.role} /></td><td><select aria-label={`Change role for ${row.email || row.user_id}`} value="" disabled={busy} onChange={event => { if (event.target.value) changeMember(row, event.target.value === "remove" ? null : event.target.value); }}><option value="">Choose action…</option>{["member", "admin", "owner"].filter(role => role !== row.role).map(role => <option key={role} value={role}>Make {role}</option>)}<option value="remove">Remove membership</option></select></td></tr>)}</tbody></table></div><form className={styles.addMember} onSubmit={event => { event.preventDefault(); changeMember({ user_id: newMember, version: "absent" }, newRole); }}><label>Existing account ID<input pattern="[a-z0-9]{32}" value={newMember} onChange={event => setNewMember(event.target.value)} required /></label><label>Initial role<select value={newRole} onChange={event => setNewRole(event.target.value)}>{["member", "admin", "owner"].map(role => <option key={role}>{role}</option>)}</select></label><button>Review adding member</button></form></article>}
        {view === "research" && data && (data.state !== "available" ? <Empty>{data.reason}</Empty> : <><div className={styles.metrics}><article><span>Indexed / registered</span><strong>{data.coverage.indexed} / {data.coverage.total}</strong></article><article><span>Failed or unsupported</span><strong>{data.coverage.failed + data.coverage.unsupported}</strong></article><article><span>Incomplete inventories</span><strong>{data.coverage.inventories_failed + data.coverage.inventories_pending}</strong></article></div><p><Badge value={data.coverage.partial ? "partial" : "complete_registered_inventory"} /> {data.coverage.scope}</p><p className={styles.muted}>{data.freshness_note} Last discovery: {date(data.coverage.last_discovery_at)}</p><div className={styles.tableScroll}><table><thead><tr><th>Document</th><th>Status</th><th>Explanation</th><th>Last attempt</th></tr></thead><tbody>{tableItems.map(row => <tr key={row.document_id}><td>{row.filename}<small>{row.accession}</small></td><td><Badge value={row.status} /></td><td>{row.error || "Waiting for extraction"}</td><td>{date(row.attempted_at)}</td></tr>)}</tbody></table></div>{tableItems.length === 0 && <Empty>No matching extraction failures or pending documents in the registered index.</Empty>}<article className={styles.card}><h2>Incomplete filing inventories</h2><p>Showing at most {data.inventory_list_limit} inventories. Coverage counts above include the full registered inventory.</p><ul className={styles.records}>{data.incomplete_inventories.map((row: Data) => <li key={`${row.cik}:${row.accession}`}><span>{row.cik} · {row.accession}</span><Badge value={row.inventory_status} /><span>{row.inventory_error}</span></li>)}</ul>{!data.incomplete_inventories.length && <p>No incomplete inventory is currently recorded.</p>}</article></>)}
        {view === "jobs" && data && data.unresolved_commands?.length > 0 && <article className={styles.card}><h2>Commands requiring reconciliation</h2><p>A request was recorded but its result was not confirmed. Inspect the current job revision before deciding what to do; do not replay it blindly.</p><ul className={styles.records}>{data.unresolved_commands.map((command: Data) => <li key={command.id}><span>{command.action} · {command.job_id}</span><Badge value={command.status} /><span>Expected revision {command.expected_revision} · {date(command.created_at)}</span></li>)}</ul></article>}
        {view === "jobs" && data && (data.state === "unavailable" ? <Empty><h2>Job controls unavailable</h2><p>{data.reason}</p><p>No production scheduler has been activated by this console.</p></Empty> : <article className={styles.card}><h2>Durable research jobs</h2><p>Scheduling state: {data.health?.scheduler_active ? "active" : "not activated"}</p><div className={styles.tableScroll}><table><thead><tr><th>Job / scope</th><th>Status</th><th>Progress</th><th>Actions</th></tr></thead><tbody>{(data.jobs || []).map((job: Data) => <tr key={job.id}><td>{job.kind}<small>{job.cik || "All registered companies"} · {job.id}</small></td><td><Badge value={job.status} /><small>{job.error}</small></td><td>{job.batches_completed} / {job.max_batches} batches</td><td>{["retry", "cancel"].filter(action => action === "retry" ? ["paused", "quarantined", "retry_wait", "cancelled"].includes(job.status) : !["completed", "cancelled"].includes(job.status)).map(action => <button key={action} onClick={() => prepare({ path: `jobs/${job.id}/${action}`, action: `job.${action}`, target: job.id, label: `${action === "retry" ? "Retry" : "Cancel"} research job`, summary: `${job.kind} job ${job.id}, currently ${job.status}. Fetch setting: ${job.fetch ? "enabled" : "cached bytes only"}.`, values: { expected_revision: job.revision } })}>Review {action}</button>)}</td></tr>)}</tbody></table></div></article>)}
        {view === "sources" && data && <><p className={styles.muted}>{data.note}</p><div className={styles.sources}>{data.sources.map((source: Data) => <article className={styles.card} key={source.source_id}><div className={styles.heading}><h2>{source.name}</h2><Badge value={source.status} /></div><p>{source.coverage_basis}</p><small>{source.rights_note}</small><p className={styles.code}>{source.source_id}</p></article>)}</div></>}
        {view === "configuration" && data && <><article className={styles.card}><h2>New account registration</h2><p>These controls are checked when a new account is created through email or Google sign-in. Existing users retain access unless separately suspended.</p>{["new_registration_enabled", "business_email_only"].map(key => <div key={key} className={styles.setting}><div><strong>{key === "new_registration_enabled" ? "Allow new accounts" : "Require a business email"}</strong><p>Currently {data.configuration[key] ? "enabled" : "disabled"}</p></div><button onClick={() => prepare({ path: "configuration", action: "configuration.change", target: "registration", label: "Update registration configuration", summary: `${key === "new_registration_enabled" ? "Allow new accounts" : "Require a business email"}: ${data.configuration[key] ? "enabled → disabled" : "disabled → enabled"}.`, values: { [key]: !data.configuration[key], expected_revision: data.configuration.revision } })}>Review change</button></div>)}</article><article className={styles.card}><h2>Deployment configuration</h2><dl className={styles.facts}><dt>Environment</dt><dd>{data.deployment.environment}</dd><dt>Admin session duration</dt><dd>{data.deployment.admin_session_minutes} minutes</dd><dt>Email provider</dt><dd>{data.deployment.mail_configured ? "Configuration present; delivery not certified" : "Not configured"}</dd><dt>Google sign-in</dt><dd>{data.deployment.google_configured ? "Configuration present; live sign-in not certified" : "Not configured"}</dd><dt>Administrator MFA</dt><dd>Not configured</dd></dl><p className={styles.muted}>Deployment secrets and provider rights are managed outside this console.</p></article></>}
        {view === "audit" && data && <><p className={styles.muted}>Privileged changes, authentication and recovery events. Passwords, session tokens and private research are excluded.</p><div className={styles.tableScroll}><table><thead><tr><th>When / operator</th><th>Action</th><th>Target</th><th>Recorded change</th></tr></thead><tbody>{tableItems.map(row => <tr key={row.id}><td>{date(row.at)}<small>{row.actor_id}</small></td><td>{row.action}</td><td className={styles.code}>{row.target_id}</td><td><details><summary>{row.metadata.reason || "Security event"}</summary><pre>{JSON.stringify(row.metadata, null, 2)}</pre></details></td></tr>)}</tbody></table></div>{tableItems.length === 0 && <Empty>No matching audit events.</Empty>}</>}
        {view === "security" && <article className={styles.card}><h2>Change operator password</h2><p>Changing it revokes all earlier administrator sessions. Ordinary user sessions are separate.</p><form className={styles.form} onSubmit={authenticate}><label>Current password<input type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required /></label><label>New password<input type="password" autoComplete="new-password" minLength={16} value={replacement} onChange={event => setReplacement(event.target.value)} required /></label><label>Repeat new password<input type="password" autoComplete="new-password" value={repeat} onChange={event => setRepeat(event.target.value)} required /></label><button disabled={busy}>Change operator password</button></form><p className={styles.muted}>MFA is not configured. Recovery requires the documented server-side operator procedure; this is not an enterprise SSO or independent security-assurance claim.</p></article>}
        {["users", "organizations", "research", "audit", "jobs"].includes(view) && typeof page?.total === "number" && <div className={styles.pagination}><span>{page.total ? `${offset + 1}–${Math.min(offset + 25, page.total)} of ${page.total}` : "0 results"}</span><button disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous</button><button disabled={offset + 25 >= page.total || loading} onClick={() => setOffset(offset + 25)}>Next</button></div>}
      </section>
    </div>}
    {review && <dialog ref={dialog} className={styles.dialog} aria-labelledby="admin-review-title" onCancel={event => { event.preventDefault(); if (!busy) setReview(null); }}><form onSubmit={apply}><p className={styles.eyebrow}>Review privileged change</p><h2 id="admin-review-title">{review.label}</h2><p>{review.summary}</p><p className={styles.code}>{review.target}</p>{error && <p role="alert" className={styles.error}>{error}</p>}<label>Operational reason<textarea minLength={8} maxLength={500} value={reason} onChange={event => setReason(event.target.value)} required /></label><label>Re-enter administrator password<input type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required /></label><label className={styles.checkbox}><input type="checkbox" checked={reviewed} onChange={event => setReviewed(event.target.checked)} required />I reviewed the account or organization and the exact change above.</label><div className={styles.actions}><button type="button" disabled={busy} onClick={() => setReview(null)}>Cancel</button><button className={styles.primary} disabled={busy || !reviewed}>{busy ? "Verifying and applying…" : "Confirm reviewed change"}</button></div><small>The API verifies permission, recent authentication and the saved revision, then records the outcome.</small></form></dialog>}
  </div>;
}
