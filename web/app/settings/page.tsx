import { redirect } from "next/navigation";
import PrefsSettings from "@/components/PrefsSettings";
import { api } from "@/lib/api";
import { currentUser, sessionToken } from "@/lib/session";

export const dynamic = "force-dynamic";
export const metadata = { title: "Settings · Filings Hub" };

export default async function SettingsPage() {
  const user = await currentUser();
  if (!user) redirect("/signin");
  const token = (await sessionToken())!;
  const { prefs, defaults } = await api.listPrefs(token);
  return (
    <>
      <p className="eyebrow">Settings</p>
      <h1>Your preferences</h1>
      <p className="lead">Signed in as {user.email}. Every choice you make on a statement or a company page is kept here with the scope it applies to. Reset any of them; export them to share with a colleague.</p>
      <PrefsSettings initial={prefs} defaults={defaults} />
    </>
  );
}
