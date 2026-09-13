import type { Metadata } from "next";
import AppShell from "@/components/AppShell";
import Shortcuts from "@/components/Shortcuts";
import UserMenu from "@/components/UserMenu";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Disclosure — Company filings, clearly organised", template: "%s · Disclosure" },
  description: "Find company filings, compare as-reported financials, inspect their sources and export selected periods to Excel.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body><Shortcuts /><AppShell userMenu={<UserMenu />}>{children}</AppShell></body>
    </html>
  );
}
