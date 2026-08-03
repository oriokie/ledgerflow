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

/** Normalized cost per month (minor units). */
export function monthlyMinor(rec: Pick<RecurringTransaction, "amount_minor" | "frequency" | "interval">): number {
  return Math.round(annualRaw(rec) / 12);
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
export function recurringTotals(list: RecurringTransaction[] | undefined): RecurringTotals {
  const items = list ?? [];
  const counts = new Map<string, number>();
  for (const r of items) counts.set(r.currency, (counts.get(r.currency) ?? 0) + 1);
  const currency = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? "USD";

  let monthlyExpense = 0;
  let annualExpense = 0;
  let monthlyIncome = 0;
  let expenseCount = 0;
  for (const r of items) {
    if (r.currency !== currency) continue;
    if (r.txn_type === "expense") {
      monthlyExpense += monthlyMinor(r);
      annualExpense += annualMinor(r);
      expenseCount += 1;
    } else if (r.txn_type === "income") {
      monthlyIncome += monthlyMinor(r);
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
const ADJECTIVE: Record<Freq, string> = {
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
  yearly: "Yearly",
};

/** Human cadence label, e.g. "Monthly" or "Every 2 weeks". */
export function cadenceLabel(rec: Pick<RecurringTransaction, "frequency" | "interval">): string {
  const f = rec.frequency as Freq;
  const n = rec.interval || 1;
  if (n === 1) return ADJECTIVE[f] ?? rec.frequency;
  return `Every ${n} ${UNIT[f] ?? rec.frequency}s`;
}

/** Best display label for a schedule: memo, else its category, else a fallback. */
export function recurringLabel(
  rec: Pick<RecurringTransaction, "memo" | "category_id" | "txn_type">,
  categories: Category[] | undefined,
): string {
  if (rec.memo?.trim()) return rec.memo.trim();
  const cat = categories?.find((c) => c.id === rec.category_id);
  if (cat) return cat.name;
  return rec.txn_type === "income" ? "Recurring income" : "Recurring expense";
}
