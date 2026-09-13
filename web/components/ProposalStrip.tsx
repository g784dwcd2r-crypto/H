"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { Proposal } from "@/lib/api";
import { logEvent } from "@/lib/prefs-client";

const KEY_WORDS: Record<string, string> = {
  period_mode: "period view",
  scale: "scale",
  column_order: "column order",
  restated: "restated comparatives",
  periods_shown: "number of periods",
  negative_style: "negative numbers",
  export_config: "export settings",
};
const VALUE_WORDS: Record<string, string> = {
  as_filed: "as filed",
  quarterly: "quarterly",
  annual: "annual",
  ltm: "trailing twelve months",
  newest_right: "oldest to newest",
  newest_left: "newest first",
  units: "full units",
  thousands: "thousands",
  millions: "millions",
  billions: "billions",
  parentheses: "parentheses",
  minus: "a minus sign",
};

export function describe(p: Proposal): string {
  const k = KEY_WORDS[p.key] ?? p.key;
  if (p.key === "export_config") return `the same export settings`;
  if (typeof p.value === "boolean") return `${k} ${p.value ? "on" : "off"}`;
  return `${k}: ${VALUE_WORDS[String(p.value)] ?? String(p.value)}`;
}

/**
 * Three strikes: a choice made on three companies is proposed as the default everywhere. Shown once
 * per page load, dismissed twice it never comes back, accepted it becomes a global preference marked
 * "inferred" so /settings shows how it got there. Signed-in people only: proposals come from the account.
 */
export default function ProposalStrip({ signedIn }: { signedIn: boolean }) {
  const router = useRouter();
  const [p, setP] = useState<Proposal | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  useEffect(() => {
    if (!signedIn) return;
    fetch("/api/proposals")
      .then((r) => r.json())
      .then((d: { proposals: Proposal[] }) => {
        const first = d.proposals?.[0] ?? null;
        if (first) {
          try {
            const seen = window.sessionStorage.getItem("fh:proposal:" + first.id);
            if (!seen) {
              window.sessionStorage.setItem("fh:proposal:" + first.id, "1");
              logEvent("proposal.shown", { key: first.key }, true);
            }
          } catch {
            /* ignore */
          }
        }
        setP(first);
      })
      .catch(() => setP(null));
  }, [signedIn]);
  if (!p) return null;
  const act = async (action: "accept" | "dismiss") => {
    setBusy(true);
    try {
    const response = await fetch("/api/proposals", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: p.key, value: p.value, action }) });
    if (!response.ok) throw new Error("Proposal update failed");
    setError(false);
    logEvent(`proposal.${action}`, { key: p.key }, true);
    setP(null);
    setBusy(false);
    if (action === "accept") router.refresh();
    } catch { setError(true); } finally { setBusy(false); }
  };
  return (
    <div className="proposal" role="status">
      <span>
        You chose <strong>{describe(p)}</strong> on {p.companies.length} companies. Make it your default everywhere?
      </span>
      {error && <span className="err" role="alert">Couldn’t save your choice. Please try again.</span>}
      <span className="row">
        <button type="button" className="btn small" disabled={busy} onClick={() => void act("accept")}>Yes, everywhere</button>
        <button type="button" className="linkbtn" disabled={busy} onClick={() => void act("dismiss")}>Not now</button>
      </span>
    </div>
  );
}
