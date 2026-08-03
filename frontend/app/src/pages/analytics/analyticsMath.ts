import type { CategoryBreakdownRow, SpendingTrendPoint } from "../../api/types";

/** ISO [start, end) covering the trailing `months` calendar months incl. the
 * current one — the window for cash-flow / breakdown queries. */
export function rangeForMonths(months: number, asOf: Date = new Date()): { start: string; end: string } {
  const y = asOf.getUTCFullYear();
  const m = asOf.getUTCMonth();
  const start = new Date(Date.UTC(y, m - (months - 1), 1));
  const end = new Date(Date.UTC(y, m + 1, 1));
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return { start: iso(start), end: iso(end) };
}

export type Direction = "up" | "down" | "flat";
export interface Delta {
  abs: number;
  pct: number;
  direction: Direction;
}

/** Change from `previous` to `current`, as an absolute delta and a percentage. */
export function delta(current: number, previous: number): Delta {
  const abs = current - previous;
  const pct = previous !== 0 ? (abs / Math.abs(previous)) * 100 : current !== 0 ? 100 : 0;
  return { abs, pct, direction: abs > 0 ? "up" : abs < 0 ? "down" : "flat" };
}

/** Fraction of income kept (0–1); 0 when there's no income. */
export function savingsRate(incomeMinor: number, expenseMinor: number): number {
  if (incomeMinor <= 0) return 0;
  return (incomeMinor - expenseMinor) / incomeMinor;
}

export interface PeriodProgress {
  /** Days of the current month that have actually happened, inclusive. */
  elapsed: number;
  /** Days the month contains. */
  total: number;
  /** True while the month is still running. */
  partial: boolean;
}

/** How far through its month the latest trend point is.
 *
 * This exists because month-over-month is a lie for most of the month. On the
 * 2nd, two days of spending against a complete previous month reads as
 * "expenses down 97%" — an improvement the user did not make, rendered in the
 * colour reserved for good news. Knowing the period is partial is what lets
 * the UI decline to make that claim.
 */
export function periodProgress(periodStartIso: string, asOf: Date = new Date()): PeriodProgress {
  const start = new Date(`${periodStartIso}T00:00:00Z`);
  const y = start.getUTCFullYear();
  const m = start.getUTCMonth();
  const total = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  const sameMonth = asOf.getUTCFullYear() === y && asOf.getUTCMonth() === m;
  const elapsed = sameMonth ? asOf.getUTCDate() : total;
  return { elapsed, total, partial: sameMonth && elapsed < total };
}

export interface TrendComparison {
  current: SpendingTrendPoint;
  previous: SpendingTrendPoint;
  income: Delta;
  expense: Delta;
  net: Delta;
  savingsRateNow: number;
  savingsRatePrev: number;
  /** Progress through the current month. Deltas are not like-for-like while
   * `partial` is true. */
  progress: PeriodProgress;
}

/** Compare the latest month to the one before it (month-over-month). Null when
 * there aren't two months to compare. */
export function comparisonFromTrend(
  trend: SpendingTrendPoint[] | undefined,
  asOf: Date = new Date(),
): TrendComparison | null {
  if (!trend || trend.length < 2) return null;
  const current = trend[trend.length - 1];
  const previous = trend[trend.length - 2];
  return {
    current,
    previous,
    income: delta(current.income_minor, previous.income_minor),
    expense: delta(current.expense_minor, previous.expense_minor),
    net: delta(current.net_minor, previous.net_minor),
    savingsRateNow: savingsRate(current.income_minor, current.expense_minor),
    savingsRatePrev: savingsRate(previous.income_minor, previous.expense_minor),
    progress: periodProgress(current.period_start, asOf),
  };
}

export interface TrendTotals {
  income_minor: number;
  expense_minor: number;
  net_minor: number;
}

/** Sum a trend series over its whole range. */
export function trendTotals(trend: SpendingTrendPoint[] | undefined): TrendTotals {
  let income = 0;
  let expense = 0;
  for (const p of trend ?? []) {
    income += p.income_minor;
    expense += p.expense_minor;
  }
  return { income_minor: income, expense_minor: expense, net_minor: income - expense };
}

export type BreakdownRowWithShare = CategoryBreakdownRow & { share: number };

/** Total across all breakdown rows. */
export function breakdownTotal(rows: CategoryBreakdownRow[] | undefined): number {
  return (rows ?? []).reduce((s, r) => s + r.amount_minor, 0);
}

/** Annotate each category with its share (0–1) of the total. */
export function breakdownWithShare(rows: CategoryBreakdownRow[] | undefined): BreakdownRowWithShare[] {
  const total = breakdownTotal(rows);
  return (rows ?? []).map((r) => ({ ...r, share: total > 0 ? r.amount_minor / total : 0 }));
}

/** First `n` rows (rows arrive biggest-first from the API). */
export function topN<T>(rows: T[], n: number): T[] {
  return rows.slice(0, n);
}
