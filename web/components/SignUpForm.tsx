"use client";

import { useState } from "react";

const ROLES: Record<string, string[]> = {
  "Hedge fund": ["Long/short equity analyst", "Event-driven analyst", "Credit analyst", "Portfolio manager", "Quant / data", "Other"],
  "Asset management": ["Equity analyst", "Credit analyst", "Portfolio manager", "Research associate", "Other"],
  "Investment bank": ["Equity research analyst", "Investment banking analyst", "Sales & trading", "Other"],
  "Private equity / venture": ["Deal team", "Portfolio operations", "Other"],
  Consultant: ["Accounting consultant", "Strategy consultant", "Valuation / transaction services", "Other"],
  Corporate: ["Corporate development", "Investor relations", "FP&A", "Finance / accounting", "Other"],
  "Family office / independent": ["Analyst", "Principal", "Other"],
  Other: ["Student", "Journalist", "Software", "Other"],
};
const COUNTRIES = [
  "United States", "United Kingdom", "Canada", "Ireland", "Germany", "France", "Netherlands", "Switzerland", "Spain", "Italy",
  "Sweden", "Denmark", "Norway", "Finland", "Belgium", "Luxembourg", "Austria", "Portugal", "Poland", "Israel",
  "United Arab Emirates", "Saudi Arabia", "India", "Singapore", "Hong Kong", "Japan", "South Korea", "Australia", "New Zealand",
  "Brazil", "Mexico", "South Africa", "Other",
];

export default function SignUpForm({ businessOnly, emailLink }: { businessOnly: boolean; emailLink: boolean }) {
  const [f, setF] = useState({
    email: "",
    first_name: "",
    last_name: "",
    company: "",
    phone: "",
    role: "Hedge fund",
    specialty: ROLES["Hedge fund"][0],
    title: "",
    country: "United States",
    marketing_opt_in: false,
  });
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error" | "off">("idle");
  const [error, setError] = useState<string | null>(null);
  const [devLink, setDevLink] = useState<string | null>(null);
  const set = (k: keyof typeof f, v: string | boolean) => setF((x) => ({ ...x, [k]: v }));

  if (!emailLink)
    return <p className="muted">Sign-up is not configured on this deployment yet (it needs an email relay). Your choices are still remembered in this browser.</p>;
  if (state === "sent")
    return (
      <div className="empty">
        <p>Check your email, {f.first_name}.</p>
        <p className="muted">A link to finish creating your account is on its way to {f.email}. It works for 15 minutes.</p>
        {devLink && (
          <p className="muted small">
            Development mode: <a href={devLink}>open the link</a>
          </p>
        )}
      </div>
    );
  return (
    <form
      className="signup"
      onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        setState("sending");
        const r = await fetch("/api/auth/signup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...f, accept_terms: true }) });
        const d = (await r.json().catch(() => ({}))) as { detail?: string; dev_link?: string };
        if (r.ok) {
          setDevLink(d.dev_link ?? null);
          setState("sent");
        } else {
          setError(d.detail ?? "That did not go through. Please try again.");
          setState(r.status === 503 ? "off" : "error");
        }
      }}
    >
      <label>
        <span>{businessOnly ? "Business email" : "Email"} *</span>
        <input type="email" value={f.email} onChange={(e) => set("email", e.target.value)} required autoFocus />
        {error?.toLowerCase().includes("email") && <em className="err">{error}</em>}
      </label>
      <div className="two">
        <label>
          <span>First name *</span>
          <input value={f.first_name} onChange={(e) => set("first_name", e.target.value)} required />
        </label>
        <label>
          <span>Last name *</span>
          <input value={f.last_name} onChange={(e) => set("last_name", e.target.value)} required />
        </label>
      </div>
      <label>
        <span>Company *</span>
        <input value={f.company} onChange={(e) => set("company", e.target.value)} required />
      </label>
      <label>
        <span>Phone *</span>
        <input type="tel" value={f.phone} onChange={(e) => set("phone", e.target.value)} required />
      </label>
      <div className="two">
        <label>
          <span>You are</span>
          <select
            value={f.role}
            onChange={(e) => {
              set("role", e.target.value);
              set("specialty", ROLES[e.target.value][0]);
            }}
          >
            {Object.keys(ROLES).map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Specifically</span>
          <select value={f.specialty} onChange={(e) => set("specialty", e.target.value)}>
            {ROLES[f.role].map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
      </div>
      <label>
        <span>Title *</span>
        <input value={f.title} onChange={(e) => set("title", e.target.value)} required />
      </label>
      <label>
        <span>Country</span>
        <select value={f.country} onChange={(e) => set("country", e.target.value)}>
          {COUNTRIES.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </label>
      <label className="check">
        <input type="checkbox" checked={f.marketing_opt_in} onChange={(e) => set("marketing_opt_in", e.target.checked)} />
        <span>I would like to receive updates from Disclosure on new features, coverage and other relevant news.</span>
      </label>
      <p className="muted small">By submitting this form you agree to Disclosure&apos;s Terms of Use and Privacy Policy. No password: we email you a link.</p>
      {error && !error.toLowerCase().includes("email") && <p className="err">{error}</p>}
      {state === "off" && <p className="muted">Sign-up is not switched on for this deployment yet.</p>}
      <button className="btn wide" type="submit" disabled={state === "sending"}>
        Get started for free
      </button>
    </form>
  );
}
