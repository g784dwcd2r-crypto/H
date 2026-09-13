import Link from "next/link";
import { redirect } from "next/navigation";
import SignInForm from "@/components/SignInForm";
import { api } from "@/lib/server-api";
import { currentUser } from "@/lib/session";
import { cookies } from "next/headers";
import { authHref, authRegion, REGION_COOKIE, safeAuthNext } from "@/lib/auth-navigation";

export const dynamic = "force-dynamic";
export const metadata = { title: "Sign in · Disclosure" };

export default async function SignInPage({ searchParams }: { searchParams: Promise<{ error?: string; next?: string; region?: string }> }) {
  const { error, next: requestedNext, region: requestedRegion } = await searchParams;
  const next = safeAuthNext(requestedNext);
  const region = authRegion(requestedRegion, (await cookies()).get(REGION_COOKIE)?.value);
  if (await currentUser()) redirect(requestedNext ? next : "/settings");
  const cfg = await api.authConfig().catch(() => ({ email_link: false, google_client_id: null, site_url: "" }));
  return (
    <>
      <p className="eyebrow">Account</p>
      <h1>Sign in</h1>
      <p className="lead">Your scale, your statement, your period count, remembered per company and everywhere else. Set once, then invisible.</p>
      <SignInForm emailLink={cfg.email_link} google={!!cfg.google_client_id} error={error} next={next} region={region} />
      <p className="muted" style={{ marginTop: 24 }}>
        New here? <Link href={authHref("/signup", next, region)}>Get started for free</Link>.
      </p>
    </>
  );
}
