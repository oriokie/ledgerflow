import { describe, expect, it } from "vitest";
import type { Category, RecurringTransaction } from "../../api/types";
import {
  annualMinor,
  cadenceLabel,
  monthlyMinor,
  recurringLabel,
  recurringTotals,
  sortByMonthlyCost,
} from "./recurringMath";

function rec(over: Partial<RecurringTransaction> = {}): RecurringTransaction {
  return {
    id: Math.random().toString(36).slice(2),
    txn_type: "expense",
    amount_minor: 1500,
    currency: "USD",
    frequency: "monthly",
    interval: 1,
    next_run_on: "2026-02-01",
    occurrences_created: 1,
    is_active: true,
    memo: "",
    category_id: null,
    financial_account_id: null,
    payee_id: null,
    ...over,
  };
}

describe("monthly/annual normalization", () => {
  it("keeps monthly as-is", () => {
    expect(monthlyMinor(rec({ frequency: "monthly", amount_minor: 1500 }))).toBe(1500);
    expect(annualMinor(rec({ frequency: "monthly", amount_minor: 1500 }))).toBe(18000);
  });

  it("spreads yearly across 12 months", () => {
    expect(monthlyMinor(rec({ frequency: "yearly", amount_minor: 12000 }))).toBe(1000);
    expect(annualMinor(rec({ frequency: "yearly", amount_minor: 12000 }))).toBe(12000);
  });

  it("normalizes weekly and daily using a 365-day year", () => {
    expect(annualMinor(rec({ frequency: "weekly", amount_minor: 1000 }))).toBe(52143);
    expect(monthlyMinor(rec({ frequency: "weekly", amount_minor: 1000 }))).toBe(4345);
    expect(annualMinor(rec({ frequency: "daily", amount_minor: 100 }))).toBe(36500);
    expect(monthlyMinor(rec({ frequency: "daily", amount_minor: 100 }))).toBe(3042);
  });

  it("accounts for the interval", () => {
    expect(monthlyMinor(rec({ frequency: "monthly", amount_minor: 3000, interval: 3 }))).toBe(1000);
  });
});

describe("recurringTotals", () => {
  it("separates recurring spend from income in the common currency", () => {
    const t = recurringTotals([
      rec({ txn_type: "expense", frequency: "monthly", amount_minor: 1500 }),
      rec({ txn_type: "expense", frequency: "yearly", amount_minor: 12000 }),
      rec({ txn_type: "income", frequency: "monthly", amount_minor: 300000 }),
      rec({ txn_type: "expense", currency: "EUR", amount_minor: 9999 }),
    ]);
    expect(t.currency).toBe("USD");
    expect(t.monthlyExpense).toBe(2500); // 1500 + 1000
    expect(t.annualExpense).toBe(30000);
    expect(t.monthlyIncome).toBe(300000);
    expect(t.expenseCount).toBe(2);
  });
});

describe("sortByMonthlyCost", () => {
  it("orders the priciest first", () => {
    const cheap = rec({ amount_minor: 500 });
    const dear = rec({ amount_minor: 5000 });
    expect(sortByMonthlyCost([cheap, dear])[0]).toBe(dear);
  });
});

describe("cadenceLabel", () => {
  it("reads naturally for single and multi-interval schedules", () => {
    expect(cadenceLabel(rec({ frequency: "monthly", interval: 1 }))).toBe("Monthly");
    expect(cadenceLabel(rec({ frequency: "weekly", interval: 2 }))).toBe("Every 2 weeks");
  });
});

describe("recurringLabel", () => {
  const categories: Category[] = [{ id: "c1", name: "Streaming", kind: "expense", path: "Streaming", depth: 0, parent_id: null }];
  it("prefers memo, then category, then a type fallback", () => {
    expect(recurringLabel(rec({ memo: "Netflix" }), categories)).toBe("Netflix");
    expect(recurringLabel(rec({ memo: "", category_id: "c1" }), categories)).toBe("Streaming");
    expect(recurringLabel(rec({ memo: "", category_id: null, txn_type: "income" }), categories)).toBe("Recurring income");
  });
});
