"use client";

import { useEffect } from "react";
import { LOGIN_REGIONS, type LoginRegion } from "@/lib/public-navigation";

export default function AuthRegionNotice({ region }: { region: LoginRegion | null }) {
  useEffect(() => {
    if (region) document.cookie = `fh_region=${region}; Path=/; Max-Age=31536000; SameSite=Lax${location.protocol === "https:" ? "; Secure" : ""}`;
  }, [region]);
  return <p className="muted small" style={{ marginBottom: 24 }}>
    {region && <span>{LOGIN_REGIONS.find(option => option.code === region)?.label} · </span>}
    All regions currently use Disclosure Global. Your region is a preference; it does not change data hosting or filing coverage.
  </p>;
}
