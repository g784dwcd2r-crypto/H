import Link from "next/link";

export function DisclosureMark({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 32 36" fill="none" aria-hidden="true">
      <path d="M5 3h10c8 0 14 6.5 14 15S23 33 15 33H3V5l2-2Z" stroke="currentColor" strokeWidth="5" />
    </svg>
  );
}

export default function Brand() {
  return (
    <Link href="/" className="brand" aria-label="Disclosure home">
      <DisclosureMark />
      <span>Disclosure<small>Company filings. Clearly organised.</small></span>
    </Link>
  );
}
