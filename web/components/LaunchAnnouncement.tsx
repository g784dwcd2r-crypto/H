"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import styles from "./PublicHeader.module.css";

const CAMPAIGN = "founding-members-2026";
const STORAGE_KEY = "disclosure-announcement-dismissed";
type CampaignState = "open" | "full" | "closed" | "unknown";

export default function LaunchAnnouncement() {
  const [dismissed, setDismissed] = useState(false);
  const [state, setState] = useState<CampaignState>("unknown");
  useEffect(() => {
    try { setDismissed(localStorage.getItem(STORAGE_KEY) === CAMPAIGN); } catch { /* Dismissal still works without storage. */ }
    let controller: AbortController;
    const refresh = () => {
      controller?.abort();
      controller = new AbortController();
      const signal = controller.signal;
      fetch("/api/launch/campaign", { signal, cache: "no-store" })
        .then(response => response.ok ? response.json() : null)
        .then(data => {
          if (!signal.aborted && data?.campaign?.id === CAMPAIGN && ["open", "full", "closed"].includes(data.campaign.state)) setState(data.campaign.state);
        })
        .catch(() => { /* A static launch invitation is safe when campaign availability is unknown. */ });
    };
    refresh();
    window.addEventListener("disclosure-campaign-changed", refresh);
    window.addEventListener("focus", refresh);
    return () => { controller.abort(); window.removeEventListener("disclosure-campaign-changed", refresh); window.removeEventListener("focus", refresh); };
  }, []);

  if (dismissed) return null;
  const dismiss = () => {
    setDismissed(true);
    try { localStorage.setItem(STORAGE_KEY, CAMPAIGN); } catch { /* Optional convenience. */ }
  };
  const message = state === "open"
    ? "Disclosure opens 1 November. Six months free for our first 20 founding members."
    : state === "full"
      ? "Our 20 founding places are filled. Disclosure opens 1 November."
      : state === "closed"
        ? "Founding-member registration has closed. Explore Disclosure."
        : "Disclosure opens 1 November. Discover our founding-member programme.";
  const action = state === "full" ? "Join the waitlist" : state === "closed" ? "Explore the platform" : "Join early access";
  return (
    <aside aria-label="Disclosure launch announcement" className={styles.announcement}>
      <p><span>{message}</span> <Link href={state === "closed" ? "/platform" : "/early-access"}>{action} <span aria-hidden="true">→</span></Link></p>
      <button type="button" onClick={dismiss} aria-label="Dismiss launch announcement"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m5 5 10 10M15 5 5 15" stroke="currentColor" strokeWidth="1.4" /></svg></button>
    </aside>
  );
}
