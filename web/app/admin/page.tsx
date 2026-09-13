import type { Metadata } from "next";
import AdminConsole from "@/components/AdminConsole";

export const metadata: Metadata = { title: "Platform administration", robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";
export default function AdminPage() { return <AdminConsole />; }
