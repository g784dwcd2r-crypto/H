"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

// "/" focuses search (from anywhere), Esc leaves an input, "w" opens the watchlist.
export default function Shortcuts() {
  const router = useRouter();
  const path = usePathname();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
      if (e.key === "Escape" && typing) {
        (t as HTMLInputElement).blur();
        return;
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "/") {
        e.preventDefault();
        const box = document.getElementById("site-search") as HTMLInputElement | null;
        if (box) {
          box.focus();
          box.select();
        } else router.push("/research");
      } else if (e.key === "w") {
        router.push("/watchlist");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router, path]);
  return null;
}
