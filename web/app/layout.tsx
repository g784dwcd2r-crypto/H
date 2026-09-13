import type { Metadata } from "next";
import AppShell from "@/components/AppShell";
import Shortcuts from "@/components/Shortcuts";
import UserMenu from "@/components/UserMenu";
import "./globals.css";
import "./typography.css";

export const metadata: Metadata = {
  title: { default: "Disclosure — Company filings, clearly organised", template: "%s · Disclosure" },
  description: "Find company filings, compare as-reported financials, inspect their sources and export selected periods to Excel.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // A licensed Adobe web project can be enabled without shipping font binaries.
  const kitId = process.env.ADOBE_FONTS_KIT_ID?.trim();
  const fontStylesheet = kitId && /^[a-z0-9]{7}$/.test(kitId)
    ? `https://use.typekit.net/${kitId}.css`
    : undefined;
  return (
    <html lang="en">
      <head>{fontStylesheet && <link rel="stylesheet" href={fontStylesheet} />}</head>
      <body><Shortcuts /><AppShell userMenu={<UserMenu />}>{children}</AppShell></body>
    </html>
  );
}
