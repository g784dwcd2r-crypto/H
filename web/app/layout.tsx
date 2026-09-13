import type { Metadata } from "next";
import AppShell from "@/components/AppShell";
import Shortcuts from "@/components/Shortcuts";
import UserMenu from "@/components/UserMenu";
import "./fonts.css";
import "./globals.css";
import "./typography.css";

export const metadata: Metadata = {
  title: { default: "Disclosure — Company filings, clearly organised", template: "%s · Disclosure" },
  description: "Find company filings, compare as-reported financials, inspect their sources and export selected periods to Excel.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preload" href="/fonts/eb-garamond-regular.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
        <link rel="preload" href="/fonts/albert-sans-regular.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
      </head>
      <body><Shortcuts /><AppShell userMenu={<UserMenu />}>{children}</AppShell></body>
    </html>
  );
}
