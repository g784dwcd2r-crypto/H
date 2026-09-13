"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { LOGIN_REGIONS, validLoginRegion, type LoginRegion } from "@/lib/public-navigation";
import { usePublicNavigation } from "./PublicNavigationContext";
import { MenuChevron } from "./PublicHeader";
import styles from "./PublicHeader.module.css";

export default function HeaderAccount({ email }: { email: string | null }) {
  const navigation = usePublicNavigation();
  const [remembered, setRemembered] = useState<LoginRegion | null>(null);
  useEffect(() => {
    const cookie = document.cookie.split("; ").find(value => value.startsWith("fh_region="))?.split("=")[1];
    if (validLoginRegion(cookie)) setRemembered(cookie);
  }, []);
  const remember = (region: LoginRegion) => {
    setRemembered(region);
    document.cookie = `fh_region=${region}; Path=/; Max-Age=31536000; SameSite=Lax${location.protocol === "https:" ? "; Secure" : ""}`;
    navigation?.close();
  };
  if (!navigation) return email ? <span className="user"><Link href="/settings" title={email}>{email}</Link><form action="/api/auth/signout" method="post" className="inline"><button type="submit" className="linkbtn">Sign out</button></form></span> : <span className="user"><Link href="/signin">Sign in</Link><Link href="/signup" className="cta">Get started</Link></span>;
  if (email) return <div className={styles.accountActions}>
    <Link href="/research" className={styles.primaryAction} onClick={() => navigation.close()}>Open workspace <span aria-hidden="true">↗</span></Link>
    <div className={styles.accountAnchor}>
      <button type="button" className={styles.loginTrigger} aria-expanded={navigation.active === "account"} aria-controls="public-account-panel" onClick={event => navigation.toggle("account", event.currentTarget)}>Account <MenuChevron /></button>
      {navigation.active === "account" && <div id="public-account-panel" className={styles.accountPanel}>
        <p className={styles.accountEmail}>{email}</p>
        <Link href="/settings" onClick={() => navigation.close()}>Preferences</Link>
        <Link href="/settings/security" onClick={() => navigation.close()}>Sessions & security</Link>
        <form action="/api/auth/signout" method="post"><button type="submit">Sign out</button></form>
      </div>}
    </div>
  </div>;
  const rememberedLabel = LOGIN_REGIONS.find(region => region.code === remembered)?.label;
  return <div className={styles.accountActions}>
    <div className={styles.accountAnchor}>
      <button type="button" className={styles.loginTrigger} aria-expanded={navigation.active === "login"} aria-controls="public-login-panel" onClick={event => navigation.toggle("login", event.currentTarget)}>Log in <MenuChevron /></button>
      {navigation.active === "login" && <div id="public-login-panel" className={styles.loginPanel}>
        <p className={styles.loginHeading}>Choose your region</p>
        {LOGIN_REGIONS.map(region => <Link href={`/signin?region=${region.code}&next=/research`} key={region.code} onClick={() => remember(region.code)}><span aria-hidden="true">{region.symbol}</span><span>{region.label}</span>{region.code === remembered && <span className={styles.regionSelected} aria-label="Remembered region">✓</span>}</Link>)}
        <p className={styles.regionNote}>All regions currently use Disclosure Global.{rememberedLabel && <span>Remembered: {rememberedLabel}.</span>}</p>
      </div>}
    </div>
    <Link href="/demo" className={styles.primaryAction} onClick={() => navigation.close()}>Request a demo</Link>
  </div>;
}
