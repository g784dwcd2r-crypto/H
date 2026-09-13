"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function SearchForm({ initial = "" }: { initial?: string }) {
  const [q, setQ] = useState(initial);
  const router = useRouter();
  return (
    <form
      className="search"
      onSubmit={(e) => {
        e.preventDefault();
        if (q.trim()) router.push(`/?q=${encodeURIComponent(q.trim())}`);
      }}
    >
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Company name, ticker or CIK"
        aria-label="Search companies"
        autoFocus
      />
      <button type="submit">Search</button>
    </form>
  );
}
