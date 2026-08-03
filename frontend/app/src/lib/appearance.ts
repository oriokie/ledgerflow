import { useCallback, useState } from "react";

/** Appearance customization beyond light/dark: accent color and density.
 * Same architecture as useTheme — localStorage persistence, a data attribute on
 * <html> as the single source of truth, and a boot-time init so there's no
 * flash of the default look. */

export type Accent = "iris" | "verdant" | "ocean" | "plum" | "ember";
export type Density = "comfortable" | "compact";

export const ACCENTS: readonly { id: Accent; label: string; swatch: string }[] = [
  { id: "iris", label: "Iris", swatch: "#5f62dd" },
  { id: "verdant", label: "Verdant", swatch: "#0e7a5f" },
  { id: "ocean", label: "Ocean", swatch: "#0369a1" },
  { id: "plum", label: "Plum", swatch: "#8b30d9" },
  { id: "ember", label: "Ember", swatch: "#c2410c" },
] as const;

const ACCENT_KEY = "lf-accent";
const DENSITY_KEY = "lf-density";

export function readAccent(): Accent {
  try {
    const stored = localStorage.getItem(ACCENT_KEY);
    if (stored && ACCENTS.some((a) => a.id === stored)) return stored as Accent;
  } catch {
    /* storage unavailable */
  }
  return "iris";
}

export function readDensity(): Density {
  try {
    if (localStorage.getItem(DENSITY_KEY) === "compact") return "compact";
  } catch {
    /* storage unavailable */
  }
  return "comfortable";
}

export function applyAccent(accent: Accent) {
  if (accent === "iris") delete document.documentElement.dataset.accent;
  else document.documentElement.dataset.accent = accent;
}

export function applyDensity(density: Density) {
  if (density === "comfortable") delete document.documentElement.dataset.density;
  else document.documentElement.dataset.density = density;
}

/** Called once at boot (main.tsx) so the stored look applies before first paint. */
export function initAppearance() {
  applyAccent(readAccent());
  applyDensity(readDensity());
  applyFontFamily(readFontFamily());
  applyFontSize(readFontSize());
}

export function useAccent() {
  const [accent, setAccentState] = useState<Accent>(readAccent);
  const setAccent = useCallback((next: Accent) => {
    setAccentState(next);
    try {
      if (next === "iris") localStorage.removeItem(ACCENT_KEY);
      else localStorage.setItem(ACCENT_KEY, next);
    } catch {
      /* ignore */
    }
    applyAccent(next);
  }, []);
  return { accent, setAccent };
}

export function useDensity() {
  const [density, setDensityState] = useState<Density>(readDensity);
  const setDensity = useCallback((next: Density) => {
    setDensityState(next);
    try {
      if (next === "comfortable") localStorage.removeItem(DENSITY_KEY);
      else localStorage.setItem(DENSITY_KEY, next);
    } catch {
      /* ignore */
    }
    applyDensity(next);
  }, []);
  return { density, setDensity };
}

// ---------------------------------------------------------------- fonts ---

export type FontFamily = "meridian" | "system" | "serif";
export type FontSize = "small" | "default" | "large" | "xlarge";

export const FONT_FAMILIES: readonly { id: FontFamily; label: string }[] = [
  { id: "meridian", label: "Meridian" },
  { id: "system", label: "System" },
  { id: "serif", label: "Serif" },
] as const;

export const FONT_SIZES: readonly { id: FontSize; label: string }[] = [
  { id: "small", label: "S" },
  { id: "default", label: "M" },
  { id: "large", label: "L" },
  { id: "xlarge", label: "XL" },
] as const;

const FONT_KEY = "lf-font";
const FONTSIZE_KEY = "lf-fontsize";

export function readFontFamily(): FontFamily {
  try {
    const stored = localStorage.getItem(FONT_KEY);
    if (stored === "system" || stored === "serif") return stored;
  } catch {
    /* storage unavailable */
  }
  return "meridian";
}

export function readFontSize(): FontSize {
  try {
    const stored = localStorage.getItem(FONTSIZE_KEY);
    if (stored === "small" || stored === "large" || stored === "xlarge") return stored;
  } catch {
    /* storage unavailable */
  }
  return "default";
}

export function applyFontFamily(font: FontFamily) {
  if (font === "meridian") delete document.documentElement.dataset.font;
  else document.documentElement.dataset.font = font;
}

export function applyFontSize(size: FontSize) {
  if (size === "default") delete document.documentElement.dataset.fontsize;
  else document.documentElement.dataset.fontsize = size;
}

export function useFontFamily() {
  const [fontFamily, setState] = useState<FontFamily>(readFontFamily);
  const setFontFamily = useCallback((next: FontFamily) => {
    setState(next);
    try {
      if (next === "meridian") localStorage.removeItem(FONT_KEY);
      else localStorage.setItem(FONT_KEY, next);
    } catch {
      /* ignore */
    }
    applyFontFamily(next);
  }, []);
  return { fontFamily, setFontFamily };
}

export function useFontSize() {
  const [fontSize, setState] = useState<FontSize>(readFontSize);
  const setFontSize = useCallback((next: FontSize) => {
    setState(next);
    try {
      if (next === "default") localStorage.removeItem(FONTSIZE_KEY);
      else localStorage.setItem(FONTSIZE_KEY, next);
    } catch {
      /* ignore */
    }
    applyFontSize(next);
  }, []);
  return { fontSize, setFontSize };
}
