import { describe, expect, it } from "vitest";
import type { CashflowCalendarDay } from "../../api/types";
import {
  dayTone,
  isSameDay,
  parseDay,
  toBalanceSeries,
  toMonthlyRollups,
  toWeekGrid,
  weekdayLabels,
} from "./calendarUtils";

function day(iso: string, closing: number, events = 0, negative = false): CashflowCalendarDay {
  return {
    day: iso,
    opening_minor: closing,
    closing_minor: closing,
    inflow_minor: 0,
    outflow_minor: 0,
    net_minor: events ? -100 : 0,
    is_negative: negative,
    expected_minor: null,
    expected_low_minor: null,
    expected_high_minor: null,
    events: Array.from({ length: events }, () => ({
      occurs_on: iso,
      amount_minor: -100,
      description: "Test",
      source: "bill" as const,
      currency: "USD",
      account_id: null,
      account_name: "",
      category_name: "",
      is_overdue: false,
      bill_id: null,
      recurring_id: null,
    })),
  };
}

describe("parseDay", () => {
  it("parses at local midnight, not UTC", () => {
    // `new Date("2026-07-25")` is UTC and lands on the 24th west of Greenwich,
    // which would shift the entire grid by one column.
    const d = parseDay("2026-07-25");
    expect(d.getFullYear()).toBe(2026);
    expect(d.getMonth()).toBe(6);
    expect(d.getDate()).toBe(25);
  });
});

describe("isSameDay", () => {
  it("compares calendar days, ignoring time", () => {
    expect(isSameDay(new Date(2026, 6, 25, 9), new Date(2026, 6, 25, 23))).toBe(true);
    expect(isSameDay(new Date(2026, 6, 25), new Date(2026, 6, 26))).toBe(false);
  });
});

describe("weekdayLabels", () => {
  it("starts on Monday", () => {
    const labels = weekdayLabels("en-GB");
    expect(labels).toHaveLength(7);
    expect(labels[0].toLowerCase()).toContain("mon");
    expect(labels[6].toLowerCase()).toContain("sun");
  });
});

describe("toWeekGrid", () => {
  it("returns nothing for an empty projection", () => {
    expect(toWeekGrid([])).toEqual([]);
  });

  it("pads to whole Monday-start weeks", () => {
    // 2026-07-25 is a Saturday: 5 leading blanks before it.
    const weeks = toWeekGrid([day("2026-07-25", 100), day("2026-07-26", 100)]);
    expect(weeks).toHaveLength(1);
    expect(weeks[0]).toHaveLength(7);
    expect(weeks[0].slice(0, 5).every((c) => c === null)).toBe(true);
    expect(weeks[0][5]?.day).toBe("2026-07-25");
    expect(weeks[0][6]?.day).toBe("2026-07-26");
  });

  it("uses null for padding rather than a fabricated day", () => {
    // A placeholder day would be indistinguishable from a real one with a
    // zero balance.
    const weeks = toWeekGrid([day("2026-07-25", 100)]);
    expect(weeks[0][0]).toBeNull();
    expect(weeks[0][6]).toBeNull();
  });

  it("spans multiple weeks and keeps every day", () => {
    const days = Array.from({ length: 30 }, (_, i) =>
      day(`2026-07-${String(i + 1).padStart(2, "0")}`, 100),
    );
    const weeks = toWeekGrid(days);
    const kept = weeks.flat().filter(Boolean);
    expect(kept).toHaveLength(30);
    expect(weeks.every((w) => w.length === 7)).toBe(true);
  });
});

describe("dayTone", () => {
  const opening = 100_000; // 1,000.00

  it("flags a projected overdraft above everything else", () => {
    // Negative outranks a busy day: it's the one thing a user must not miss.
    expect(dayTone(day("2026-07-25", -500, 3, true), opening)).toBe("negative");
  });

  it("warns while the balance is merely thin", () => {
    // Below 10% of opening. The day it gets thin is more actionable than the
    // day it goes negative — by then there's no time to move money.
    expect(dayTone(day("2026-07-25", 5_000), opening)).toBe("low");
  });

  it("distinguishes inflow from outflow days", () => {
    const inflow = { ...day("2026-07-25", 200_000, 1), net_minor: 500 };
    const outflow = { ...day("2026-07-25", 200_000, 1), net_minor: -500 };
    expect(dayTone(inflow, opening)).toBe("inflow");
    expect(dayTone(outflow, opening)).toBe("outflow");
  });

  it("leaves a day with no movement quiet", () => {
    expect(dayTone(day("2026-07-25", 200_000), opening)).toBe("quiet");
  });

  it("does not raise a low warning when there is no balance to compare against", () => {
    // A zero opening balance makes a percentage threshold meaningless; warning
    // on every day would train the user to ignore it.
    expect(dayTone(day("2026-07-25", 0), 0)).toBe("quiet");
  });
});

