import { describe, expect, it } from "vitest";
import { filterCommands, groupCommands, QUICK_ACTIONS } from "./commands";

describe("command palette quick actions", () => {
  it("covers the verbs the palette promises: transaction, account, transfer, budget, goal, bill, import", () => {
    const ids = QUICK_ACTIONS.map((c) => c.id);
    expect(ids).toEqual(
      expect.arrayContaining([
        "action-add-transaction",
        "action-new-account",
        "action-transfer",
        "action-create-budget",
        "action-create-goal",
        "action-add-bill",
        "action-import",
      ]),
    );
  });

  it("routes every quick action to a destination that opens its surface", () => {
    // A quick action that only navigates is a broken promise — each one has to
    // carry the flag the destination page reads to open its create surface.
    for (const action of QUICK_ACTIONS) {
      expect(action.to).toMatch(/[?&](add|import)=1/);
    }
  });

  it("matches synonyms users actually type, not just our vocabulary", () => {
    expect(filterCommands("csv").some((c) => c.id === "action-import")).toBe(true);
    expect(filterCommands("move").some((c) => c.id === "action-transfer")).toBe(true);
  });
});

describe("groupCommands", () => {
  it("puts actions before navigation", () => {
    const groups = groupCommands(filterCommands(""));
    expect(groups[0].group).toBe("Actions");
    expect(groups[1].group).toBe("Go to");
  });

  it("drops empty groups rather than rendering a bare heading", () => {
    // "workspace" matches no quick action, so only the nav group survives.
    const groups = groupCommands(filterCommands("members"));
    expect(groups.every((g) => g.items.length > 0)).toBe(true);
    expect(groups.map((g) => g.group)).not.toContain("Actions");
  });

  it("preserves every command across grouping", () => {
    const flat = filterCommands("");
    const regrouped = groupCommands(flat).flatMap((g) => g.items);
    expect(regrouped).toHaveLength(flat.length);
  });
});
