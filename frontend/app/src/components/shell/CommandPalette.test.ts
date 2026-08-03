import { describe, expect, it } from "vitest";
import { filterCommands } from "./commands";

describe("filterCommands — ⌘K search matching", () => {
  it("returns every command for an empty query", () => {
    const all = filterCommands("");
    // 1 quick action + 13 nav destinations
    expect(all.length).toBeGreaterThanOrEqual(14);
  });

  it("matches nav destinations case-insensitively by label", () => {
    const hits = filterCommands("BUDG");
    expect(hits.some((c) => c.to === "/budgets")).toBe(true);
    expect(hits.every((c) => /budg/i.test(`${c.label} ${c.keywords ?? ""}`))).toBe(true);
  });

  it("matches quick actions via their keywords, not just the label", () => {
    // "spend" only appears in the Add-transaction action's keywords.
    const hits = filterCommands("spend");
    expect(hits).toHaveLength(1);
    expect(hits[0].to).toBe("/transactions?add=1");
  });

  it("surfaces the quick action ahead of navigation entries", () => {
    const all = filterCommands("");
    expect(all[0].id.startsWith("action-")).toBe(true);
  });

  it("returns nothing for a query with no matches", () => {
    expect(filterCommands("zzznope")).toHaveLength(0);
  });
});
