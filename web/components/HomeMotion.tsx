"use client";

import { useEffect } from "react";

/** Enhance below-the-fold content once. Nothing depends on animation to become visible. */
export default function HomeMotion() {
  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (preference.matches || !("IntersectionObserver" in window)) return;

    const animations = new Set<Animation>();
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        observer.unobserve(entry.target);
        const animation = entry.target.animate(
          [{ opacity: .45, transform: "translateY(16px)" }, { opacity: 1, transform: "none" }],
          { duration: 600, easing: "cubic-bezier(.2,.7,.2,1)" },
        );
        animations.add(animation);
        animation.onfinish = () => animations.delete(animation);
      }
    }, { threshold: .08 });

    document.querySelectorAll("[data-reveal]").forEach((element) => {
      // Above-the-fold content is already visible; do not flash it after hydration.
      if (element.getBoundingClientRect().top >= window.innerHeight) observer.observe(element);
    });
    const stop = () => {
      observer.disconnect();
      animations.forEach((animation) => animation.cancel());
      animations.clear();
    };
    const onPreferenceChange = () => { if (preference.matches) stop(); };
    preference.addEventListener("change", onPreferenceChange);
    return () => { stop(); preference.removeEventListener("change", onPreferenceChange); };
  }, []);

  return null;
}
