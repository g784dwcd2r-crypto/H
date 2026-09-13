import Link from "next/link";
import { redirect } from "next/navigation";
import SignUpForm from "@/components/SignUpForm";
import { api } from "@/lib/server-api";
import { currentUser } from "@/lib/session";
import { cookies } from "next/headers";
import { authHref, authRegion, REGION_COOKIE, safeAuthNext } from "@/lib/auth-navigation";

export const dynamic = "force-dynamic";
export const metadata = { title: "Get started · Disclosure" };

export default async function SignUpPage({ searchParams }: { searchParams: Promise<{ next?: string; region?: string }> }) {
  const { next: requestedNext, region: requestedRegion } = await searchParams;
  const next = safeAuthNext(requestedNext);
  const region = authRegion(requestedRegion, (await cookies()).get(REGION_COOKIE)?.value);
  if (await currentUser()) redirect(requestedNext ? next : "/settings");
  const cfg = await api.authConfig().catch(() => ({ email_link: false, google_client_id: null, site_url: "", business_email_only: false }));
  return (
    <div className="narrow">
      <h1>
        Get started <em className="accent">for free</em>
      </h1>
      <p className="lead">Fill in the form and we email you a link. Your account keeps your scale, your statements and your period counts on every device.</p>
      <SignUpForm businessOnly={!!(cfg as { business_email_only?: boolean }).business_email_only} emailLink={cfg.email_link} next={next} region={region} />
      <p className="muted" style={{ marginTop: 24 }}>
        Already have an account? <Link href={authHref("/signin", next, region)}>Sign in</Link>.
      </p>
    </div>
  );
}
