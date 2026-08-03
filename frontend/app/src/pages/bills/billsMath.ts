import type { Bill } from "../../api/types";

const DAY_MS = 86_400_000;
const dayValue = (d: string): number => Date.parse(`${d.slice(0, 10)}T00:00:00Z`);

/** Whole days from `asOf` until `dueOn` (negative = overdue). */
export function daysUntil(dueOn: string, asOf: Date): number {
  const asOfUtc = Date.parse(`${asOf.toISOString().slice(0, 10)}T00:00:00Z`);
  return Math.floor((dayValue(dueOn) - asOfUtc) / DAY_MS);
}

/** Human urgency label + tone for a days-until value. */
export function dueLabel(days: number): { text: string; tone?: "danger" | "warning" } {
  if (days < 0) return { text: `${-days} day${-days === 1 ? "" : "s"} overdue`, tone: "danger" };
  if (days === 0) return { text: "Due today", tone: "warning" };
  if (days <= 7) return { text: `Due in ${days} day${days === 1 ? "" : "s"}`, tone: "warning" };
  return { text: `Due in ${days} days` };
}

/** Is this a bill still awaiting payment (not paid, not cancelled)? */
function isOpen(bill: Bill): boolean {
  return bill.status !== "paid" && bill.status !== "cancelled";
}

export interface BillBuckets {
  overdue: Bill[];
  dueThisWeek: Bill[];
  later: Bill[];
  paid: Bill[];
}

/**
 * Split bills into urgency buckets around `asOf`: overdue (past due or flagged),
 * due within 7 days, later, and already paid. Cancelled bills drop out.
 */
export function billBuckets(bills: Bill[] | undefined, asOf: Date): BillBuckets {
  const buckets: BillBuckets = { overdue: [], dueThisWeek: [], later: [], paid: [] };
  for (const b of bills ?? []) {
    if (b.status === "paid") {
      buckets.paid.push(b);
      continue;
    }
    if (b.status === "cancelled") continue;
    const d = daysUntil(b.due_on, asOf);
    if (b.status === "overdue" || d < 0) buckets.overdue.push(b);
    else if (d <= 7) buckets.dueThisWeek.push(b);
    else buckets.later.push(b);
  }
  const byDue = (a: Bill, b: Bill) => dayValue(a.due_on) - dayValue(b.due_on);
  buckets.overdue.sort(byDue);
  buckets.dueThisWeek.sort(byDue);
  buckets.later.sort(byDue);
  return buckets;
}

export interface BillTotals {
  overdue_minor: number;
  due7_minor: number;
  due30_minor: number;
  overdue_count: number;
}

/** Headline amounts: total overdue, due within 7 days, due within 30 days
 * (each inclusive of anything more urgent). */
export function billTotals(bills: Bill[] | undefined, asOf: Date): BillTotals {
  let overdue = 0;
  let due7 = 0;
  let due30 = 0;
  let overdueCount = 0;
  for (const b of bills ?? []) {
    if (!isOpen(b)) continue;
    const d = daysUntil(b.due_on, asOf);
    const isOverdue = b.status === "overdue" || d < 0;
    if (isOverdue) {
      overdue += b.amount_minor;
      overdueCount += 1;
    }
    if (d <= 7) due7 += b.amount_minor;
    if (d <= 30) due30 += b.amount_minor;
  }
  return { overdue_minor: overdue, due7_minor: due7, due30_minor: due30, overdue_count: overdueCount };
}
