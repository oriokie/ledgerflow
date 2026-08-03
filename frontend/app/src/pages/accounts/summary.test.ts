import { describe, expect, it } from "vitest";
import type { FinancialAccount, StatementLine } from "../../api/types";
import {
  accountTypeLabel,
  groupAccounts,
  isLiability,
  primaryCurrency,
  statementSummary,
  summarizeByCurrency,
} from "./summary";

function acct(partial: Partial<FinancialAccount> & { balance_minor: number; account_type: string }): FinancialAccount {
  return {
    id: Math.random().toString(36).slice(2),
    name: "Account",
    currency: "USD",
    mask: undefined,
    ...partial,
  };
}

function line(amount: number): StatementLine {
  return { amount_minor: amount } as StatementLine;
}

describe("isLiability", () => {
  it("flags credit cards and loans, not deposit accounts", () => {
    expect(isLiability("credit_card")).toBe(true);
    expect(isLiability("loan")).toBe(true);
    expect(isLiability("checking")).toBe(false);
    expect(isLiability("investment")).toBe(false);
  });
});

describe("summarizeByCurrency", () => {
  it("rolls assets, liabilities, and net per currency", () => {
    const accounts = [
      acct({ account_type: "checking", balance_minor: 100_00 }),
      acct({ account_type: "savings", balance_minor: 400_00 }),
      acct({ account_type: "credit_card", balance_minor: -50_00 }),
    ];
    const [usd] = summarizeByCurrency(accounts);
    expect(usd.currency).toBe("USD");
    expect(usd.assets_minor).toBe(500_00);
    expect(usd.liabilities_minor).toBe(50_00); // magnitude, not sign
    expect(usd.net_minor).toBe(450_00);
    expect(usd.count).toBe(3);
  });

  it("separates currencies and orders by account count", () => {
    const accounts = [
      acct({ account_type: "checking", balance_minor: 10, currency: "EUR" }),
      acct({ account_type: "checking", balance_minor: 10, currency: "USD" }),
      acct({ account_type: "savings", balance_minor: 10, currency: "USD" }),
    ];
    const totals = summarizeByCurrency(accounts);
    expect(totals.map((t) => t.currency)).toEqual(["USD", "EUR"]);
  });

  it("is empty for no accounts", () => {
    expect(summarizeByCurrency([])).toEqual([]);
    expect(summarizeByCurrency(undefined)).toEqual([]);
  });
});

describe("primaryCurrency", () => {
  it("picks the most common currency", () => {
    const accounts = [
      acct({ account_type: "checking", balance_minor: 1, currency: "GBP" }),
      acct({ account_type: "checking", balance_minor: 1, currency: "GBP" }),
      acct({ account_type: "checking", balance_minor: 1, currency: "USD" }),
    ];
    expect(primaryCurrency(accounts)).toBe("GBP");
  });

  it("defaults to USD with no accounts", () => {
    expect(primaryCurrency([])).toBe("USD");
  });
});

describe("groupAccounts", () => {
  it("splits assets and liabilities, each sorted by magnitude", () => {
    const accounts = [
      acct({ account_type: "checking", balance_minor: 100 }),
      acct({ account_type: "savings", balance_minor: 900 }),
      acct({ account_type: "loan", balance_minor: -300 }),
      acct({ account_type: "credit_card", balance_minor: -50 }),
    ];
    const { assets, liabilities } = groupAccounts(accounts);
    expect(assets.map((a) => a.balance_minor)).toEqual([900, 100]);
    expect(liabilities.map((a) => a.balance_minor)).toEqual([-300, -50]);
  });
});

describe("statementSummary", () => {
  it("sums inflows and outflows into a net", () => {
    const s = statementSummary([line(500), line(-200), line(-100), line(50)]);
    expect(s.in_minor).toBe(550);
    expect(s.out_minor).toBe(300);
    expect(s.net_minor).toBe(250);
  });

  it("handles empty input", () => {
    expect(statementSummary([])).toEqual({ in_minor: 0, out_minor: 0, net_minor: 0 });
    expect(statementSummary(undefined)).toEqual({ in_minor: 0, out_minor: 0, net_minor: 0 });
  });
});

describe("accountTypeLabel", () => {
  it("maps known types and de-slugs unknown ones", () => {
    expect(accountTypeLabel("credit_card")).toBe("Credit card");
    expect(accountTypeLabel("checking")).toBe("Checking");
    expect(accountTypeLabel("money_market")).toBe("money market");
  });
});
