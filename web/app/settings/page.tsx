import { redirect } from "next/navigation";
import PrefsSettings from "@/components/PrefsSettings";
import { api } from "@/lib/server-api";
import { currentUser, sessionToken } from "@/lib/session";

export const dynamic = "force-dynamic";
export const metadata = { title: "Settings · Disclosure" };

export default async function SettingsPage() {
  const user = await currentUser();
  if (!user) redirect("/signin");
  const token = (await sessionToken())!;
  const { prefs, defaults } = await api.listPrefs(token);
  return (
    <>
      <p className="eyebrow">Settings</p>
      <h1>Your preferences</h1>
      <p className="lead">
        Signed in as {user.email}
        {user.first_name ? ` (${user.first_name} ${user.last_name}${user.company ? `, ${user.company}` : ""}${user.title ? `, ${user.title}` : ""})` : ""}. Manage your saved research and export defaults. See where each choice applies, change it or take your settings with you.
      </p>
      <PrefsSettings initial={prefs} defaults={defaults} />
    </>
  );
}
