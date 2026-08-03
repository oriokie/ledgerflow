import { describe, expect, it } from "vitest";
import type { ReportResult } from "../../api/types";
import { caveatsOf, humanizeKey, isMoneyKey, numericKeys, timeKeyOf } from "./reportRenderers";

function result(meta: Record<string, unknown>): ReportResult {
  return {
    slug: "x",
    title: "X",
    currency: "USD",
    start: "2026-01-01",
    end: "2026-06-30",
    totals: {},
    series: [],
    rows: [],
    meta,
  };
}

describe("isMoneyKey", () => {
  it("recognises the minor-unit convention used across every report", () => {
    expect(isMoneyKey("amount_minor")).toBe(true);
    expect(isMoneyKey("inflow_minor")).toBe(true);
    expect(isMoneyKey("count")).toBe(false);
    expect(isMoneyKey("rate")).toBe(false);
  });
});

describe("humanizeKey", () => {
  it("derives a label from the key rather than a per-report lookup", () => {
    // One rule covers all fourteen; a new report needs no extra mapping.
    expect(humanizeKey("amount_minor")).toBe("Amount");
    expect(humanizeKey("inflow_minor")).toBe("Inflow");
    expect(humanizeKey("transaction_count")).toBe("Transaction count");
  });

  it("marks percentage fields", () => {
    expect(humanizeKey("change_pct")).toContain("%");
  });
});

describe("timeKeyOf", () => {
  it("finds whichever time field a report used", () => {
    // Reports legitimately differ by granularity, so the renderer adapts
    // rather than forcing one name.
    expect(timeKeyOf([{ month: "2026-01-01", v: 1 }])).toBe("month");
    expect(timeKeyOf([{ period: "2026-01", v: 1 }])).toBe("period");
    expect(timeKeyOf([{ occurred_on: "2026-01-01", v: 1 }])).toBe("occurred_on");
  });

  it("returns null when there is no time axis", () => {
    expect(timeKeyOf([{ label: "Groceries", amount_minor: 100 }])).toBeNull();
    expect(timeKeyOf([])).toBeNull();
  });
});

describe("numericKeys", () => {
  it("returns plottable fields only", () => {
    const rows = [{ month: "2026-01-01", inflow_minor: 100, label: "x", outflow_minor: 50 }];
    expect(numericKeys(rows, { exclude: ["month"] })).toEqual(["inflow_minor", "outflow_minor"]);
  });

  it("excludes identifiers, which are numbers in name only", () => {
    const rows = [{ category_id: 12, amount_minor: 100 }];
    expect(numericKeys(rows)).toEqual(["amount_minor"]);
  });

  it("handles an empty series", () => {
    expect(numericKeys([])).toEqual([]);
  });
});

describe("caveatsOf", () => {
  it("warns that a partial month isn't comparable", () => {
    // The most common way a report gets misread — a half-month looks like a
    // collapse in spending.
    expect(caveatsOf(result({ partial_month: true }))[0]).toMatch(/isn't over yet/i);
  });

  it("says when there isn't enough history for a trend", () => {
    expect(caveatsOf(result({ insufficient_history: true }))[0]).toMatch(/not enough history/i);
  });

  it("flags a large uncategorised share, since the split is then incomplete", () => {
    expect(caveatsOf(result({ uncategorised_share: 34 }))[0]).toMatch(/34%/);
  });

  it("stays quiet when the share is small", () => {
    expect(caveatsOf(result({ uncategorised_share: 3 }))).toEqual([]);
  });

  it("returns nothing when there is nothing to caveat", () => {
    expect(caveatsOf(result({}))).toEqual([]);
  });
});
