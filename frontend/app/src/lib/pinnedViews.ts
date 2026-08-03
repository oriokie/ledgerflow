import { useCallback, useEffect, useState } from "react";

/**
 * Views the user has pinned to the rail.
 *
 * A pin is a **named URL** — nothing more. That is the whole design: any state
 * this app can put in a location (a filtered Activity list, a category
 * drill-down, a report with a range selected) is pinnable, and none of those
 * screens needs to know pinning exists. The alternative — a bespoke "saved
 * filter" model per feature — is how this kind of thing usually rots.
 *
 * This is what converts a monthly-visit product into a weekly-habit one:
 * "Groceries this month" as a one-click rail item is a different relationship
 * with the data than reconstructing that filter every time.
 *
 * Stored locally, with the same limitation as `featureFlags`: pins do not
 * follow the user to another device, and there is no server record of them.
 * Fixing that is a `UserPreference` row and an endpoint, not a redesign.
 */
export interface PinnedView {
  id: string;
  label: string;
  /** Path + query, exactly as the router would produce it. */
  to: string;
}

const KEY = "lf-pinned-views";
const MAX_PINS = 8;
const EVENT = "lf-pins-change";

export function readPins(): PinnedView[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    // Hand-editable storage: validate rather than trust. A malformed pin
    // must not be able to crash the shell that renders the rail.
    return parsed
      .filter(
        (p): p is PinnedView =>
          !!p &&
          typeof p === "object" &&
          typeof (p as PinnedView).id === "string" &&
          typeof (p as PinnedView).label === "string" &&
          typeof (p as PinnedView).to === "string" &&
          (p as PinnedView).to.startsWith("/"),
      )
      .slice(0, MAX_PINS);
  } catch {
    return [];
  }
}

function write(pins: PinnedView[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(pins.slice(0, MAX_PINS)));
  } catch {
    /* storage unavailable — the pin simply won't persist */
  }
  window.dispatchEvent(new CustomEvent(EVENT));
}

/** Same `to` = same view, however the user got there. */
export function isPinned(pins: PinnedView[], to: string): boolean {
  return pins.some((p) => p.to === to);
}

export function usePinnedViews() {
  const [pins, setPins] = useState<PinnedView[]>(readPins);

  useEffect(() => {
    const sync = () => setPins(readPins());
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const pin = useCallback((label: string, to: string) => {
    const current = readPins();
    if (current.some((p) => p.to === to)) return;
    write([...current, { id: `${Date.now()}-${to}`, label: label.trim() || to, to }]);
  }, []);

  const unpin = useCallback((to: string) => {
    write(readPins().filter((p) => p.to !== to));
  }, []);

  return { pins, pin, unpin, full: pins.length >= MAX_PINS, max: MAX_PINS };
}

/**
 * A default name for the view at `to`, so pinning is one click for the common
 * case and a rename only when the guess is poor.
 *
 * Deliberately built from the *URL*, not from page state: a pin has to be
 * nameable from the shell, which cannot see inside whatever page is mounted.
 */
export function suggestLabel(to: string, fallback = "Pinned view"): string {
  const [path, query = ""] = to.split("?");
  const base =
    {
      "/": "Today",
      "/activity": "Activity",
      "/transactions": "Activity",
      "/plan": "Plan",
      "/insights": "Insights",
      "/accounts": "Accounts",
      "/goals": "Goals",
      "/investments": "Invest",
      "/debt": "Debt",
      "/reports": "Reports",
    }[path] ?? path.replace(/^\//, "").replace(/[-/]/g, " ") ?? fallback;

  const params = new URLSearchParams(query);
  const tab = params.get("tab");
  const qualifiers = [tab, params.get("q"), params.get("search")].filter(Boolean);
  const filtered = [...params.keys()].some((k) => !["tab"].includes(k));

  if (qualifiers.length) return `${cap(base)} · ${qualifiers.join(" ")}`;
  if (filtered) return `${cap(base)} · filtered`;
  return cap(base);
}

const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);
