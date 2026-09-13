"use client";

import { useEffect, useRef, useState } from "react";

// The filing in a sandboxed frame (no scripts; its own styles stay inside), with a jump list beside it.
export default function Reader({ html, toc }: { html: string; toc: { id: string; title: string }[] }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const doc = `<!doctype html><html><head><meta charset="utf-8"><base target="_blank"><style>
    html{scroll-behavior:smooth} body{margin:0;padding:24px 28px;font:15px/1.55 Georgia,"Times New Roman",serif;color:#141414;background:#fbfaf7;max-width:980px}
    table{max-width:100%} img{max-width:100%;height:auto} [id^="fh-"]{scroll-margin-top:16px}
  </style></head><body>${html}</body></html>`;

  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    const size = () => {
      const h = el.contentDocument?.documentElement?.scrollHeight;
      if (h) el.style.height = `${Math.max(600, h + 40)}px`;
    };
    el.addEventListener("load", size);
    const t = setInterval(size, 1500);
    return () => {
      el.removeEventListener("load", size);
      clearInterval(t);
    };
  }, [doc]);

  const jump = (id: string) => {
    const target = frame.current?.contentDocument?.getElementById(id);
    if (!target || !frame.current) return;
    const top = target.getBoundingClientRect().top + (frame.current.getBoundingClientRect().top + window.scrollY);
    window.scrollTo({ top: top - 90, behavior: "smooth" });
    setCurrent(id);
  };

  return (
    <div className="reader">
      <aside className="toc">
        <p className="eyebrow">In this document</p>
        {toc.length === 0 ? (
          <p className="muted small">No section headings found. Use your browser's find (⌘F) inside the page.</p>
        ) : (
          <ul>
            {toc.map((t) => (
              <li key={t.id} className={(t.title.match(/^(part|consolidated|condensed|notes|balance|statements?)/i) ? "top " : "") + (current === t.id ? "current" : "")}>
                <button type="button" onClick={() => jump(t.id)}>
                  {t.title}
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>
      <iframe ref={frame} className="doc" title="Filing" sandbox="allow-same-origin allow-popups" srcDoc={doc} />
    </div>
  );
}
