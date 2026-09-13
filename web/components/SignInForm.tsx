"use client";

import { useState } from "react";
import { authHref } from "@/lib/auth-navigation";
import type { LoginRegion } from "@/lib/public-navigation";
import AuthRegionNotice from "./AuthRegionNotice";

export default function SignInForm({ emailLink, google, error, next = "/", region = null }: { emailLink: boolean; google: boolean; error?: string; next?: string; region?: LoginRegion | null }) {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "off" | "error">("idle");
  const [devLink, setDevLink] = useState<string | null>(null);
  return (
    <div className="signin">
      <AuthRegionNotice region={region} />
      {error === "link" && <p className="notice">That sign-in link is invalid or has expired. Ask for a new one.</p>}
      {error === "google" && <p className="notice">Google sign-in did not complete. Try again, or use your email.</p>}
      {state === "sent" ? (
        <div className="empty">
          <p>Check your email.</p>
          <p className="muted">A sign-in link is on its way to {email}. It works for 15 minutes.</p>
          {devLink && (
            <p className="muted small">
              Development mode: <a href={devLink}>open the link</a>
            </p>
          )}
        </div>
      ) : (
        <>
          {emailLink && (
            <form
              className="row"
              onSubmit={async (e) => {
                e.preventDefault();
                setState("sending");
                try {
                  const r = await fetch("/api/auth/magic-link", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, next, region }) });
                  const d = (await r.json().catch(() => ({}))) as { dev_link?: string };
                  if (r.ok) {
                    setDevLink(d.dev_link ?? null);
                    setState("sent");
                  } else setState(r.status === 503 ? "off" : "error");
                } catch { setState("error"); }
              }}
            >
              <input type="email" aria-label="Email address" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@fund.com" required autoFocus />
              <button className="btn" type="submit" disabled={state === "sending"}>
                Email me a link
              </button>
            </form>
          )}
          {state === "error" && <p className="muted" role="alert">That did not go through. Check your connection and email address, then try again.</p>}
          {state === "off" && <p className="muted" role="alert">Email sign-in is unavailable right now. Please try again later.</p>}
          {google && (
            <p className="alt">
              <a className="btn secondary" href={authHref("/auth/google", next, region)}>Continue with Google</a>
            </p>
          )}
          {!emailLink && !google && <p className="muted">Sign-in is not configured on this deployment. Your choices are still remembered in this browser.</p>}
          <p className="muted small">No password. A link by email, or Google. Your preferences follow your account.</p>
        </>
      )}
    </div>
  );
}
