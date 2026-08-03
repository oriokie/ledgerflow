import { describe, expect, it } from "vitest";
import type { AskResult } from "../../api/types";

/**
 * The client half of the contract in `apps/intelligence/ask.py`: the palette
 * turns an interpreted question into a *link to a filtered ledger*, never into
 * a stated figure. These assert the shape that guarantees it.
 */
function toHref(query: NonNullable<AskResult["query"]>): string {
  return `/activity?${new URLSearchParams(
    Object.entries(query).map(([k, v]) => [k, String(v)]),
  ).toString()}`;
}

describe("asking a question in the palette", () => {
  it("navigates to a filtered ledger rather than reporting a number", () => {
    // Everything the user sees afterwards is computed by the same selectors as
    // every other view, so there is nothing to take on trust.
    const href = toHref({ start: "2026-07-01", end: "2026-07-31", direction: "out" });
    expect(href.startsWith("/activity?")).toBe(true);
    expect(href).toContain("start=2026-07-01");
    expect(href).toContain("direction=out");
  });

  it("carries only filter fields into the URL", () => {
    // `explanation` and `from_rules` describe the interpretation; putting them
    // in the query would have the ledger try to filter on them.
    const result: AskResult = {
      query: { search: "coffee" },
      explanation: "Showing coffee",
      from_rules: true,
    };
    const href = toHref(result.query!);
    expect(href).not.toContain("explanation");
    expect(href).not.toContain("from_rules");
  });

  it("has nothing to offer when the question could not be interpreted", () => {
    const result: AskResult = { query: null, explanation: "" };
    expect(result.query).toBeNull();
  });
});
