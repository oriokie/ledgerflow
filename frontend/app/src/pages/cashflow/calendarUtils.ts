import {
  ArrowDownLeft,
  ArrowUpRight,
  Banknote,
  CreditCard,
  Receipt,
  Repeat,
  type LucideIcon,
} from "lucide-react";
import type { CashflowCalendar, CashflowCalendarDay, CashflowEventSource } from "../../api/types";

export type CalendarView = "month" | "week" | "timeline";

/** Icons per movement source. Icon carries the *kind*, colour carries the
 * direction — so the two channels never encode the same thing twice. */
export const SOURCE_ICONS: Record<CashflowEventSource, LucideIcon> = {
  salary: Banknote,
  income: ArrowDownLeft,
  bill: Receipt,
  subscription: Repeat,
  recurring_expense: CreditCard,
  transfer_in: ArrowDownLeft,
  transfer_out: ArrowUpRight,
};

export const SOURCE_LABELS: Record<CashflowEventSource, string> = {
  salary: "Salary",
  income: "Income",
  bill: "Bill",
  subscription: "Subscription",
  recurring_expense: "Recurring",
  transfer_in: "Transfer in",
  transfer_out: "Transfer out",
};

/**
 * Severity of a projected day, driving its background tint.
 *
 * `negative` outranks everything: a predicted overdraft is the one thing on
 * this calendar a user must not miss. `low` is a deliberate early warning —
 * the day the balance gets thin is more actionable than the day it goes
 * negative, because by then it's too late to move money.
 */
export type DayTone = "negative" | "low" | "inflow" | "outflow" | "quiet";

/** Balance below this is "getting thin". A proportion of the window's opening
 * balance rather than a fixed figure, so it means the same to someone holding
 * £500 as to someone holding £50,000. */
const LOW_BALANCE_FRACTION = 0.1;

export function dayTone(day: CashflowCalendarDay, openingBalanceMinor: number): DayTone {
  if (day.is_negative) return "negative";
  const threshold = Math.max(0, openingBalanceMinor * LOW_BALANCE_FRACTION);
  if (threshold > 0 && day.closing_minor < threshold) return "low";
  if (!day.events.length) return "quiet";
  return day.net_minor >= 0 ? "inflow" : "outflow";
}

/** Local-midnight Date from an ISO day string.
 *
 * `new Date("2026-07-25")` parses as UTC and can land on the previous day west
 * of Greenwich — which would shift the whole grid by one column. */
export function parseDay(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/** Day, month and year — first-negative dates must name the year so a
 * twelve-month window does not look like it overdrafts "on 12 Mar" forever. */
export function formatFullDate(iso: string, locale?: string): string {
  return parseDay(iso).toLocaleDateString(locale, { day: "numeric", month: "short", year: "numeric" });
}

export function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
  );
}

/** Weekday initials starting Monday, localised. */
export function weekdayLabels(locale?: string): string[] {
  // 2024-01-01 was a Monday.
  return Array.from({ length: 7 }, (_, i) =>
    new Date(2024, 0, 1 + i).toLocaleDateString(locale, { weekday: "short" }),
  );
}

/**
 * Pads a run of days into whole Monday-start weeks.
 *
 * Returns `null` for the leading and trailing blanks rather than inventing
 * placeholder days — a blank cell must not be mistakable for a day with a zero
 * balance.
 */
