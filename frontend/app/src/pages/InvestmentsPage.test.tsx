import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PortfolioPerformance, PortfolioSummary } from "../api/types";

let portfolio: PortfolioSummary | null = null;
let performance: PortfolioPerformance | null = null;

vi.mock("../hooks/useInvestments", () => ({
  usePortfolio: () => ({ data: portfolio, isLoading: false }),
  useHoldings: () => ({ data: [] }),
  usePortfolioHistory: () => ({ data: [] }),
  usePortfolioPerformance: () => ({ data: performance }),
  useSecurities: () => ({ data: [] }),
  useCreateSecurity: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useTrade: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useRecordPrice: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useRecordDividend: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useRecordInterest: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock("../hooks/useFinance", () => ({
  useAccounts: () => ({ data: [] }),
}));

vi.mock("../hooks/useCurrencies", () => ({
  useCurrencyOptions: () => [{ value: "USD", label: "USD" }],
}));

vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ activeWorkspace: { role: "owner", tenant: { id: "t1", base_currency: "USD" } } }),
}));

vi.mock("./investments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./investments")>();
  return {
    ...actual,
    SecurityModal: () => null,
    PriceModal: () => null,
    IncomeModal: () => null,
    TradeModal: () => null,
  };
});

import { InvestmentsPage } from "./InvestmentsPage";

const SUMMARY: PortfolioSummary = {
  currency: "USD",
  cost_basis_minor: 500_000,
  market_value_minor: 750_000,
  unrealized_gain_minor: 250_000,
  unrealized_gain_pct: 50,
  realized_gain_minor: 0,
  dividend_income_minor: 0,
  total_return_minor: 250_000,
  holding_count: 1,
  unpriced_count: 0,
  priced_as_of: "2026-08-03",
  stale_count: 0,
  asset_allocation: [],
  sector_allocation: [],
  account_allocation: [],
};

const PERFORMANCE: PortfolioPerformance = {
  currency: "USD",
  start: "2025-08-01",
  end: "2026-08-01",
  beginning_value_minor: 500_000,
  ending_value_minor: 750_000,
  net_flow_minor: 0,
  modified_dietz: 0.123,
  annualized_return: 0.123,
  volatility: 0.08,
  max_drawdown: -0.042,
  months: 12,
  irregular_quotes: true,
  caveats: ["Quotes are irregular."],
};

function renderPage() {
  return render(
    <MemoryRouter>
      <InvestmentsPage />
    </MemoryRouter>,
  );
}

describe("InvestmentsPage", () => {
  beforeEach(() => {
    portfolio = null;
    performance = null;
  });

  it("invites a first security when nothing is tracked", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Investments" })).toBeInTheDocument();
    expect(screen.getByText(/no investments tracked yet/i)).toBeInTheDocument();
  });

  it("shows Modified Dietz, volatility and drawdown on a funded portfolio", () => {
    portfolio = SUMMARY;
    performance = PERFORMANCE;
    renderPage();
    expect(screen.getByText("Modified Dietz")).toBeInTheDocument();
    expect(screen.getByText("12.3%")).toBeInTheDocument();
    expect(screen.getByText("Volatility")).toBeInTheDocument();
    expect(screen.getByText("8.0%")).toBeInTheDocument();
    expect(screen.getByText("Max drawdown")).toBeInTheDocument();
    expect(screen.getByText("-4.2%")).toBeInTheDocument();
    expect(screen.getByText(/quotes in this window are irregular/i)).toBeInTheDocument();
  });
});
