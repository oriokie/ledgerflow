import {
  addDays,
  differenceInCalendarDays,
  endOfDay,
  endOfMonth,
  startOfMonth,
  startOfYear,
  subDays,
  subMonths,
} from "date-fns";
import type { CategoryBreakdownRow } from "../../api/types";

export type PeriodKey = "this-month" | "last-month" | "last-30d" | "ytd";

export interface PeriodRange {
  start: string;
  end: string;
  label: string;
}

/** Resolve a period key to an inclusive ISO date range plus a human label. */
export function periodRange(period: PeriodKey, now: Date = new Date()): PeriodRange {
  switch (period) {
    case "last-month": {
      const ref = subMonths(now, 1);
      return { start: startOfMonth(ref).toISOString(), end: endOfMonth(ref).toISOString(), label: "Last month" };
    }
    case "last-30d":
      return { start: startOfDayIso(subDays(now, 29)), end: endOfDay(now).toISOString(), label: "Last 30 days" };
    case "ytd":
      return { start: startOfYear(now).toISOString(), end: endOfDay(now).toISOString(), label: "Year to date" };
    case "this-month":
    default:
      return {
        start: startOfMonth(now).toISOString(),
        end: endOfDay(now).toISOString(),
        label: "This month so far",
      };
  }
}

/**
 * The comparable prior window for a dashboard period.
 *
 * This month is compared to the same number of days last month, not to last
 * month in full — a 10-day June against a 31-day May would always look like a
 * collapse. Last-30-days compares to the 30 days immediately before. Full
 * calendar periods (last month, year to date) have no honest sibling here.
 */
export function comparisonRange(period: PeriodKey, now: Date = new Date()): PeriodRange | null {
  switch (period) {
    case "this-month": {
      const daysElapsed = differenceInCalendarDays(now, startOfMonth(now)) + 1;
      const ref = subMonths(now, 1);
      const start = startOfMonth(ref);
      const lastMonthLength = differenceInCalendarDays(endOfMonth(ref), start) + 1;
      const n = Math.min(daysElapsed, lastMonthLength);
      return {
        start: start.toISOString(),
        end: endOfDay(addDays(start, n - 1)).toISOString(),
        label: `Same ${n} days last month`,
      };
    }
    case "last-30d":
      return {
        start: startOfDayIso(subDays(now, 59)),
        end: endOfDay(subDays(now, 30)).toISOString(),
        label: "Previous 30 days",
      };
    default:
      return null;
  }
}

function startOfDayIso(d: Date): string {
  const c = new Date(d);
  c.setHours(0, 0, 0, 0);
  return c.toISOString();
}

/** Time-of-day greeting. Pure over the supplied date so it's testable. */
export function greeting(date: Date = new Date()): string {
  const h = date.getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

/**
 * Signed percentage change from `previous` to `current`. Returns null when there
 * is no meaningful baseline (missing or zero previous), so callers can hide the
 * delta rather than render a divide-by-zero artifact.
 */
export function percentChange(current: number, previous: number | null | undefined): number | null {
  if (previous == null || previous === 0) return null;
  return ((current - previous) / Math.abs(previous)) * 100;
}

/**
 * Savings rate for a period: share of income kept. Null when income is zero or
 * negative (rate is undefined). Can be negative when spending exceeds income.
 */
export function savingsRate(incomeMinor: number, expenseMinor: number): number | null {
  if (incomeMinor <= 0) return null;
  return ((incomeMinor - expenseMinor) / incomeMinor) * 100;
}

export interface RankedCategory extends CategoryBreakdownRow {
  /** 0..1 relative to the largest category — drives bar width for readability. */
  share: number;
  /** 0..100 share of total spend — shown as the label. */
  pctOfTotal: number;
  /** Stable palette index (chart-1..5, cycling). */
  colorIndex: number;
}

/**
 * Sort spend categories high→low and annotate each with a bar `share` (relative
 * to the top category) and `pctOfTotal`. Non-positive amounts are dropped.
 */
export function rankedCategories(rows: CategoryBreakdownRow[] | undefined): RankedCategory[] {
  const positive = (rows ?? []).filter((r) => r.amount_minor > 0);
  if (positive.length === 0) return [];
  const sorted = positive.slice().sort((a, b) => b.amount_minor - a.amount_minor);
  const max = sorted[0].amount_minor;
  const total = sorted.reduce((sum, r) => sum + r.amount_minor, 0);
  return sorted.map((r, i) => ({
    ...r,
    share: max > 0 ? r.amount_minor / max : 0,
    pctOfTotal: total > 0 ? (r.amount_minor / total) * 100 : 0,
    colorIndex: (i % 5) + 1,
  }));
}

/** Format a signed percentage compactly, e.g. 12.4 → "+12.4%", -3 → "-3.0%". */
export function formatDelta(pct: number): string {
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}
