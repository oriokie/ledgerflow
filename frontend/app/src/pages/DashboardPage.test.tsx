import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("../hooks/useFinance", () => ({
  useAccounts: vi.fn(() => ({ data: undefined, isLoading: false })),
  useCategories: vi.fn(() => ({ data: undefined })),
  useCashflowCalendar: () => ({ data: undefined }),
  useNetWorth: vi.fn(() => ({ data: undefined, isLoading: false })),
  useNetWorthBase: vi.fn(() => ({ data: undefined })),
  useCashFlow: vi.fn(() => ({ data: undefined, isLoading: false })),
  useCategoryBreakdown: vi.fn(() => ({ data: undefined })),
  useBills: vi.fn(() => ({ data: undefined })),
  useTransactions: vi.fn(() => ({ data: undefined, isLoading: false })),
  useReviewCount: () => ({ data: { count: 0 } }),
  useRecurring: () => ({ data: undefined }),
}));
vi.mock("../hooks/useBudgeting", () => ({
  useBudgets: () => ({ data: undefined }),
  useBudgetStatus: () => ({ data: undefined }),
}));
vi.mock("../hooks/useGoals", () => ({
  useGoals: () => ({ data: undefined }),
  useGoalForecasts: () => ({ data: undefined }),
}));
vi.mock("../hooks/useIncome", () => ({
  useIncomeSummary: () => ({ data: undefined }),
  useIncomeSources: () => ({ data: undefined }),
}));
vi.mock("../hooks/useTenancy", () => ({ useMembers: () => ({ data: undefined }) }));
vi.mock("../hooks/useCoach", () => ({ useInsights: () => ({ data: [] }) }));
vi.mock("../hooks/useInvestments", () => ({ usePortfolio: () => ({ data: undefined }) }));
vi.mock("../hooks/useDebt", () => ({
  useDebts: () => ({ data: undefined }),
  useDebtSummary: () => ({ data: undefined }),
}));
vi.mock("../hooks/useIntelligence", () => ({
  useForecast: () => ({ data: undefined }),
  useHealthScore: () => ({ data: undefined }),
  useNetWorthHistory: () => ({ data: undefined }),
  useRecommendations: () => ({ data: undefined }),
  useSpendingTrend: () => ({ data: undefined }),
}));
vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({
    user: { first_name: "Sam", email: "sam@example.com" },
    activeWorkspace: {
      role: "owner",
      tenant: { id: "t1", base_currency: "USD", base_currency_chosen_at: null },
    },
  }),
}));
vi.mock("../hooks/useEntitlements", () => ({
  useAiEnabled: () => ({ aiEnabled: true, isLoading: false }),
}));
vi.mock("../hooks/useDismissible", () => ({
  useDismissible: () => [false, vi.fn()],
}));

import { useAccounts, useTransactions } from "../hooks/useFinance";
import { DashboardPage } from "./DashboardPage";

function setWorkspace({ accounts, txns }: { accounts: unknown[]; txns: unknown[] }) {
  vi.mocked(useAccounts).mockReturnValue({ data: accounts, isLoading: false } as unknown as ReturnType<typeof useAccounts>);
  vi.mocked(useTransactions).mockReturnValue({
    data: { results: txns, next: null, previous: null, count: txns.length },
    isLoading: false,
  } as unknown as ReturnType<typeof useTransactions>);
}

function renderDash() {
  return render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  );
}

describe("DashboardPage", () => {
  it("shows the Getting Started checklist for a brand-new empty workspace", () => {
    setWorkspace({ accounts: [], txns: [] });
    renderDash();
    expect(screen.getByText(/Sam/)).toBeInTheDocument();
    expect(screen.getByText(/let's get you set up/i)).toBeInTheDocument();
    expect(screen.getByText(/choose your currency/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /use this currency/i })).toBeInTheDocument();
  });

  it("renders the command-center dashboard once an account and activity exist", () => {
    setWorkspace({
      accounts: [{ id: "a1", name: "Checking", currency: "USD", account_type: "checking", balance_minor: 0 }],
      txns: [{ id: "t1" }],
    });
    renderDash();
    expect(screen.getByRole("group", { name: /time period/i })).toBeInTheDocument();
    expect(screen.getByText(/financial pulse/i)).toBeInTheDocument();
    expect(screen.getByText(/needs your attention/i)).toBeInTheDocument();
    expect(screen.getByText(/spending intelligence/i)).toBeInTheDocument();
    expect(screen.getByText(/no goals yet|set a target/i)).toBeInTheDocument();
  });

  it("keeps the checklist alongside the dashboard until setup is finished", () => {
    setWorkspace({
      accounts: [{ id: "a1", name: "Checking", currency: "USD", account_type: "checking", balance_minor: 0 }],
      txns: [{ id: "t1" }],
    });
    renderDash();
    expect(screen.getByText(/let's get you set up/i)).toBeInTheDocument();
    expect(screen.getByText("2 of 6 done")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /time period/i })).toBeInTheDocument();
  });

  it("does not duplicate the Add Transaction button already in the persistent header", () => {
    setWorkspace({
      accounts: [{ id: "a1", name: "Checking", currency: "USD", account_type: "checking", balance_minor: 0 }],
      txns: [{ id: "t1" }],
    });
    renderDash();
    expect(screen.queryByRole("link", { name: /^add transaction$/i })).not.toBeInTheDocument();
  });
});
