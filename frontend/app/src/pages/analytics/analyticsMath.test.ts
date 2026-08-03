import { describe, expect, it } from "vitest";
import type { CategoryBreakdownRow, SpendingTrendPoint } from "../../api/types";
import {
  breakdownTotal,
  breakdownWithShare,
  comparisonFromTrend,
  delta,
  rangeForMonths,
  savingsRate,
  topN,
  trendTotals,
} from "./analyticsMath";

const AS_OF = new Date("2026-06-15T00:00:00Z");

function point(over: Partial<SpendingTrendPoint> & { period_start: string }): SpendingTrendPoint {
  const income = over.income_minor ?? 0;
  const expense = over.expense_minor ?? 0;
  return { income_minor: income, expense_minor: expense, net_minor: income - expense, ...over };
}

describe("rangeForMonths", () => {
  it("covers the trailing N calendar months including the current one", () => {
    expect(rangeForMonths(6, AS_OF)).toEqual({ start: "2026-01-01", end: "2026-07-01" });
    expect(rangeForMonths(1, AS_OF)).toEqual({ start: "2026-06-01", end: "2026-07-01" });
    expect(rangeForMonths(12, AS_OF)).toEqual({ start: "2025-07-01", end: "2026-07-01" });
  });
});

describe("delta", () => {
  it("reports absolute change, percent, and direction", () => {
    expect(delta(120, 100)).toEqual({ abs: 20, pct: 20, direction: "up" });
    expect(delta(80, 100)).toEqual({ abs: -20, pct: -20, direction: "down" });
    expect(delta(50, 0)).toEqual({ abs: 50, pct: 100, direction: "up" });
    expect(delta(0, 0)).toEqual({ abs: 0, pct: 0, direction: "flat" });
  });
});

describe("savingsRate", () => {
  it("is the fraction of income kept, zero-safe", () => {
    expect(savingsRate(1000, 600)).toBeCloseTo(0.4, 6);
    expect(savingsRate(0, 500)).toBe(0);
  });
});

describe("comparisonFromTrend", () => {
  it("compares the last two months", () => {
    const c = comparisonFromTrend([
      point({ period_start: "2026-05-01", income_minor: 100000, expense_minor: 80000 }),
      point({ period_start: "2026-06-01", income_minor: 120000, expense_minor: 60000 }),
    ]);
    expect(c).not.toBeNull();
    expect(c!.income.direction).toBe("up");
    expect(c!.expense.direction).toBe("down");
    expect(c!.savingsRateNow).toBeCloseTo(0.5, 6); // (120-60)/120
  });

  it("returns null without two months", () => {
    expect(comparisonFromTrend([point({ period_start: "2026-06-01" })])).toBeNull();
    expect(comparisonFromTrend([])).toBeNull();
  });
});

describe("trendTotals", () => {
  it("sums income/expense/net across the range", () => {
    const t = trendTotals([
      point({ period_start: "2026-05-01", income_minor: 100, expense_minor: 40 }),
      point({ period_start: "2026-06-01", income_minor: 200, expense_minor: 60 }),
    ]);
    expect(t).toEqual({ income_minor: 300, expense_minor: 100, net_minor: 200 });
  });
});

describe("breakdown helpers", () => {
  const rows: CategoryBreakdownRow[] = [
    { category_id: "a", category_name: "Food", amount_minor: 6000 },
    { category_id: "b", category_name: "Transport", amount_minor: 4000 },
  ];
  it("totals and shares", () => {
    expect(breakdownTotal(rows)).toBe(10000);
    const withShare = breakdownWithShare(rows);
    expect(withShare[0].share).toBeCloseTo(0.6, 6);
    expect(withShare[1].share).toBeCloseTo(0.4, 6);
  });
  it("topN slices", () => {
    expect(topN(rows, 1)).toHaveLength(1);
  });
});
