import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Filings Hub",
  description: "Any SEC-registered company: periods, results filings, as-reported statements, Excel.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="top">
          <div className="inner">
            <Link href="/" className="brand">Filings Hub</Link>
            <span className="muted">SEC filings, organised by period. Statements exactly as reported.</span>
          </div>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
