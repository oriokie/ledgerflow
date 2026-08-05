import { api } from "./client";
import type {
  BorrowingCost,
  ConsolidationResult,
  DebtAnalytics,
  DebtStress,
  DebtSummary,
  DebtView,
  PayoffPlan,
  PayoffStrategy,
  RatePeriod,
  RefinanceResult,
  ScenarioResult,
} from "./types";

export const debtApi = {
  debts: () => api.get<DebtView[]>("/debt/debts/"),

  /**
   * Create a debt: the liability account and its terms in one request.
   *
   * Terms are all optional, which is what makes an informal debt expressible —
   * money borrowed from a friend has a name and an amount and nothing else.
   */
  createDebt: (payload: {
    name: string;
    currency: string;
    balance_minor: number;
    debt_kind?: string;
    lender?: string;
    apr?: string | number;
    minimum_payment_minor?: number;
    payment_day?: number | null;
    original_principal_minor?: number | null;
    notes?: string;
  }) => api.post<DebtView>("/debt/debts/", payload),

  /** Remove a debt outright. Distinct from `clearTerms`, which stops the
   * planning but leaves the account owing. */
  deleteDebt: (accountId: string) => api.delete<void>(`/debt/debts/${accountId}/`),
  /** Liability accounts that exist, whether or not anything is owed on them.
   * Distinct from `debts`, which is "what you owe" and excludes zero balances. */
  tracked: () => api.get<TrackedLiability[]>("/debt/debts/tracked/"),

  /** Null when nothing is owed — the API answers 204 rather than a row of
   * zeroes, which is a worse answer than "you have no debt". */
  summary: (extraMonthlyMinor = 0) =>
    api.get<DebtSummary | null>(`/debt/debts/summary/?extra_monthly_minor=${extraMonthlyMinor}`),

  payoff: (params: { strategy?: PayoffStrategy; extra_monthly_minor?: number; months?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.strategy) q.set("strategy", params.strategy);
    if (params.extra_monthly_minor) q.set("extra_monthly_minor", String(params.extra_monthly_minor));
    if (params.months) q.set("months", String(params.months));
    return api.get<PayoffPlan | null>(`/debt/debts/payoff/?${q.toString()}`);
  },

  extraPaymentCurve: (strategy: PayoffStrategy = "avalanche") =>
    api.get<
      {
        extra_monthly_minor: number;
        months_to_debt_free: number | null;
        total_interest_minor: number;
        interest_saved_minor: number;
        months_saved: number | null;
      }[]
    >(`/debt/debts/extra-payment-curve/?strategy=${strategy}`),

  setTerms: (
    accountId: string,
    payload: {
      apr?: string | number;
      minimum_payment_minor?: number;
      debt_kind?: string;
      payment_day?: number | null;
      original_principal_minor?: number | null;
      include_in_payoff?: boolean;
      custom_priority?: number;
      compounding?: string;
      monthly_fee_minor?: number;
      annual_fee_minor?: number;
      annual_fee_month?: number;
      origination_fee_minor?: number;
    },
  ) => api.put<DebtView>(`/debt/debts/${accountId}/terms/`, payload),

  clearTerms: (accountId: string) => api.delete<void>(`/debt/debts/${accountId}/terms/`),

  /** The Debt Stress Score, always with its derivation. Null when nothing is
   * owed. */
  stress: () => api.get<DebtStress | null>("/debt/debts/stress/"),

  /** Annual cost split into interest and fees — they behave differently, so a
   * combined figure would hide a card whose real cost is a fee. */
  borrowingCost: () => api.get<BorrowingCost | null>("/debt/debts/borrowing-cost/"),

  rateHistory: (accountId: string) =>
    api.get<{
      current_apr: number;
      history: RatePeriod[];
      historical_average_apr: number | null;
      next_change_on: string | null;
      next_apr: number | null;
    }>(`/debt/debts/${accountId}/rates/`),

  recordRateChange: (
    accountId: string,
    payload: { apr: string; effective_from: string; source?: string; notes?: string },
  ) => api.post(`/debt/debts/${accountId}/rates/`, payload),

  setOffsetAccounts: (accountId: string, accountIds: string[]) =>
    api.put<DebtView>(`/debt/debts/${accountId}/offsets/`, { account_ids: accountIds }),

  /** Simulation only — never modifies the debt. */
  simulateRefinance: (
    accountId: string,
    payload: {
      new_apr: string;
      new_minimum_payment_minor: number;
      closing_costs_minor?: number;
      capitalise_costs?: boolean;
    },
  ) => api.post<RefinanceResult>(`/debt/debts/${accountId}/refinance/`, payload),

  simulateConsolidation: (payload: {
    account_ids: string[];
    new_apr: string;
    new_minimum_payment_minor: number;
    fees_minor?: number;
  }) => api.post<ConsolidationResult>("/debt/debts/consolidate/", payload),

  analytics: (params: { strategy?: PayoffStrategy; extra_monthly_minor?: number; months?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.strategy) q.set("strategy", params.strategy);
    if (params.extra_monthly_minor) q.set("extra_monthly_minor", String(params.extra_monthly_minor));
    if (params.months) q.set("months", String(params.months));
    return api.get<DebtAnalytics | null>(`/debt/debts/analytics/?${q.toString()}`);
  },

  /** API path for the CSV export. Fetched with auth headers via
   * `downloadFile` — a bare anchor would 401, since this endpoint is
   * tenant-scoped like every other. */
  exportPath: (strategy: PayoffStrategy = "avalanche", extraMonthlyMinor = 0) =>
    `/debt/debts/payoff/export/?strategy=${strategy}&extra_monthly_minor=${extraMonthlyMinor}`,

  compareScenarios: (
    scenarios: {
      label: string;
      strategy?: PayoffStrategy;
      monthly_minor?: number;
      lump_sums?: [number, number][];
      step_ups?: [number, number][];
    }[],
  ) =>
    api.post<{
      baseline: { months_to_debt_free: number | null; total_interest_minor: number; total_paid_minor: number };
      scenarios: ScenarioResult[];
    }>("/debt/debts/scenarios/", { scenarios }),
};

export interface TrackedLiability {
  account_id: string;
  name: string;
  account_type: string;
  currency: string;
  balance_minor: number;
  has_terms: boolean;
  apr: number | null;
  minimum_payment_minor: number;
}
