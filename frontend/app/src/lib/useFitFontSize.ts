import { useLayoutEffect, useRef } from "react";

/**
 * Shrinks an element's font-size just enough to fit its parent's width,
 * floored at 60% of the resolved size. Below that floor the caller's own
 * overflow/scroll fallback takes over — this hook only ever shrinks, never
 * clips.
 *
 * Reads the starting size via `getComputedStyle` rather than a hardcoded
 * base, so it composes with any CSS breakpoint already in effect instead of
 * fighting it.
 */
export function useFitFontSize<T extends HTMLElement>(active: boolean, deps: readonly unknown[]) {
  const ref = useRef<T>(null);

  useLayoutEffect(() => {
    if (!active) return;
    const el = ref.current;
    if (!el?.parentElement) return;
    const parent = el.parentElement;

    const fit = () => {
      el.style.fontSize = "";
      const base = parseFloat(getComputedStyle(el).fontSize);
      if (!base) return;
      const available = parent.clientWidth;
      const needed = el.scrollWidth;
      if (needed <= available || available <= 0) return;
      el.style.fontSize = `${base * Math.max(0.6, available / needed)}px`;
    };

    fit();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(fit);
    ro.observe(parent);
    return () => ro.disconnect();
  }, [active, ...deps]);

  return ref;
}
