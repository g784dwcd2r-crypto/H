"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

export default function SettingsNav() {
  const pathname = usePathname();
  return <nav className="company-nav settings-nav" aria-label="Account settings">
    <Link href="/settings" aria-current={pathname === "/settings" ? "page" : undefined}>Preferences</Link>
    <Link href="/settings/security" aria-current={pathname === "/settings/security" ? "page" : undefined}>Sessions & security</Link>
  </nav>;
}
