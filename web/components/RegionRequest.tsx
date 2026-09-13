"use client";

import { useState } from "react";

// Explain available coverage and collect interest without promising unbuilt regions.
export default function RegionRequest() {
  const [region, setRegion] = useState<"US" | "UK" | "Europe" | "Rest of world">("US");
  const [note, setNote] = useState("");
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "done" | "error">("idle");
  const regions = ["US", "UK", "Europe", "Rest of world"] as const;
  return (
    <div className="regions">
      <div className="tabs small" role="tablist">
        {regions.map((r) => (
          <button key={r} role="tab" aria-selected={region === r} className={region === r ? "active" : ""} onClick={() => setRegion(r)}>
            {r}
            {r !== "US" && <span className="soon">request</span>}
          </button>
        ))}
      </div>
      {region !== "US" && (
        <form
          className="request"
          onSubmit={async (e) => {
            e.preventDefault();
            setState("sending");
            const r = await fetch("/api/request", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ region, note, email }) });
            setState(r.ok ? "done" : "error");
          }}
        >
          {state === "done" ? (
            <p className="muted">Thanks. Your interest in {region} coverage has been recorded.</p>
          ) : (
            <>
              <p className="muted">Interested in {region} filings? Tell us which companies you need. This helps us plan future coverage.</p>
              <div className="row">
                <input value={note} onChange={(e) => setNote(e.target.value)} aria-label="Companies or tickers requested" placeholder="Companies, tickers, or what you look at" required />
                <input value={email} onChange={(e) => setEmail(e.target.value)} aria-label="Email for coverage updates (optional)" placeholder="Email (optional)" type="email" />
                <button className="btn" type="submit" disabled={state === "sending"}>
                  Send
                </button>
              </div>
              {state === "error" && <p className="muted">Your request could not be sent. Please try again.</p>}
            </>
          )}
        </form>
      )}
    </div>
  );
}
