import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark" | "system";

const STORAGE_KEY = "lf-theme";

function systemPrefersDark(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}

/** Resolve the stored preference to the concrete theme to apply. */
function resolve(theme: Theme): "light" | "dark" {
  if (theme === "system") return systemPrefersDark() ? "dark" : "light";
  return theme;
}

function apply(theme: Theme) {
  const effective = resolve(theme);
  document.documentElement.dataset.theme = effective === "dark" ? "dark" : "";
}

function read(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    /* private mode / disabled storage — fall through to system */
  }
  return "system";
}

/**
 * Light/dark/system theme. Persists an explicit choice to localStorage under the
 * same `lf-theme` key the no-flash boot script in index.html reads, and follows
 * the OS when set to "system". Kept as a plain hook (not context) because the
 * document attribute is the single source of truth every component already sees.
 */
export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(read);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    try {
      if (next === "system") localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore storage failures */
    }
    apply(next);
  }, []);

  // Keep "system" in sync if the OS preference changes while the app is open.
  useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => apply("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  return { theme, resolved: resolve(theme), setTheme };
}
