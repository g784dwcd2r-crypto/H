import Link from "next/link";

export default function ResearchNav({ current }: { current: "search" | "ask" }) {
  return <nav className="research-subnav" aria-label="Research tools"><Link href="/research" aria-current={current === "search" ? "page" : undefined}>Search filings</Link><Link href="/research/ask" aria-current={current === "ask" ? "page" : undefined}>Ask with sources</Link></nav>;
}
