import { describe, expect, it } from "vitest";
import type { CategoryBreakdownRow } from "../../api/types";
import { formatDelta, greeting, percentChange, periodRange, rankedCategories, savingsRate } from "./metrics";

const NOW = new Date("2024-06-15T10:00:00.000Z");

describe("periodRange", () => {
  it("resolves this-month to the calendar month", () => {
    const r = periodRange("this-month", NOW);
    expect(r.start.slice(0, 10)).toBe("2024-06-01");
    expect(r.end.slice(0, 10)).toBe("2024-06-30");
    expect(r.label).toBe("This month");
  });

  it("resolves last-month", () => {
    const r = periodRange("last-month", NOW);
    expect(r.start.slice(0, 10)).toBe("2024-05-01");
    expect(r.end.slice(0, 10)).toBe("2024-05-31");
    expect(r.label).toBe("Last month");
  });

  it("resolves last-30d to a 30-day window ending today", () => {
    const r = periodRange("last-30d", NOW);
    expect(r.start.slice(0, 10)).toBe("2024-05-17"); // 29 days before the 15th
    expect(r.label).toBe("Last 30 days");
  });

  it("resolves ytd to Jan 1", () => {
    const r = periodRange("ytd", NOW);
    expect(r.start.slice(0, 10)).toBe("2024-01-01");
    expect(r.label).toBe("Year to date");
  });
});

describe("greeting", () => {
  it("greets by time of day", () => {
    expect(greeting(new Date("2024-01-01T09:00:00Z"))).toBe("Good morning");
    expect(greeting(new Date("2024-01-01T14:00:00Z"))).toBe("Good afternoon");
    expect(greeting(new Date("2024-01-01T20:00:00Z"))).toBe("Good evening");
    expect(greeting(new Date("2024-01-01T00:30:00Z"))).toBe("Good morning");
  });
});

describe("percentChange", () => {
  it("computes signed change", () => {
    expect(percentChange(110, 100)).toBeCloseTo(10);
    expect(percentChange(90, 100)).toBeCloseTo(-10);
  });

  it("uses the magnitude of a negative baseline", () => {
    expect(percentChange(50, -100)).toBeCloseTo(150);
  });

  it("returns null without a usable baseline", () => {
    expect(percentChange(50, 0)).toBeNull();
    expect(percentChange(50, null)).toBeNull();
    expect(percentChange(50, undefined)).toBeNull();
  });
});

describe("savingsRate", () => {
  it("computes the kept share of income", () => {
    expect(savingsRate(1000, 400)).toBeCloseTo(60);
  });

  it("goes negative when overspending", () => {
    expect(savingsRate(1000, 1200)).toBeCloseTo(-20);
  });

  it("is undefined (null) without positive income", () => {
    expect(savingsRate(0, 500)).toBeNull();
    expect(savingsRate(-5, 500)).toBeNull();
  });
});

describe("rankedCategories", () => {
  const rows: CategoryBreakdownRow[] = [
    { category_id: "a", category_name: "Groceries", amount_minor: 100 },
    { category_id: "b", category_name: "Rent", amount_minor: 300 },
    { category_id: "c", category_name: "Zero", amount_minor: 0 },
    { category_id: "d", category_name: "Weird", amount_minor: -5 },
  ];

  it("sorts high→low, drops non-positive, and computes shares", () => {
    const out = rankedCategories(rows);
    expect(out.map((r) => r.category_id)).toEqual(["b", "a"]);
    expect(out[0].share).toBeCloseTo(1); // largest fills the bar
    expect(out[1].share).toBeCloseTo(1 / 3);
    expect(out[0].pctOfTotal).toBeCloseTo(75);
    expect(out[1].pctOfTotal).toBeCloseTo(25);
    expect(out[0].colorIndex).toBe(1);
    expect(out[1].colorIndex).toBe(2);
  });

  it("handles empty and undefined input", () => {
    expect(rankedCategories([])).toEqual([]);
    expect(rankedCategories(undefined)).toEqual([]);
  });
});

describe("formatDelta", () => {
  it("prefixes a sign and one decimal", () => {
    expect(formatDelta(12.4)).toBe("+12.4%");
    expect(formatDelta(-3)).toBe("-3.0%");
    expect(formatDelta(0)).toBe("0.0%");
  });
});
