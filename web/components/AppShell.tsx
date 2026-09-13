"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import Brand from "@/components/Brand";
import { SearchIcon, StarIcon } from "@/components/Icons";

export default function AppShell({ children, userMenu }: { children: ReactNode; userMenu: ReactNode }) {
  const path = usePathname();
  const home = path === "/";
  return (
    <div className={home ? "app-shell public-shell" : "app-shell workspace-shell"}>
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="top">
        <div className="inner">
          <Brand />
          <nav aria-label="Main navigation" className="main-nav">
            {home ? <><a href="#platform">Platform</a><a href="#how-it-works">How it works</a><Link href="/coverage">Coverage</Link></> : <><Link href="/research" className={path.startsWith("/research") ? "current" : ""} aria-current={path.startsWith("/research") ? "page" : undefined}><SearchIcon /> Research</Link><Link href="/watchlist" className={path === "/watchlist" ? "current" : ""}><StarIcon /> Watchlist</Link><Link href="/projects" className={path.startsWith("/projects") ? "current" : ""} aria-current={path.startsWith("/projects") ? "page" : undefined}>Projects</Link><Link href="/compare" className={path === "/compare" ? "current" : ""} aria-current={path === "/compare" ? "page" : undefined}>Compare</Link><Link href="/coverage" className={path === "/coverage" ? "current" : ""}>Coverage</Link></>}
          </nav>
          <div className="account-nav">{userMenu}</div>
        </div>
      </header>
      <main id="main-content">{children}</main>
      <footer className="bottom">
        <div className="inner">
          <div><Link href="/" className="footer-brand">Disclosure</Link><p>Company filings. Clearly organised.</p></div>
          <nav aria-label="Footer navigation"><Link href="/coverage">Coverage & sources</Link><Link href="/watchlist">Your watchlist</Link><Link href="/settings">Preferences</Link><Link href="/settings/security">Sessions & security</Link><a href="https://www.sec.gov/edgar" target="_blank" rel="noreferrer">SEC EDGAR ↗</a></nav>
          <p className="footer-keys"><kbd>/</kbd> Search <span>·</span> <kbd>w</kbd> Watchlist</p>
        </div>
        <div className="footer-note">Reported figures and supported calculations retain their source context. Availability varies by company and period.</div>
      </footer>
    </div>
  );
}
