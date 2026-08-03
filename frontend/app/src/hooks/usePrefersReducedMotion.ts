import { useEffect, useState } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

/**
 * The user's reduced-motion preference, as a value React can branch on.
 *
 * The stylesheets already honour `prefers-reduced-motion` for CSS transitions,
 * but chart animation is driven in JavaScript by recharts and never sees those
 * rules — so a user who asked for less motion still gets bars growing and
 * lines sweeping on every chart in the product.
 *
 * There is a second, less obvious reason to respect it here. Recharts animates
 * bars up from zero height using `requestAnimationFrame`, and the bar's shape
 * is not committed to the DOM until the first frame lands. Anywhere rAF does
 * not run — a background or hidden tab, print, PDF export, a screenshotting
 * pipeline — the bars never appear at all. Disabling the animation makes the
 * chart render its final state synchronously, which is both what the
 * preference asks for and what those environments need.
 */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined" && window.matchMedia?.(QUERY).matches === true,
  );

  useEffect(() => {
    const mq = window.matchMedia?.(QUERY);
    if (!mq) return;
    const onChange = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener("change", onChange);
    setReduced(mq.matches);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  return reduced;
}
