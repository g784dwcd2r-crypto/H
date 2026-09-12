import Link from "next/link";

export default function NotFound() {
  return (
    <div className="empty">
      <p>That company is not in the hub.</p>
      <Link href="/">Back to search</Link>
    </div>
  );
}
