import { redirect } from "next/navigation";
import SettingsNav from "@/components/SettingsNav";
import SessionManager from "@/components/SessionManager";
import { sessionToken } from "@/lib/session";
import { workspaceRequest } from "@/lib/workspace-api";
import type { SessionsResponse } from "@/lib/workspace-types";

export const dynamic = "force-dynamic";
export const metadata = { title: "Sessions & security" };

export default async function SecurityPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  if (!await sessionToken()) redirect("/signin");
  const result = await workspaceRequest<SessionsResponse>("/me/sessions");
  if (result.status === 401) redirect("/signin");
  const query = await searchParams;
  return <>
    <p className="eyebrow">Your account</p><h1>Sessions & security</h1><p className="lead">Review where you are signed in and revoke access to a session you no longer use.</p>
    <SettingsNav />
    <SessionManager initial={result.data?.sessions ?? null} initialError={query.error === "signout" ? "Sign-out could not be completed. Your session is still active. Please try again." : result.ok ? null : "Sessions could not be loaded. Please try again."} />
  </>;
}
