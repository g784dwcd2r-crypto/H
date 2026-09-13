"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { ArrowIcon, SearchIcon } from "@/components/Icons";
import type { Company } from "@/lib/api";

export default function SearchBox({ initial = "", autoFocus = true }: { initial?: string; autoFocus?: boolean }) {
  const [q, setQ] = useState(initial);
  const [items, setItems] = useState<Company[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const router = useRouter();
  const box = useRef<HTMLInputElement>(null);
  const listId = useId();
  const resultTerm = useRef("");

  useEffect(() => { setQ(initial); setBusy(false); }, [initial]);
  useEffect(() => {
    const term = q.trim();
    setItems([]);
    setActive(-1);
    resultTerm.current = "";
    if (!term || !dirty) { setOpen(false); setStatus("idle"); return; }
    const controller = new AbortController();
    setStatus("loading");
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/search?q=${encodeURIComponent(term)}`, { signal: controller.signal });
        if (!response.ok) throw new Error("Search unavailable");
        const data = (await response.json()) as { results: Company[] };
        if (controller.signal.aborted) return;
        setItems(data.results);
        resultTerm.current = term;
        setStatus("ready");
        setOpen(document.activeElement === box.current);
      } catch {
        if (controller.signal.aborted) return;
        setItems([]); setStatus("error"); setOpen(document.activeElement === box.current);
      }
    }, 150);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [q, dirty]);

  const go = (c: Company) => { setOpen(false); router.push(`/companies/${c.cik}`); };
  const submit = () => {
    const term = q.trim();
    if (!term) { box.current?.focus(); return; }
    const matches = resultTerm.current === term ? items : [];
    if (active >= 0 && matches[active]) return go(matches[active]);
    const exact = matches.find((c) => (c.ticker ?? "").toUpperCase() === term.toUpperCase() || String(c.cik) === term);
    if (exact) return go(exact);
    if (matches.length === 1) return go(matches[0]);
    setBusy(true); setOpen(false); router.push(`/?q=${encodeURIComponent(term)}`);
    // A repeat query may reuse the current route without a component update.
    setTimeout(() => setBusy(false), 1000);
  };
  return (
    <form className="search" role="search" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <div className="search-field">
        <SearchIcon className="search-glyph" />
        <input id="site-search" ref={box} value={q} onChange={(e) => { setDirty(true); setQ(e.target.value); setBusy(false); }}
          onFocus={() => dirty && status !== "idle" && setOpen(true)} onBlur={() => setOpen(false)}
          onKeyDown={(e) => {
            if (e.key === "Escape") { setOpen(false); return; }
            if (!items.length) return;
            if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, items.length - 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, -1)); }
          }}
          placeholder="Search company or ticker" aria-label="Search company, ticker or CIK" role="combobox" aria-autocomplete="list" aria-controls={listId}
          aria-expanded={open} aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined} autoComplete="off" autoFocus={autoFocus} />
        {open && <div className="suggest-panel"><ul className="suggest" id={listId} role="listbox" aria-label="Matching companies">{items.map((c, i) => <li id={`${listId}-${i}`} key={c.cik} role="option" aria-selected={i === active} className={i === active ? "active" : ""} onMouseDown={(e) => { e.preventDefault(); go(c); }} onMouseEnter={() => setActive(i)}><span className="s-name">{c.name}</span><span className="s-meta">{c.ticker ?? ""}{c.exchange ? ` · ${c.exchange}` : ""}{!c.is_active && " · inactive"}</span></li>)}</ul><p className="suggest-status" role="status">{status === "error" ? "Search is temporarily unavailable. Please try again." : status === "loading" ? "Searching companies…" : items.length ? "↑ ↓ to choose · Enter to open · Esc to close" : "No match. Try a ticker, CIK or a shorter name."}</p></div>}
      </div>
      <button type="submit" disabled={busy} aria-label={busy ? "Opening search results" : "Search companies"}><ArrowIcon /></button>
    </form>
  );
}
