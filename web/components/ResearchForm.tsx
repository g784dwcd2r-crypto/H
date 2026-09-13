"use client";
import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { SearchIcon } from "@/components/Icons";
import type { Company } from "@/lib/api";
import type { ResearchFilters } from "@/lib/research";

export default function ResearchForm({ filters, companyName }: { filters: ResearchFilters; companyName?: string }) {
  const [company, setCompany] = useState(companyName || filters.cik);
  const [cik, setCik] = useState(filters.cik);
  const [choices, setChoices] = useState<Company[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [dirty, setDirty] = useState(false);
  const [companyError, setCompanyError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();
  useEffect(() => {
    if (!dirty || !company.trim()) { setChoices([]); return; }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/search?q=${encodeURIComponent(company.trim())}`, { signal: controller.signal });
        if (!response.ok) throw new Error();
        const data = await response.json();
        if (controller.signal.aborted) return;
        setChoices(data.results); setOpen(document.activeElement === input.current); setCompanyError(data.results.length ? null : "No company found. Try a ticker or CIK.");
      } catch { if (!controller.signal.aborted) { setChoices([]); setCompanyError("Company lookup is unavailable. You can still enter a numeric CIK."); } }
    }, 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [company, dirty]);
  const choose = (item: Company) => { setCompany(item.name); setCik(String(item.cik)); setOpen(false); setDirty(false); setCompanyError(null); input.current?.setCustomValidity(""); };
  return <form action="/research" method="get" className="research-form" role="search" onSubmit={e => {
    if (company.trim() && !cik && !/^\d+$/.test(company.trim())) { e.preventDefault(); input.current?.setCustomValidity("Choose a company from the suggestions, enter a numeric CIK, or clear the company filter."); input.current?.reportValidity(); return; }
    setBusy(true);
  }}>
    <label className="query-label" htmlFor="site-search">Search filing text</label>
    <div className="research-query"><SearchIcon /><input id="site-search" name="q" defaultValue={filters.q} placeholder={'e.g. "supply chain" AND (risk OR disruption)'} maxLength={1000} aria-describedby="research-syntax" autoComplete="off"/><button className="btn" type="submit" disabled={busy}>{busy ? "Searching…" : "Search filings"}</button></div>
    <div className="research-filters">
      <div className="company-filter"><label htmlFor="research-company">Company</label><input type="hidden" name="cik" value={cik || (/^\d+$/.test(company.trim()) ? company.trim() : "")} />
        <input id="research-company" ref={input} value={company} placeholder="All companies · name or ticker" role="combobox" aria-autocomplete="list" aria-expanded={open && choices.length > 0} aria-controls={listId} aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined} autoComplete="off" onChange={e => { setCompany(e.target.value); setCik(""); setDirty(true); setActive(-1); setCompanyError(null); e.target.setCustomValidity(""); }} onFocus={() => choices.length > 0 && setOpen(true)} onBlur={() => setOpen(false)} onKeyDown={e => {
          if (e.key === "Escape") { setOpen(false); return; }
          if (e.key === "ArrowDown" && choices.length) { e.preventDefault(); setOpen(true); setActive(a => Math.min(a + 1, choices.length - 1)); }
          if (e.key === "ArrowUp" && choices.length) { e.preventDefault(); setActive(a => Math.max(0, a - 1)); }
          if (e.key === "Enter" && open && active >= 0 && choices[active]) { e.preventDefault(); choose(choices[active]); }
        }}/>
        {open && choices.length > 0 && <ul className="company-options" id={listId} role="listbox" aria-label="Companies">{choices.map((item, i) => <li id={`${listId}-${i}`} key={item.cik} role="option" aria-selected={i === active} className={i === active ? "active" : ""} onMouseDown={e => { e.preventDefault(); choose(item); }} onMouseEnter={() => setActive(i)}><span>{item.name}</span><small>{item.ticker || `CIK ${item.cik}`}</small></li>)}</ul>}
        {companyError && <small className="filter-hint" role="status">{companyError}</small>}
      </div>
      <label>Filing type<select name="form" defaultValue={filters.form}><option value="">All forms</option>{["10-K", "10-Q", "8-K", "20-F", "6-K", "10-K/A", "10-Q/A", "DEF 14A"].map(form => <option key={form}>{form}</option>)}</select></label>
      <label>Filed from<input type="date" name="from" defaultValue={filters.from} /></label>
      <label>Filed through<input type="date" name="to" defaultValue={filters.to} /></label>
      <Link href="/research" className="filter-reset">Clear</Link>
    </div>
    <details className="query-help" id="research-syntax"><summary>Search syntax & scope</summary><p>Use words, “quoted phrases”, AND, OR, NOT and parentheses. Search runs over indexed public SEC document text. It does not retrieve new documents when you submit a query.</p><p>For example: <code>"share repurchase" AND NOT "credit agreement"</code>. Dates filter the filing date, not its financial reporting period.</p></details>
  </form>;
}