export function toWeekGrid(days: CashflowCalendarDay[]): (CashflowCalendarDay | null)[][] {
  if (days.length === 0) return [];
  const first = parseDay(days[0].day);
  // getDay(): 0 = Sunday. Convert to a Monday-start offset.
  const leading = (first.getDay() + 6) % 7;

  const cells: (CashflowCalendarDay | null)[] = [
    ...Array.from({ length: leading }, () => null),
    ...days,
  ];
  while (cells.length % 7 !== 0) cells.push(null);

  const weeks: (CashflowCalendarDay | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

/**
 * Month heading to draw above a week row, or `null` to draw nothing.
 *
 * A multi-month window (60/90 day) renders as one continuous run of weeks
 * with nothing but weekday initials at the top — there is no visual answer
 * to "where does August end and September begin?" in a view literally
 * labelled "Month". A week earns a heading whenever it carries a month the
 * previous week didn't: either because it opens on a fresh month, or
 * because the month turns over partway through it (a week can never span
 * more than two months, so there is at most one new one per row). The
 * heading always names that *new* month — the one the reader doesn't have a
 * label for yet — even when the row's earlier days still belong to the old
 * one.
 */
export function monthHeadingForWeek(
  week: (CashflowCalendarDay | null)[],
  previousWeek: (CashflowCalendarDay | null)[] | undefined,
  locale?: string,
): string | null {
  const lastMonthOf = (w: (CashflowCalendarDay | null)[] | undefined): string | null => {
    const days = (w ?? []).filter((d): d is CashflowCalendarDay => d !== null);
    return days.length ? days[days.length - 1].day.slice(0, 7) : null;
  };

  const newestMonth = lastMonthOf(week);
  if (!newestMonth || newestMonth === lastMonthOf(previousWeek)) return null;
  return parseDay(`${newestMonth}-01`).toLocaleDateString(locale, { month: "long", year: "numeric" });
}

// --------------------------------------------------------------- long horizons
/** A month's worth of projected activity, rolled up from daily cells. */
export interface MonthlyRollup {
  /** First day of the month, ISO. */
  month: string;
  label: string;
  inflowMinor: number;
  outflowMinor: number;
  netMinor: number;
  /** Closing balance on the last projected day of this month. */
  endBalanceMinor: number;
  /** The month's trough — the figure that says whether it was survivable. */
  lowestMinor: number;
  negativeDays: number;
}

/**
 * Collapse daily projections into months.
 *
 * A day grid stops being readable somewhere past a quarter: twelve months of
 * cells is 365 numbers, which is data rather than an answer. The month is the
 * unit people actually plan in, so the long-horizon view aggregates to it and
 * keeps the trough — averaging that away would hide the exact thing the
 * projection exists to warn about.
 */
export function toMonthlyRollups(
  days: CashflowCalendarDay[],
  locale?: string,
): MonthlyRollup[] {
  const byMonth = new Map<string, MonthlyRollup>();

  for (const day of days) {
    // Slice rather than parse: the API sends plain ISO dates, and going via
    // Date here would re-introduce the timezone shifts parseDay exists to avoid.
    const month = `${day.day.slice(0, 7)}-01`;
    let bucket = byMonth.get(month);
    if (!bucket) {
      bucket = {
        month,
        label: parseDay(month).toLocaleDateString(locale, { month: "short", year: "numeric" }),
        inflowMinor: 0,
        outflowMinor: 0,
        netMinor: 0,
        endBalanceMinor: day.closing_minor,
        lowestMinor: day.closing_minor,
        negativeDays: 0,
      };
      byMonth.set(month, bucket);
    }
    bucket.inflowMinor += day.inflow_minor;
    bucket.outflowMinor += day.outflow_minor;
    bucket.netMinor += day.net_minor;
    // Days arrive in order, so the last one seen is the month's close.
    bucket.endBalanceMinor = day.closing_minor;
    bucket.lowestMinor = Math.min(bucket.lowestMinor, day.closing_minor);
    if (day.is_negative) bucket.negativeDays += 1;
  }

  return [...byMonth.values()];
}

/** Points for the projected-balance line. */
export interface BalancePoint {
  day: string;
  balanceMinor: number;
  isNegative: boolean;
}

/**
 * Thin a daily series down to something a chart can draw legibly.
 *
 * Plotting 365 points into a few hundred pixels wastes most of them, but naive
 * sampling can step straight over a one-day dip into overdraft. So every
 * negative day is kept regardless of the stride: the whole point of the chart
 * is spotting those.
 */
export function toBalanceSeries(days: CashflowCalendarDay[], maxPoints = 120): BalancePoint[] {
  const stride = Math.max(1, Math.ceil(days.length / maxPoints));
  const out: BalancePoint[] = [];
  days.forEach((day, i) => {
    const keep = i % stride === 0 || i === days.length - 1 || day.is_negative;
    if (keep) {
      out.push({ day: day.day, balanceMinor: day.closing_minor, isNegative: day.is_negative });
    }
  });
  return out;
}

/**
 * Whether this projection has anything to project.
 *
 * A calendar of 60 identical cells is not a forecast, it is the absence of
 * one. With no bills and no recurring income the balance line is flat, so the
 * grid rendered the same figure sixty times over — alongside a summary stating
 * that same figure four more ways. The user's actual situation ("nothing is
 * scheduled, so I cannot tell you what happens next") was the one thing the
 * screen never said.
 *
 * A day counts as activity if it moves the balance or carries an event, so a
 * projection that is flat only because inflow exactly cancels outflow still
 * renders — that is a real, informative flatness.
 */
export function hasScheduledActivity(days: CashflowCalendarDay[] | undefined): boolean {
  return (days ?? []).some((d) => d.events.length > 0 || d.net_minor !== 0);
}

/**
 * Apply a persistent monthly income/spend change to every projected day.
 *
 * Matches `apps.analytics.scenarios._cashflow_leg`: the drip accumulates, so
 * day *n* carries n days of the change. The outlook table, chart and hero
 * figures all read this result — a what-if that only moved a comparison box
 * was not a what-if the person could see.
 */
export function applyScenarioOverlay(
  calendar: CashflowCalendar,
  monthlyIncomeDeltaMinor: number,
  monthlyExpenseDeltaMinor: number,
): CashflowCalendar {
  const netMonthly = monthlyIncomeDeltaMinor - monthlyExpenseDeltaMinor;
  if (netMonthly === 0) return calendar;

  const daily = (netMonthly * 12) / 365;
  let lowest = Number.POSITIVE_INFINITY;
  let lowestOn: string | null = null;
  let firstNegative: string | null = null;
  let negativeCount = 0;

  const days = calendar.days.map((day, index) => {
    const n = index + 1;
    const prevAdj = Math.round(daily * (n - 1));
    const adj = Math.round(daily * n);
    const step = adj - prevAdj;
    const closing = day.closing_minor + adj;
    const opening = index === 0 ? day.opening_minor : day.opening_minor + prevAdj;
    const inflow = day.inflow_minor + Math.max(0, step);
    const outflow = day.outflow_minor + Math.max(0, -step);
    const isNegative = closing < 0;
    if (closing < lowest) {
      lowest = closing;
      lowestOn = day.day;
    }
    if (isNegative) {
      negativeCount += 1;
      if (firstNegative === null) firstNegative = day.day;
    }
    return {
      ...day,
      opening_minor: opening,
      closing_minor: closing,
      inflow_minor: inflow,
      outflow_minor: outflow,
      net_minor: day.net_minor + step,
      is_negative: isNegative,
      expected_minor: day.expected_minor === null ? null : day.expected_minor + adj,
      expected_low_minor: day.expected_low_minor === null ? null : day.expected_low_minor + adj,
      expected_high_minor: day.expected_high_minor === null ? null : day.expected_high_minor + adj,
    };
  });

  const last = days[days.length - 1];
  return {
    ...calendar,
    days,
    closing_balance_minor: last ? last.closing_minor : calendar.closing_balance_minor,
    lowest_balance_minor: days.length ? lowest : calendar.lowest_balance_minor,
    lowest_balance_on: lowestOn,
    first_negative_on: firstNegative,
    negative_day_count: negativeCount,
    safe_to_spend_minor: days.length ? Math.max(0, lowest) : calendar.safe_to_spend_minor,
  };
}
