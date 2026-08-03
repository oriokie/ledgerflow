import { describe, expect, it } from "vitest";
import { SETTINGS_NAV, SETTINGS_SLUGS } from "./nav";

describe("settings nav config", () => {
  it("groups items by who a change affects, not just by topic", () => {
    // Deliberately not flattened: the split is between settings that change
    // things for you and settings that change things for everyone in the
    // workspace. A flat list makes renaming yourself and renaming the
    // workspace look like the same kind of act.
    expect(SETTINGS_NAV.map((g) => g.label)).toEqual(["Your account", "Whole workspace"]);
    expect(SETTINGS_NAV[0].items.map((i) => i.slug)).toContain("profile");
    expect(SETTINGS_NAV[1].items.map((i) => i.slug)).toContain("taxonomy");
  });

  it("exposes a unique flat slug list", () => {
    expect(SETTINGS_SLUGS).toEqual([
      "profile",
      "security",
      "preferences",
      "workspace",
      "taxonomy",
      "intelligence",
    ]);
    expect(new Set(SETTINGS_SLUGS).size).toBe(SETTINGS_SLUGS.length);
  });
});
