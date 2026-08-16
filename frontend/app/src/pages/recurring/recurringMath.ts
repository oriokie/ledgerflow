import type { Category, RecurringTransaction } from "../../api/types";

type Freq = "daily" | "weekly" | "monthly" | "yearly";

/** Unrounded annual cost of a schedule, normalizing its frequency × interval.
 * (365-day year, 52.14 weeks.) Kept as a float so monthly/annual round once. */
function annualRaw(rec: Pick<RecurringTransaction, "amount_minor" | "frequency" | "interval">): number {
  const a = rec.amount_minor;
  const n = rec.interval || 1;
  switch (rec.frequency as Freq) {
    case "daily":
      return (a * 365) / n;
    case "weekly":
      return (a * (365 / 7)) / n;
    case "yearly":
      return a / n;
    case "monthly":
    default:
      return (a * 12) / n;
  }
}

/** Normalized cost per month (minor units) for cadences that hit a month more
 * than once. Periodical schedules use `recognizedMinor` instead. */
export function monthlyMinor(rec: Pick<RecurringTransaction, "amount_minor" | "frequency" | "interval">): number {
  return Math.round(annualRaw(rec) / 12);
}

/** True when the schedule fires at most once per calendar month. The amount
 * is the block that lands on the due date, not a monthly smear. */
export function isPeriodical(rec: Pick<RecurringTransaction, "frequency" | "interval">): boolean {
  const n = rec.interval || 1;
  if (rec.frequency === "yearly") return true;
  return rec.frequency === "monthly" && n >= 2;
}

/** Amount to show for a schedule: the block for periodical cadences, else the
 * monthly run-rate. */
export function recognizedMinor(
  rec: Pick<RecurringTransaction, "amount_minor" | "frequency" | "interval">,
): number {
  return isPeriodical(rec) ? rec.amount_minor : monthlyMinor(rec);
}

function sameCalendarMonth(isoDate: string, asOf: Date): boolean {
  const [year, month] = isoDate.split("-").map(Number);
  return year === asOf.getFullYear() && month === asOf.getMonth() + 1;
}

/** Normalized cost per year (minor units). */
export function annualMinor(rec: Pick<RecurringTransaction, "amount_minor" | "frequency" | "interval">): number {
  return Math.round(annualRaw(rec));
}

export interface RecurringTotals {
  currency: string;
  monthlyExpense: number;
  annualExpense: number;
  monthlyIncome: number;
  expenseCount: number;
}

/**
 * Roll active schedules into a monthly/annual spend picture. Money totals use
 * the most common currency (schedules can differ); expense count spans that
 * currency. Income schedules are tracked separately so the headline is "spend".
 */
export function recurringTotals(
  list: RecurringTransaction[] | undefined,
  asOf: Date = new Date(),
): RecurringTotals {
  const items = list ?? [];
  const counts = new Map<string, number>();
  for (const r of items) {
    if (r.txn_type !== "transfer") counts.set(r.currency, (counts.get(r.currency) ?? 0) + 1);
  }
  const currency = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? "USD";

  let monthlyExpense = 0;
  let annualExpense = 0;
  let monthlyIncome = 0;
  let expenseCount = 0;
  for (const r of items) {
    if (r.currency !== currency) continue;
    const thisMonth = isPeriodical(r)
      ? sameCalendarMonth(r.next_run_on, asOf)
        ? r.amount_minor
        : 0
      : monthlyMinor(r);
    if (r.txn_type === "expense") {
      monthlyExpense += thisMonth;
      annualExpense += annualMinor(r);
      expenseCount += 1;
    } else if (r.txn_type === "income") {
      monthlyIncome += thisMonth;
    }
  }
  return { currency, monthlyExpense, annualExpense, monthlyIncome, expenseCount };
}

/** Expense schedules ordered by monthly cost, biggest first — where the savings
 * are, so they lead the list. */
export function sortByMonthlyCost(list: RecurringTransaction[]): RecurringTransaction[] {
  return [...list].sort((a, b) => monthlyMinor(b) - monthlyMinor(a));
}

const UNIT: Record<Freq, string> = { daily: "day", weekly: "week", monthly: "month", yearly: "year" };

/**
 * The cadences a person actually gets billed on, as (frequency × interval).
 *
 * The server stores a base unit and a multiplier, which between them already
 * express every one of these — quarterly *is* monthly×3. So this catalogue is
 * a naming layer, not a schema change: no migration, and a schedule already
 * stored as monthly×3 starts reading "Quarterly" without being touched.
 *
 * Quarterly, four-monthly and semiannual are here because real bills use them
 * — school fees a term at a time, insurance premiums, land rates, bond coupons
 * — and without them the only way to enter one was to misstate the cadence,
 * which then misstates every annualised figure derived from it.
 *
 * "Triannual" is deliberately not used as a label: it reads as both "three
 * times a year" and "every three years". `Every 4 months` says which.
 */
export interface Cadence {
  /** Stable key for a <Select>. */
  value: string;
  label: string;
  frequency: Freq;
  interval: number;
}

export const CADENCES: readonly Cadence[] = [
  { value: "daily", label: "Daily", frequency: "daily", interval: 1 },
  { value: "weekly", label: "Weekly", frequency: "weekly", interval: 1 },
  { value: "fortnightly", label: "Every two weeks", frequency: "weekly", interval: 2 },
  { value: "monthly", label: "Monthly", frequency: "monthly", interval: 1 },
  { value: "bimonthly", label: "Every two months", frequency: "monthly", interval: 2 },
  { value: "quarterly", label: "Quarterly", frequency: "monthly", interval: 3 },
  { value: "four_monthly", label: "Every 4 months", frequency: "monthly", interval: 4 },
  { value: "semiannual", label: "Twice a year", frequency: "monthly", interval: 6 },
  { value: "yearly", label: "Yearly", frequency: "yearly", interval: 1 },
] as const;

export const CADENCE_OPTIONS = CADENCES.map((c) => ({ value: c.value, label: c.label }));

/** The catalogue entry for a stored (frequency, interval) pair, if it has a name. */
export function cadenceFor(
  rec: Pick<RecurringTransaction, "frequency" | "interval">,
): Cadence | undefined {
  const n = rec.interval || 1;
  return CADENCES.find((c) => c.frequency === rec.frequency && c.interval === n);
}

/** The catalogue entry for a <Select> value. */
export function cadenceByValue(value: string): Cadence | undefined {
  return CADENCES.find((c) => c.value === value);
}

/**
 * Human cadence label, e.g. "Monthly", "Quarterly" or "Every 5 months".
 *
 * Named cadences win; anything else falls back to counting units, so a
 * schedule stored with an interval nobody has a word for still describes
 * itself honestly rather than being rounded to the nearest named one.
 */
export function cadenceLabel(rec: Pick<RecurringTransaction, "frequency" | "interval">): string {
  const named = cadenceFor(rec);
  if (named) return named.label;
  const n = rec.interval || 1;
  return `Every ${n} ${UNIT[rec.frequency as Freq] ?? rec.frequency}s`;
}

/** Best display label for a schedule: memo, else its category, else a fallback. */
export function recurringLabel(
  rec: Pick<RecurringTransaction, "memo" | "category_id" | "txn_type">,
  categories: Category[] | undefined,
): string {
  if (rec.memo?.trim()) return rec.memo.trim();
  const cat = categories?.find((c) => c.id === rec.category_id);
  if (cat) return cat.name;
  if (rec.txn_type === "income") return "Recurring income";
  if (rec.txn_type === "transfer") return "Transfer / savings";
  return "Recurring expense";
}
