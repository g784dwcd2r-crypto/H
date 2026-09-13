import Link from "next/link";
import { redirect } from "next/navigation";
import SignInForm from "@/components/SignInForm";
import { api } from "@/lib/api";
import { currentUser } from "@/lib/session";

export const dynamic = "force-dynamic";
export const metadata = { title: "Sign in · Filings Hub" };

export default async function SignInPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  if (await currentUser()) redirect("/settings");
  const cfg = await api.authConfig().catch(() => ({ email_link: false, google_client_id: null, site_url: "" }));
  return (
    <>
      <p className="eyebrow">Account</p>
      <h1>Sign in</h1>
      <p className="lead">Your scale, your statement, your period count, remembered per company and everywhere else. Set once, then invisible.</p>
      <SignInForm emailLink={cfg.email_link} google={!!cfg.google_client_id} error={error} />
      <p className="muted" style={{ marginTop: 24 }}>
        New here? <Link href="/signup">Get started for free</Link>.
      </p>
    </>
  );
}
