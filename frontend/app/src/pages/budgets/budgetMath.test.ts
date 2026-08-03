import { describe, expect, it } from "vitest";
import type { BudgetLineStatus } from "../../api/types";
import {
  budgetAlerts,
  budgetTotals,
  lineState,
  overPace,
  periodProgress,
  paceIsMeaningful,
  projectedSpendMinor,
  sortLinesByRisk,
} from "./budgetMath";

function line(over: Partial<BudgetLineStatus> = {}): BudgetLineStatus {
  const limit = over.effective_limit_minor ?? 10000;
  const actual = over.actual_minor ?? 0;
  return {
    line_id: Math.random().toString(36).slice(2),
    category_id: "c",
    category_name: "Category",
    limit_minor: limit,
    carried_minor: 0,
    effective_limit_minor: limit,
    actual_minor: actual,
    remaining_minor: limit - actual,
    percent_used: limit ? Math.round((actual / limit) * 1000) / 10 : 0,
    over_budget: actual > limit,
    ...over,
  };
}

describe("lineState", () => {
  it("classifies under / warning / over", () => {
    expect(lineState(line({ actual_minor: 5000 }))).toBe("under"); // 50%
    expect(lineState(line({ actual_minor: 9000 }))).toBe("warning"); // 90%
    expect(lineState(line({ actual_minor: 12000 }))).toBe("over"); // 120%
  });
});

describe("budgetTotals", () => {
  it("sums limits and spend into an overall picture", () => {
    const t = budgetTotals([
      line({ effective_limit_minor: 10000, actual_minor: 4000 }),
      line({ effective_limit_minor: 20000, actual_minor: 5000 }),
    ]);
    expect(t.budgeted_minor).toBe(30000);
    expect(t.spent_minor).toBe(9000);
    expect(t.remaining_minor).toBe(21000);
    expect(t.percent).toBeCloseTo(30, 5);
  });

  it("is zero-safe with no lines", () => {
    expect(budgetTotals([])).toEqual({ budgeted_minor: 0, spent_minor: 0, remaining_minor: 0, percent: 0 });
  });
});

describe("periodProgress", () => {
  it("computes elapsed days and fraction from the window", () => {
    const p = periodProgress({ period_start: "2026-01-01", period_end: "2026-02-01", as_of: "2026-01-16" });
    expect(p.daysTotal).toBe(31);
    expect(p.daysElapsed).toBe(15);
    expect(p.daysLeft).toBe(16);
    expect(p.elapsedPercent).toBeCloseTo((15 / 31) * 100, 4);
  });

  it("clamps to the period bounds", () => {
    const p = periodProgress({ period_start: "2026-01-01", period_end: "2026-02-01", as_of: "2026-03-01" });
    expect(p.daysElapsed).toBe(31);
    expect(p.daysLeft).toBe(0);
    expect(p.elapsedFraction).toBe(1);
  });
});

describe("overPace / projectedSpendMinor", () => {
  it("flags spending running ahead of the clock", () => {
    expect(overPace(60, 48)).toBe(true);
    expect(overPace(50, 48)).toBe(false); // within the 5-point margin
  });

  it("projects full-period spend from the current pace", () => {
    expect(projectedSpendMinor(5000, 0.5)).toBe(10000);
    expect(projectedSpendMinor(5000, 0)).toBeNull();
  });

  it("refuses to project from a sliver of the period", () => {
    // Two days of a 31-day month is 6.5% elapsed. Dividing by that turns a
    // single grocery run into a five-figure monthly habit, which is how a
    // budget screen ends up shouting about nothing.
    expect(projectedSpendMinor(8126, 2 / 31)).toBeNull();
    expect(projectedSpendMinor(8126, 4 / 31)).not.toBeNull();
  });
});

describe("paceIsMeaningful", () => {
  const monthly = (day: number) => ({ daysElapsed: day, elapsedFraction: day / 31 });

  it("withholds a verdict for the first three days of a month", () => {
    // Every budget is trivially "on track" on day 2 — the statement is true by
    // construction, and saying it in the same words used on day 20 teaches the
    // reader to ignore the verdict when it finally carries information.
    expect(paceIsMeaningful(monthly(1))).toBe(false);
    expect(paceIsMeaningful(monthly(2))).toBe(false);
    expect(paceIsMeaningful(monthly(3))).toBe(false);
    expect(paceIsMeaningful(monthly(4))).toBe(true);
  });

  it("also withholds it early in a short period", () => {
    // The day threshold alone would judge a 7-day budget on day 3 (43%
    // elapsed, fine) but a 365-day one on day 3 too (0.8% elapsed, absurd).
    // The fraction is what stops the second case.
    expect(paceIsMeaningful({ daysElapsed: 3, elapsedFraction: 3 / 7 })).toBe(true);
    expect(paceIsMeaningful({ daysElapsed: 3, elapsedFraction: 3 / 365 })).toBe(false);
  });

  it("stays false for a period that has not started", () => {
    expect(paceIsMeaningful({ daysElapsed: 0, elapsedFraction: 0 })).toBe(false);
  });
});

describe("sortLinesByRisk", () => {
  it("orders over, then warning, then by usage", () => {
    const under = line({ actual_minor: 3000 }); // 30%
    const warn = line({ actual_minor: 9000 }); // 90%
    const over = line({ actual_minor: 15000 }); // 150%
    const sorted = sortLinesByRisk([under, warn, over]);
    expect(sorted.map((l) => lineState(l))).toEqual(["over", "warning", "under"]);
  });
});

describe("budgetAlerts", () => {
  it("partitions lines needing attention", () => {
    const { over, warning } = budgetAlerts([
      line({ actual_minor: 1000 }),
      line({ actual_minor: 9500 }),
      line({ actual_minor: 13000 }),
    ]);
    expect(over).toHaveLength(1);
    expect(warning).toHaveLength(1);
  });
});
