import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Same treatment as PushToggle below: the notification matrix fetches on
// mount and needs a QueryClientProvider. These tests exercise appearance
// controls, so the section is stubbed rather than wired up.
// PreferencesPanel now carries the receipt-scanner switch, which reads the
// signed-in user. These tests exercise appearance only and render the panel
// outside an AuthProvider.
vi.mock("./AuthContext", () => ({
  useAuth: () => ({ user: { show_receipt_scanner: false }, refreshUser: vi.fn() }),
}));
vi.mock("../api/auth", () => ({ profileApi: { update: vi.fn() } }));

vi.mock("../pages/settings/NotificationPreferences", () => ({
  NotificationPreferencesSection: () => null,
}));

vi.mock("../pages/settings/PushToggle", () => ({
  PushToggle: () => null,
}));
import {
  ACCENTS,
  applyAccent,
  applyDensity,
  initAppearance,
  readAccent,
  readDensity,
} from "./appearance";

afterEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.accent;
  delete document.documentElement.dataset.density;
});

describe("appearance module", () => {
  it("offers a well-formed accent catalog with iris as default", () => {
    expect(ACCENTS.length).toBeGreaterThanOrEqual(5);
    expect(ACCENTS[0].id).toBe("iris");
    for (const a of ACCENTS) expect(a.swatch).toMatch(/^#[0-9a-f]{6}$/i);
  });

  it("applies and clears the accent attribute (iris = no attribute)", () => {
    applyAccent("plum");
    expect(document.documentElement.dataset.accent).toBe("plum");
    applyAccent("iris");
    expect(document.documentElement.dataset.accent).toBeUndefined();
  });

  it("reads persisted values and initializes both attributes at boot", () => {
    localStorage.setItem("lf-accent", "ocean");
    localStorage.setItem("lf-density", "compact");
    expect(readAccent()).toBe("ocean");
    expect(readDensity()).toBe("compact");
    initAppearance();
    expect(document.documentElement.dataset.accent).toBe("ocean");
    expect(document.documentElement.dataset.density).toBe("compact");
  });

  it("falls back to defaults for unknown stored values", () => {
    localStorage.setItem("lf-accent", "neon-zebra");
    expect(readAccent()).toBe("iris");
    applyDensity("comfortable");
    expect(document.documentElement.dataset.density).toBeUndefined();
  });
});

describe("PreferencesPanel appearance controls", () => {
  it("selects an accent and a density, persisting both", async () => {
    // useTheme's system-sync effect needs matchMedia, which jsdom lacks.
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    })) as unknown as typeof window.matchMedia;

    const { PreferencesPanel } = await import("../pages/settings/panels/PreferencesPanel");
    render(<PreferencesPanel />);

    const plum = screen.getByRole("radio", { name: "Plum" });
    fireEvent.click(plum);
    expect(plum).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement.dataset.accent).toBe("plum");
    expect(localStorage.getItem("lf-accent")).toBe("plum");

    fireEvent.click(screen.getByRole("radio", { name: "Compact" }));
    expect(document.documentElement.dataset.density).toBe("compact");
    expect(localStorage.getItem("lf-density")).toBe("compact");
  });
});

describe("font customization", () => {
  afterEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.font;
    delete document.documentElement.dataset.fontsize;
  });

  it("applies and clears font attributes (meridian/default = none)", async () => {
    const { applyFontFamily, applyFontSize, initAppearance } = await import("./appearance");
    applyFontFamily("serif");
    applyFontSize("large");
    expect(document.documentElement.dataset.font).toBe("serif");
    expect(document.documentElement.dataset.fontsize).toBe("large");
    applyFontFamily("meridian");
    applyFontSize("default");
    expect(document.documentElement.dataset.font).toBeUndefined();
    expect(document.documentElement.dataset.fontsize).toBeUndefined();

    localStorage.setItem("lf-font", "system");
    localStorage.setItem("lf-fontsize", "xlarge");
    initAppearance();
    expect(document.documentElement.dataset.font).toBe("system");
    expect(document.documentElement.dataset.fontsize).toBe("xlarge");
  });

  it("selects font family and size from the Preferences panel", async () => {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    })) as unknown as typeof window.matchMedia;
    const { PreferencesPanel } = await import("../pages/settings/panels/PreferencesPanel");
    render(<PreferencesPanel />);

    fireEvent.click(screen.getByRole("radio", { name: "Serif" }));
    expect(document.documentElement.dataset.font).toBe("serif");
    expect(localStorage.getItem("lf-font")).toBe("serif");

    fireEvent.click(screen.getByRole("radio", { name: "XL" }));
    expect(document.documentElement.dataset.fontsize).toBe("xlarge");
    expect(localStorage.getItem("lf-fontsize")).toBe("xlarge");
  });
});
