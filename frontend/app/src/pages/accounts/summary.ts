import type { FinancialAccount, StatementLine } from "../../api/types";

/** Account types that represent money owed rather than money held. */
export const LIABILITY_TYPES = new Set(["credit_card", "loan"]);

export function isLiability(accountType: string): boolean {
  return LIABILITY_TYPES.has(accountType);
}

export interface CurrencyTotal {
  currency: string;
  assets_minor: number;
  liabilities_minor: number;
  net_minor: number;
  count: number;
}

/**
 * Roll accounts up per currency into assets / liabilities / net. Liability
 * balances are stored as their natural sign by the backend; we take the
 * magnitude so "liabilities" reads as a positive owed amount and net =
 * assets − liabilities. Sorted by account count so the busiest currency leads.
 */
export function summarizeByCurrency(accounts: FinancialAccount[] | undefined): CurrencyTotal[] {
  const map = new Map<string, CurrencyTotal>();
  for (const a of accounts ?? []) {
    const t =
      map.get(a.currency) ??
      { currency: a.currency, assets_minor: 0, liabilities_minor: 0, net_minor: 0, count: 0 };
    if (isLiability(a.account_type)) t.liabilities_minor += Math.abs(a.balance_minor);
    else t.assets_minor += a.balance_minor;
    t.count += 1;
    map.set(a.currency, t);
  }
  const totals = [...map.values()];
  for (const t of totals) t.net_minor = t.assets_minor - t.liabilities_minor;
  return totals.sort((a, b) => b.count - a.count);
}

/** The currency the workspace uses most, for headline framing. */
export function primaryCurrency(accounts: FinancialAccount[] | undefined): string {
  return summarizeByCurrency(accounts)[0]?.currency ?? accounts?.[0]?.currency ?? "USD";
}

export interface GroupedAccounts {
  assets: FinancialAccount[];
  liabilities: FinancialAccount[];
}

/** Split accounts into assets vs liabilities, each ordered by balance size. */
export function groupAccounts(accounts: FinancialAccount[] | undefined): GroupedAccounts {
  const assets: FinancialAccount[] = [];
  const liabilities: FinancialAccount[] = [];
  for (const a of accounts ?? []) {
    (isLiability(a.account_type) ? liabilities : assets).push(a);
  }
  const byMagnitude = (a: FinancialAccount, b: FinancialAccount) =>
    Math.abs(b.balance_minor) - Math.abs(a.balance_minor);
  assets.sort(byMagnitude);
  liabilities.sort(byMagnitude);
  return { assets, liabilities };
}

export interface StatementSummary {
  in_minor: number;
  out_minor: number;
  net_minor: number;
}

/**
 * Money in vs out for a set of statement lines. Positive amounts are inflows,
 * negatives are outflows (reported as a positive magnitude). Net = in − out.
 */
export function statementSummary(lines: StatementLine[] | undefined): StatementSummary {
  let inMinor = 0;
  let outMinor = 0;
  for (const l of lines ?? []) {
    if (l.amount_minor >= 0) inMinor += l.amount_minor;
    else outMinor += -l.amount_minor;
  }
  return { in_minor: inMinor, out_minor: outMinor, net_minor: inMinor - outMinor };
}

const TYPE_LABELS: Record<string, string> = {
  checking: "Checking",
  savings: "Savings",
  cash: "Cash",
  credit_card: "Credit card",
  loan: "Loan",
  investment: "Investment",
};

/** Human label for an account type, falling back to a de-slugged form. */
export function accountTypeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type.replace(/_/g, " ");
}
