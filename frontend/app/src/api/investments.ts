import { api } from "./client";
import type {
  AllocationSlice,
  AssetClass,
  HoldingValuation,
  PortfolioHistoryPoint,
  PortfolioSummary,
  Security,
} from "./types";

export const investmentsApi = {
  securities: () => api.get<Security[]>("/investments/securities/"),

  createSecurity: (payload: {
    symbol: string;
    name?: string;
    asset_class: AssetClass;
    currency: string;
    sector?: string;
    exchange?: string;
  }) => api.post<Security>("/investments/securities/", payload),

  holdings: () => api.get<HoldingValuation[]>("/investments/holdings/"),

  /** Null when there are no holdings — the API answers 204 rather than an
   * all-zero portfolio, which would read as one that lost everything. */
  portfolio: () => api.get<PortfolioSummary | null>("/investments/portfolio/"),

  history: (months = 12) =>
    api.get<PortfolioHistoryPoint[]>(`/investments/portfolio/history/?months=${months}`),

  trade: (
    action: "buy" | "sell",
    payload: {
      financial_account_id: string;
      security_id: string;
      quantity: string;
      amount_minor: number;
      fee_minor?: number;
      occurred_on?: string;
      memo?: string;
    },
  ) => api.post(`/investments/trade/${action}/`, payload),

  recordPrice: (payload: { security_id: string; price_minor: number; as_of?: string }) =>
    api.post("/investments/prices/", payload),

  recordDividend: (payload: {
    financial_account_id: string;
    security_id: string;
    amount_minor: number;
    occurred_on?: string;
    memo?: string;
  }) => api.post("/investments/dividends/record/", payload),

  /**
   * Interest paid out by a holding — an MMF distribution, a bond coupon.
   *
   * Separate from a dividend rather than folded into it: the two are taxed and
   * reported differently, and a fund paying monthly interest is a different
   * cash-flow shape from an equity paying a discretionary dividend.
   */
  recordInterest: (payload: {
    financial_account_id: string;
    security_id: string;
    amount_minor: number;
    occurred_on?: string;
    memo?: string;
  }) => api.post("/investments/interest/record/", payload),

  dividends: (months = 12) =>
    api.get<{ currency: string; total_minor: number; by_security: { symbol: string; amount_minor: number }[] } | null>(
      `/investments/dividends/?months=${months}`,
    ),
};

export type { AllocationSlice };
