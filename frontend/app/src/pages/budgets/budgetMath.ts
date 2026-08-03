import type { BudgetLineStatus, BudgetStatus } from "../../api/types";

/** A category is "warning" once it's used this share of its limit. */
export const WARNING_THRESHOLD = 85;

export type LineState = "under" | "warning" | "over";

/** Traffic-light state for a single budget line. */
export function lineState(line: BudgetLineStatus): LineState {
  if (line.over_budget) return "over";
  if (line.percent_used >= WARNING_THRESHOLD) return "warning";
  return "under";
}

export interface BudgetTotals {
  budgeted_minor: number;
  spent_minor: number;
  remaining_minor: number;
  /** 0–∞ (can exceed 100 when overspent). */
  percent: number;
}

/** Roll every line up into an overall budgeted / spent / remaining picture. */
export function budgetTotals(lines: BudgetLineStatus[] | undefined): BudgetTotals {
  let budgeted = 0;
  let spent = 0;
  for (const l of lines ?? []) {
    budgeted += l.effective_limit_minor;
    spent += l.actual_minor;
  }
  return {
    budgeted_minor: budgeted,
    spent_minor: spent,
    remaining_minor: budgeted - spent,
    percent: budgeted > 0 ? (spent / budgeted) * 100 : 0,
  };
}

const DAY_MS = 86_400_000;
const dayValue = (d: string): number => Date.parse(`${d}T00:00:00Z`);

export interface PeriodProgress {
  /** 0–1 share of the period elapsed as of the status date. */
  elapsedFraction: number;
  elapsedPercent: number;
  daysTotal: number;
  daysElapsed: number;
  daysLeft: number;
}

/** How far through the current period we are — the basis for pacing. */
export function periodProgress(status: Pick<BudgetStatus, "period_start" | "period_end" | "as_of">): PeriodProgress {
  const start = dayValue(status.period_start);
  const end = dayValue(status.period_end);
  const asOf = dayValue(status.as_of);
  const daysTotal = Math.max(0, Math.round((end - start) / DAY_MS));
  const daysElapsed = Math.min(daysTotal, Math.max(0, Math.round((asOf - start) / DAY_MS)));
  const elapsedFraction = daysTotal > 0 ? daysElapsed / daysTotal : 0;
  return {
    elapsedFraction,
    elapsedPercent: elapsedFraction * 100,
    daysTotal,
    daysElapsed,
    daysLeft: Math.max(0, daysTotal - daysElapsed),
  };
}

/** True when spending is running ahead of the clock by a meaningful margin. */
export function overPace(percentUsed: number, elapsedPercent: number, marginPoints = 5): boolean {
  return percentUsed > elapsedPercent + marginPoints;
}

/**
 * Whether the period has run long enough for pace to mean anything.
 *
 * On day 2 of a month almost every budget is trivially "on track" — you have
 * spent 3% of a limit against 6% of the clock — and the product was saying so
 * in the same words it uses on day 20, when the statement is a real finding.
 * A verdict that is true by construction teaches the reader to ignore the
 * verdict.
 *
 * Both conditions matter: the day count stops a 31-day month being judged on
 * its first weekend, and the fraction stops a 7-day budget being judged on
 * hour one. For a calendar month this makes day 4 the first day with an
 * opinion.
 */
export function paceIsMeaningful(progress: Pick<PeriodProgress, "daysElapsed" | "elapsedFraction">): boolean {
  return progress.daysElapsed >= MIN_DAYS_FOR_PACE && progress.elapsedFraction >= MIN_FRACTION_FOR_PACE;
}

export const MIN_DAYS_FOR_PACE = 3;
const MIN_FRACTION_FOR_PACE = 0.1;

/** Projected full-period spend if the current pace holds — null too early to tell. */
export function projectedSpendMinor(spentMinor: number, elapsedFraction: number): number | null {
  // Dividing by a tiny fraction turns two days of groceries into a five-figure
  // annual habit. Below the pace threshold there is no projection to make.
  if (elapsedFraction < MIN_FRACTION_FOR_PACE) return null;
  return Math.round(spentMinor / elapsedFraction);
}

const STATE_ORDER: Record<LineState, number> = { over: 0, warning: 1, under: 2 };

/** Most-at-risk first: over-budget, then near-limit, then by usage. */
export function sortLinesByRisk(lines: BudgetLineStatus[]): BudgetLineStatus[] {
  return [...lines].sort((a, b) => {
    const byState = STATE_ORDER[lineState(a)] - STATE_ORDER[lineState(b)];
    return byState !== 0 ? byState : b.percent_used - a.percent_used;
  });
}

export interface BudgetAlerts {
  over: BudgetLineStatus[];
  warning: BudgetLineStatus[];
}

/** Lines that need attention, split into over-budget and nearing-limit. */
export function budgetAlerts(lines: BudgetLineStatus[] | undefined): BudgetAlerts {
  const over: BudgetLineStatus[] = [];
  const warning: BudgetLineStatus[] = [];
  for (const l of lines ?? []) {
    const s = lineState(l);
    if (s === "over") over.push(l);
    else if (s === "warning") warning.push(l);
  }
  return { over, warning };
}
