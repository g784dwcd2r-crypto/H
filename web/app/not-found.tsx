import Link from "next/link";

export default function NotFound() {
  return (
    <div className="empty">
      <p>That company is not in the hub.</p>
      <p className="muted">Every SEC registrant is here, so the likely cause is a ticker that changed or a typo. The 10-digit CIK from sec.gov always works.</p>
      <Link href="/" className="btn">Back to search</Link>
    </div>
  );
}
