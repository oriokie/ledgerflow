import { describe, expect, it } from "vitest";
import {
  adaptiveSectionPriority,
  buildAttentionItems,
  buildChangeInsights,
  contextualStatement,
} from "./personalization";

describe("contextualStatement", () => {
  it("prioritizes overdue bills over softer signals", () => {
    const text = contextualStatement({
      overdueBills: 2,
      currency: "USD",
      netWorth: { currency: "USD", net_minor: 10000, assets_minor: 10000, liabilities_minor: 0 },
    });
    expect(text).toMatch(/2 bills are overdue/i);
  });

  it("returns null when there is nothing honest to say", () => {
    expect(contextualStatement({ overdueBills: 0, currency: "USD" })).toBeNull();
  });
});

describe("buildChangeInsights", () => {
  it("reports month-over-month spend shifts from real trend points", () => {
    const insights = buildChangeInsights({
      currency: "USD",
      spendingTrend: [
        { period_start: "2026-01-01", income_minor: 100000, expense_minor: 40000, net_minor: 60000 },
        { period_start: "2026-02-01", income_minor: 100000, expense_minor: 50000, net_minor: 50000 },
      ],
    });
    expect(insights.some((i) => /spending rose/i.test(i.title))).toBe(true);
  });
});

describe("buildAttentionItems", () => {
  it("ranks overdue bills ahead of soft recommendations", () => {
    const items = buildAttentionItems({
      currency: "USD",
      bills: [
        {
          id: "b1",
          name: "Rent",
          amount_minor: 100000,
          currency: "USD",
          due_on: "2026-01-01",
          status: "overdue",
          payee_id: null,
          category_id: null,
          recurrence_frequency: "monthly",
          autopay_account_id: null,
          paid_at: null,
          notes: "",
        },
      ],
      recommendations: [
        { kind: "tip", title: "Nice tip", body: "Optional", severity: "info" },
      ],
    });
    expect(items[0].kind).toBe("overdue_bill");
  });
});

describe("adaptiveSectionPriority", () => {
  it("elevates cashflow when a shortfall is projected", () => {
    const order = adaptiveSectionPriority({
      hasAttention: true,
      hasCashRisk: true,
      hasGoals: false,
      hasBudgetExceptions: false,
      hasInvestments: false,
      hasDebt: false,
      hasInsights: false,
    });
    expect(order.slice(0, 4)).toEqual(["pulse", "attention", "timeline", "cashflow"]);
    expect(order).not.toContain("investments");
  });
});
