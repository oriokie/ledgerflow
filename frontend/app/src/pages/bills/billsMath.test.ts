import { describe, expect, it } from "vitest";
import type { Bill } from "../../api/types";
import { billBuckets, billTotals, daysUntil, dueLabel } from "./billsMath";

const AS_OF = new Date("2026-01-15T00:00:00Z");

function bill(over: Partial<Bill> & { due_on: string }): Bill {
  return {
    id: Math.random().toString(36).slice(2),
    name: "Bill",
    amount_minor: 1000,
    currency: "USD",
    status: "upcoming",
    payee_id: null,
    category_id: null,
    recurrence_frequency: "monthly",
    autopay_account_id: null,
    paid_at: null,
    notes: "",
    ...over,
  };
}

describe("daysUntil / dueLabel", () => {
  it("counts whole days, negative when overdue", () => {
    expect(daysUntil("2026-01-20", AS_OF)).toBe(5);
    expect(daysUntil("2026-01-10", AS_OF)).toBe(-5);
  });

  it("labels urgency with a tone", () => {
    expect(dueLabel(-4)).toEqual({ text: "4 days overdue", tone: "danger" });
    expect(dueLabel(0)).toEqual({ text: "Due today", tone: "warning" });
    expect(dueLabel(3)).toEqual({ text: "Due in 3 days", tone: "warning" });
    expect(dueLabel(20)).toEqual({ text: "Due in 20 days" });
  });
});

const bills: Bill[] = [
  bill({ due_on: "2026-01-01", status: "overdue", amount_minor: 5000 }),
  bill({ due_on: "2026-01-10", status: "upcoming", amount_minor: 1000 }), // past due → overdue
  bill({ due_on: "2026-01-18", status: "upcoming", amount_minor: 2000 }), // in 3 days
  bill({ due_on: "2026-02-10", status: "upcoming", amount_minor: 3000 }), // in 26 days
  bill({ due_on: "2026-01-05", status: "paid", amount_minor: 9000 }),
  bill({ due_on: "2026-01-20", status: "cancelled", amount_minor: 8000 }),
];

describe("billBuckets", () => {
  it("splits into overdue / this week / later / paid, dropping cancelled", () => {
    const b = billBuckets(bills, AS_OF);
    expect(b.overdue.map((x) => x.amount_minor)).toEqual([5000, 1000]); // sorted by due date
    expect(b.dueThisWeek.map((x) => x.amount_minor)).toEqual([2000]);
    expect(b.later.map((x) => x.amount_minor)).toEqual([3000]);
    expect(b.paid).toHaveLength(1);
  });
});

describe("billTotals", () => {
  it("sums overdue, due-in-7, and due-in-30 (each inclusive of more urgent)", () => {
    const t = billTotals(bills, AS_OF);
    expect(t.overdue_minor).toBe(6000);
    expect(t.overdue_count).toBe(2);
    expect(t.due7_minor).toBe(8000); // 6000 overdue + 2000 this week
    expect(t.due30_minor).toBe(11000); // + 3000 later (26 days)
  });
});
