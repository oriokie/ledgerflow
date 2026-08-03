import { afterEach, describe, expect, it } from "vitest";
import { filterCommands, parseQuery, rankByUse, recordCommandUse } from "./commands";
import { writeFlag } from "../../lib/featureFlags";

afterEach(() => localStorage.clear());

describe("command palette under the new IA", () => {
  it("still finds the destinations that became tabs", () => {
    // The one real cost of 21 destinations → 8: "bills" is no longer a place.
    // If the palette stopped matching it, the IA change would have taken
    // something away from every keyboard user.
    writeFlag("navV2", true);
    const hits = filterCommands("bills").map((c) => c.to);
    expect(hits).toContain("/plan?tab=bills");
  });

  it("routes the old vocabulary to the new home", () => {
    writeFlag("navV2", true);
    expect(filterCommands("analytics").map((c) => c.to)).toContain("/insights?tab=trends");
    expect(filterCommands("coach").map((c) => c.to)).toContain("/insights?tab=coach");
    expect(filterCommands("recurring").map((c) => c.to)).toContain("/plan?tab=recurring");
  });

  it("offers the old destinations when the flag is off", () => {
    writeFlag("navV2", false);
    const hits = filterCommands("bills").map((c) => c.to);
    expect(hits).toContain("/bills");
    expect(hits).not.toContain("/plan?tab=bills");
  });

  it("does not offer retired top-level paths as destinations under the new IA", () => {
    writeFlag("navV2", true);
    const all = filterCommands("").map((c) => c.to);
    expect(all).not.toContain("/transactions");
    expect(all).toContain("/activity");
  });
});

describe("query sigils", () => {
  it("reads a leading > as 'actions only'", () => {
    expect(parseQuery(">add")).toEqual({ sigil: ">", text: "add" });
    expect(parseQuery("  > add bill ")).toEqual({ sigil: ">", text: "add bill" });
    expect(parseQuery("bills")).toEqual({ sigil: null, text: "bills" });
  });

  it("restricts results to verbs", () => {
    writeFlag("navV2", true);
    const results = filterCommands(">");
    expect(results.length).toBeGreaterThan(0);
    expect(results.every((c) => c.group === "Actions")).toBe(true);
    // "Bills" the destination must not appear; "Add a bill" the verb must.
    const withText = filterCommands(">bill").map((c) => c.label);
    expect(withText).toContain("Add a bill");
    expect(withText).not.toContain("Bills");
  });
});

describe("record sigils", () => {
  it("reads @ and # as 'records, not destinations'", () => {
    expect(parseQuery("@chase")).toEqual({ sigil: "@", text: "chase" });
    expect(parseQuery("#groceries")).toEqual({ sigil: "#", text: "groceries" });
    // A record sigil means the command list has nothing to offer.
    expect(filterCommands("@chase")).toEqual([]);
    expect(filterCommands("#groceries")).toEqual([]);
  });

  it("turns $ into a real amount range", () => {
    // The filter has to run on the server against the whole ledger. A
    // client-side version would filter the page that happened to be loaded and
    // quietly answer a different question.
    expect(parseQuery("$>500").amount).toEqual({ min: 50_000 });
    expect(parseQuery("$<20").amount).toEqual({ max: 2_000 });
    expect(parseQuery("$100-250").amount).toEqual({ min: 10_000, max: 25_000 });
  });

  it("reads a bare amount as 'about', not 'exactly'", () => {
    // An exact-cent match almost never finds anything; the intent is a lookup.
    expect(parseQuery("$120").amount).toEqual({ min: 10_800, max: 13_200 });
  });

  it("does not invent a range from nonsense", () => {
    expect(parseQuery("$abc").amount).toBeUndefined();
    expect(parseQuery("$").amount).toBeUndefined();
  });
});

describe("recent and frequent", () => {
  it("leaves an unused palette in its authored order", () => {
    localStorage.clear();
    const cmds = [
      { id: "a", label: "A", to: "/a" },
      { id: "b", label: "B", to: "/b" },
    ];
    expect(rankByUse(cmds).map((c) => c.id)).toEqual(["a", "b"]);
  });

  it("floats what the user actually opens", () => {
    localStorage.clear();
    const cmds = [
      { id: "a", label: "A", to: "/a" },
      { id: "b", label: "B", to: "/b" },
    ];
    recordCommandUse("b");
    recordCommandUse("b");
    expect(rankByUse(cmds).map((c) => c.id)).toEqual(["b", "a"]);
  });

  it("lets an old habit fade rather than calcify", () => {
    localStorage.clear();
    // 20 uses, but a year ago; against 2 uses today. A raw count would keep
    // the stale one on top forever.
    const yearAgo = Date.now() - 365 * 86_400_000;
    localStorage.setItem(
      "lf-command-use",
      JSON.stringify({ old: { count: 20, last: yearAgo }, fresh: { count: 2, last: Date.now() } }),
    );
    const cmds = [
      { id: "old", label: "Old", to: "/old" },
      { id: "fresh", label: "Fresh", to: "/fresh" },
    ];
    expect(rankByUse(cmds).map((c) => c.id)).toEqual(["fresh", "old"]);
  });
});
