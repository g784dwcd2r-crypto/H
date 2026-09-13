"use client";

import Link from "next/link";
import { useState } from "react";
import { DisclosureMark } from "@/components/Brand";
import { ArrowIcon, DocumentIcon, SearchIcon, SettingsIcon, StarIcon } from "@/components/Icons";
import { EXAMPLE_ANNUAL, EXAMPLE_RELEASE, EXAMPLE_ROWS, EXAMPLE_SOURCE } from "@/lib/example-data";

export default function WorkspacePreview() {
  const [selected, setSelected] = useState({ row: 0, year: 0 });
  const [tab, setTab] = useState("Financials");
  const metric = EXAMPLE_ROWS[selected.row];
  return (
    <div className="preview-frame" id="platform">
      <div className="preview-workspace">
        <aside className="preview-sidebar" aria-label="Example workspace shortcuts">
          <div className="preview-brand"><DisclosureMark /><span>Disclosure</span></div>
          <a href="#site-search" className="selected"><SearchIcon /> Research</a>
          <Link href="/watchlist"><StarIcon /> Watchlist</Link>
          <Link href="/settings"><SettingsIcon /> Settings</Link>
          <span className="preview-caption">Interactive example<br />Historical source data</span>
        </aside>
        <div className="preview-main">
          <div className="preview-company"><span className="company-monogram" aria-hidden="true">A</span><div><h2>Apple Inc.</h2><p>AAPL · NASDAQ</p></div><Link href="/companies/320193/statements?mode=annual" className="preview-open">Open financials <ArrowIcon /></Link></div>
          <div className="preview-tabs" role="tablist" aria-label="Example views">{["Overview", "Financials", "Filings"].map((t) => <button role="tab" aria-selected={tab === t} key={t} onClick={() => setTab(t)}>{t}</button>)}</div>
          {tab === "Financials" ? <div role="tabpanel" aria-label="Example financials">
            <div className="preview-heading"><h3>Income statement</h3><span>Historical example · USD millions</span></div>
            <table className="preview-table"><caption className="sr-only">Apple historical annual results. Select a number to inspect its source.</caption><thead><tr><th scope="col">Line item</th><th scope="col">FY 2024</th><th scope="col">FY 2023</th></tr></thead><tbody>{EXAMPLE_ROWS.map((r, row) => <tr key={r.label}><th scope="row">{r.label}</th>{r.values.map((value, year) => <td key={year}><button className={selected.row === row && selected.year === year ? "selected" : ""} onClick={() => setSelected({ row, year })} aria-pressed={selected.row === row && selected.year === year} aria-label={`${r.label}, FY ${2024 - year}, ${value.toLocaleString("en-US")} million USD. Inspect source.`}>{value.toLocaleString("en-US")}</button></td>)}</tr>)}</tbody></table>
            <div className="preview-evidence" aria-live="polite"><DocumentIcon /><div><strong>{metric.label} · FY {2024 - selected.year}</strong><span>Apple FY2024 results · Financial statements, p. 1</span></div><a href={EXAMPLE_SOURCE} target="_blank" rel="noreferrer">View source ↗</a></div>
          </div> : tab === "Filings" ? <div className="preview-documents" role="tabpanel" aria-label="Example filings"><p className="eyebrow">Fiscal year 2024</p><h3>One period. Related filings.</h3><a href={EXAMPLE_ANNUAL} target="_blank" rel="noreferrer"><DocumentIcon /><span>Annual report<small>Form 10-K · November 1, 2024</small></span><span>↗</span></a><a href={EXAMPLE_RELEASE} target="_blank" rel="noreferrer"><DocumentIcon /><span>Earnings release<small>Fourth quarter results · October 31, 2024</small></span><span>↗</span></a></div> : <div className="preview-overview" role="tabpanel" aria-label="Example overview"><p className="eyebrow">Fiscal year 2024 · Historical example</p><h3>A clear starting point.</h3><p>Explore the reported numbers, then follow the evidence into the original document.</p><div><span>Total net sales<strong>$391,035m</strong></span><span>Net income<strong>$93,736m</strong></span></div><button className="text-link" onClick={() => setTab("Financials")}>Inspect the financials <ArrowIcon /></button></div>}
        </div>
      </div>
    </div>
  );
}
