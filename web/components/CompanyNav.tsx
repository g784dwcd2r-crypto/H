"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
export default function CompanyNav({ cik }: { cik: string }) {
  const path = usePathname();
  const base = `/companies/${cik}`;
  return <nav className="company-nav" aria-label="Company navigation"><Link href={base} aria-current={path === base ? "page" : undefined}>Overview</Link><Link href={`${base}/statements`} aria-current={path.endsWith("/statements") ? "page" : undefined}>Financials</Link><Link href={`${base}#filings`} aria-current={path.includes("/filings/") ? "page" : undefined}>Filings</Link><Link href={`${base}/search`} aria-current={path.endsWith("/search") ? "page" : undefined}>Search filings</Link></nav>;
}