// ------------------------------------------------- long-horizon aggregation
describe("toMonthlyRollups", () => {
  function day(iso: string, over: Partial<CashflowCalendarDay> = {}): CashflowCalendarDay {
    return {
      day: iso,
      opening_minor: 0,
      closing_minor: 0,
      inflow_minor: 0,
      outflow_minor: 0,
      net_minor: 0,
      is_negative: false,
      expected_minor: null,
      expected_low_minor: null,
      expected_high_minor: null,
      events: [],
      ...over,
    };
  }

  it("groups days into their calendar months", () => {
    const rollups = toMonthlyRollups([
      day("2026-01-05", { inflow_minor: 100, closing_minor: 100 }),
      day("2026-01-20", { outflow_minor: 40, closing_minor: 60 }),
      day("2026-02-03", { inflow_minor: 200, closing_minor: 260 }),
    ]);
    expect(rollups).toHaveLength(2);
    expect(rollups[0].month).toBe("2026-01-01");
    expect(rollups[0].inflowMinor).toBe(100);
    expect(rollups[0].outflowMinor).toBe(40);
  });

  it("takes the closing balance from the month's last day, not its largest", () => {
    const rollups = toMonthlyRollups([
      day("2026-01-05", { closing_minor: 900 }),
      day("2026-01-31", { closing_minor: 120 }),
    ]);
    expect(rollups[0].endBalanceMinor).toBe(120);
  });

  it("keeps the trough rather than averaging it away", () => {
    const rollups = toMonthlyRollups([
      day("2026-01-05", { closing_minor: 500 }),
      day("2026-01-14", { closing_minor: -80, is_negative: true }),
      day("2026-01-28", { closing_minor: 400 }),
    ]);
    // A month that ends healthy can still have gone underwater mid-way; that
    // is exactly the fact the projection exists to surface.
    expect(rollups[0].lowestMinor).toBe(-80);
    expect(rollups[0].endBalanceMinor).toBe(400);
    expect(rollups[0].negativeDays).toBe(1);
  });

  it("returns nothing for an empty projection", () => {
    expect(toMonthlyRollups([])).toEqual([]);
  });
});

describe("toBalanceSeries", () => {
  function day(iso: string, closing: number, negative = false): CashflowCalendarDay {
    return {
      day: iso,
      opening_minor: 0,
      closing_minor: closing,
      inflow_minor: 0,
      outflow_minor: 0,
      net_minor: 0,
      is_negative: negative,
    expected_minor: null,
    expected_low_minor: null,
    expected_high_minor: null,
      events: [],
    };
  }

  const many = (n: number) =>
    Array.from({ length: n }, (_, i) =>
      day(`2026-01-${String((i % 28) + 1).padStart(2, "0")}`, 1000 - i),
    );

  it("leaves a short series untouched", () => {
    const days = many(10);
    expect(toBalanceSeries(days, 120)).toHaveLength(10);
  });

  it("thins a long series toward the point budget", () => {
    const series = toBalanceSeries(many(365), 100);
    expect(series.length).toBeLessThanOrEqual(120);
    expect(series.length).toBeGreaterThan(50);
  });

  it("never drops a negative day, however aggressive the thinning", () => {
    const days = many(365);
    days[137] = day("2026-01-15", -50, true);
    const series = toBalanceSeries(days, 20);
    // A one-day dip into overdraft is the single most important point on the
    // chart; sampling must not be able to step over it.
    expect(series.some((p) => p.isNegative && p.balanceMinor === -50)).toBe(true);
  });

  it("always keeps the final day so the line ends where the projection does", () => {
    const days = many(365);
    const series = toBalanceSeries(days, 30);
    expect(series[series.length - 1].balanceMinor).toBe(days[364].closing_minor);
  });
});
