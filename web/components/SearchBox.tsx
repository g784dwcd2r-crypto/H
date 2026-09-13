"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { Company } from "@/lib/api";

// One box, then the right thing: suggestions as you type, Enter on an exact ticker opens the company.
export default function SearchBox({ initial = "", autoFocus = true }: { initial?: string; autoFocus?: boolean }) {
  const [q, setQ] = useState(initial);
  const [items, setItems] = useState<Company[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false); // suggestions only once the person has typed here
  const router = useRouter();
  const box = useRef<HTMLInputElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    const term = q.trim();
    if (term.length < 1 || !dirty) {
      setItems([]);
      setOpen(false);
      return;
    }
    timer.current = setTimeout(async () => {
      try {
        const r = await fetch(`/api/search?q=${encodeURIComponent(term)}`);
        const data = (await r.json()) as { results: Company[] };
        setItems(data.results);
        setOpen(true);
        setActive(-1);
      } catch {
        setItems([]);
      }
    }, 120);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [q, dirty]);

  const go = (c: Company) => {
    setOpen(false);
    router.push(`/companies/${c.cik}`);
  };

  const submit = async () => {
    const term = q.trim();
    if (!term) return;
    const exact = items.find((c) => (c.ticker ?? "").toUpperCase() === term.toUpperCase()) ?? (items.length === 1 ? items[0] : null);
    if (active >= 0 && items[active]) return go(items[active]);
    if (exact) return go(exact);
    setBusy(true);
    router.push(`/?q=${encodeURIComponent(term)}`);
  };

  return (
    <form
      className="search"
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <div className="search-field">
        <input
          id="site-search"
          ref={box}
          value={q}
          onChange={(e) => {
            setDirty(true);
            setQ(e.target.value);
          }}
          onFocus={() => items.length && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (!open || !items.length) return;
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(a + 1, items.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, -1));
            } else if (e.key === "Escape") {
              setOpen(false);
            }
          }}
          placeholder="Company name, ticker or CIK"
          aria-label="Search companies"
          aria-autocomplete="list"
          aria-expanded={open}
          autoComplete="off"
          autoFocus={autoFocus}
        />
        {open && items.length > 0 && (
          <ul className="suggest" role="listbox">
            {items.map((c, i) => (
              <li
                key={c.cik}
                role="option"
                aria-selected={i === active}
                className={i === active ? "active" : ""}
                onMouseDown={(e) => {
                  e.preventDefault();
                  go(c);
                }}
                onMouseEnter={() => setActive(i)}
              >
                <span className="s-name">{c.name}</span>
                <span className="s-meta">
                  {c.ticker ?? ""}
                  {c.exchange ? ` · ${c.exchange}` : ""}
                  {!c.is_active && " · inactive"}
                </span>
              </li>
            ))}
            <li className="hint">↵ opens the top match · ↑↓ to choose</li>
          </ul>
        )}
      </div>
      <button type="submit" disabled={busy}>
        Search
      </button>
    </form>
  );
}
