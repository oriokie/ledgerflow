import { useCallback, useEffect, useState } from "react";

/**
 * Per-user feature flags, persisted locally.
 *
 * Only one flag so far: the Phase 5 information architecture, which collapses
 * 21 primary destinations into 8. IA changes are the one category of redesign
 * that measurably breaks habitual users — someone who has typed `/bills` for a
 * year does not want to discover it is now a tab. A flag turns that gamble into
 * something the user opts into and can reverse in one click.
 *
 * **This is deliberately local, and that is a real limitation.** The roadmap's
 * exit criteria talk about watching time-to-first-action and support volume
 * across a cohort, and localStorage cannot support that: there is no server
 * record of who is in which arm, no way to enrol a percentage, and no way to
 * turn it off remotely if something is wrong. Doing this properly needs the
 * flag on the user model with the API reporting it. What is here is honest for
 * a single-user opt-in and nothing more — see `docs/redesign/06-roadmap.md`.
 */
export type FlagName = "navV2";

const STORAGE_KEY: Record<FlagName, string> = {
  navV2: "lf-flag-nav-v2",
};

/** Read outside React — routing needs this before any component mounts. */
export function readFlag(name: FlagName): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY[name]) === "on";
  } catch {
    /* storage unavailable (private mode, embedded webview) */
    return false;
  }
}

export function writeFlag(name: FlagName, value: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY[name], value ? "on" : "off");
  } catch {
    /* storage unavailable — the flag simply won't persist */
  }
  // Same-tab listeners: `storage` only fires in *other* tabs, so a component
  // toggling the flag would not re-render itself without this.
  window.dispatchEvent(new CustomEvent("lf-flag-change", { detail: { name, value } }));
}

export function useFlag(name: FlagName): [boolean, (value: boolean) => void] {
  const [on, setOn] = useState(() => readFlag(name));

  useEffect(() => {
    const sync = () => setOn(readFlag(name));
    window.addEventListener("lf-flag-change", sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener("lf-flag-change", sync);
      window.removeEventListener("storage", sync);
    };
  }, [name]);

  const set = useCallback((value: boolean) => writeFlag(name, value), [name]);
  return [on, set];
}
