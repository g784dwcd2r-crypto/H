"use client";
import Link from "next/link";
export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <section className="empty page-error"><p className="eyebrow">Temporarily unavailable</p><h1>We couldn’t load this page.</h1><p>The data service may be catching up or temporarily unavailable. Try again to resume your research.</p><div className="row"><button className="btn" onClick={reset}>Try again</button><Link href="/" className="btn secondary">Back to research</Link></div></section>;
}
