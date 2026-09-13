import type { Metadata } from "next";
import Link from "next/link";
import Shortcuts from "@/components/Shortcuts";
import UserMenu from "@/components/UserMenu";
import "./globals.css";

export const metadata: Metadata = {
  title: "Disclosure",
  description: "Any SEC-registered company: periods, results filings, as-reported statements, Excel.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Inter:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <Shortcuts />
        <header className="top">
          <div className="inner">
            <Link href="/" className="brand">Disclosure</Link>
            <nav>
              <Link href="/">Search</Link>
              <Link href="/watchlist">Watchlist</Link>
              <a href="https://www.sec.gov/edgar" target="_blank" rel="noreferrer">EDGAR</a>
              <UserMenu />
            </nav>
          </div>
        </header>
        <main>{children}</main>
        <footer className="bottom">
          <div className="inner">
            <span>Disclosure · SEC filings, organised by period. Statements exactly as reported.</span>
            <span>Source: SEC EDGAR and the Financial Statement Data Sets. Refreshed daily. Keys: <kbd>/</kbd> search · <kbd>w</kbd> watchlist · <kbd>1</kbd>–<kbd>3</kbd> statements</span>
          </div>
        </footer>
      </body>
    </html>
  );
}
