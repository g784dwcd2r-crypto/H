"use client";

import { useState } from "react";

// US now; UK and Europe as a visible promise with a place to say which companies you need.
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
            {r !== "US" && <span className="soon">soon</span>}
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
            <p className="muted">Noted. {region} coverage is on the list, and the companies you named go first.</p>
          ) : (
            <>
              <p className="muted">{region} filings are coming. Tell us which companies you need and they go to the front of the queue.</p>
              <div className="row">
                <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Companies, tickers, or what you look at" required />
                <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email (optional)" type="email" />
                <button className="btn" type="submit" disabled={state === "sending"}>
                  Send
                </button>
              </div>
              {state === "error" && <p className="muted">That did not go through. Email us instead, and sorry.</p>}
            </>
          )}
        </form>
      )}
    </div>
  );
}
