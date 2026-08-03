import { describe, expect, it } from "vitest";
import { NAV_ITEMS } from "./navConfig";
import { TAB_BAR_PATHS, tabBarItems } from "./tabBarConfig";

describe("tabBarConfig", () => {
  it("only surfaces destinations that exist in the primary nav (parity, not a fork)", () => {
    const navPaths = new Set(NAV_ITEMS.map((i) => i.to));
    for (const to of TAB_BAR_PATHS) {
      expect(navPaths.has(to)).toBe(true);
    }
  });

  it("resolves five ordered items with labels and icons", () => {
    const items = tabBarItems();
    expect(items.map((i) => i.to)).toEqual([...TAB_BAR_PATHS]);
    for (const item of items) {
      expect(item.label.length).toBeGreaterThan(0);
      expect(item.icon).toBeTruthy();
    }
  });
});
