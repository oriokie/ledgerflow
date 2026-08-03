import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

// Data hooks are mocked as vi.fn so individual tests can vary the workspace
// between "brand new" (empty) and "established" (has an account + activity).
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
}));
vi.mock("../hooks/useBudgeting", () => ({
  useBudgets: () => ({ data: undefined }),
  useBudgetStatus: () => ({ data: undefined }),
}));
vi.mock("../hooks/useGoals", () => ({ useGoals: () => ({ data: undefined }) }));
// Undefined by default: the committed-income strip must render nothing at all
// when a household has not said what it earns. A "0% committed" card derived
// from an absence reads as a clean bill of health.
vi.mock("../hooks/useIncome", () => ({ useIncomeSummary: () => ({ data: undefined }) }));
vi.mock("../hooks/useTenancy", () => ({ useMembers: () => ({ data: undefined }) }));
vi.mock("../hooks/useCoach", () => ({ useInsights: () => ({ data: [] }) }));
vi.mock("../hooks/useIntelligence", () => ({
  useForecast: () => ({ data: undefined }),
  useHealthScore: () => ({ data: undefined }),
  useNetWorthHistory: () => ({ data: undefined }),
  useRecommendations: () => ({ data: undefined }),
  useSpendingTrend: () => ({ data: undefined }),
}));
vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ user: { first_name: "Sam", email: "sam@example.com" } }),
}));
vi.mock("../hooks/useEntitlements", () => ({
  useAiEnabled: () => ({ aiEnabled: true, isLoading: false }),
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
    expect(screen.getByRole("link", { name: /add account/i })).toBeInTheDocument();
  });

  it("renders the full dashboard once an account and activity exist", () => {
    setWorkspace({
      accounts: [{ id: "a1", name: "Checking", currency: "USD" }],
      txns: [{ id: "t1" }],
    });
    renderDash();
    // The real tiers (with their own empty fallbacks) appear as soon as there
    // is an account and some activity.
    expect(screen.getByRole("group", { name: /time period/i })).toBeInTheDocument();
    expect(screen.getByText(/no spending yet/i)).toBeInTheDocument();
    expect(screen.getByText(/no goals yet/i)).toBeInTheDocument();
  });

  it("keeps the checklist alongside the dashboard until setup is finished", () => {
    setWorkspace({
      accounts: [{ id: "a1", name: "Checking", currency: "USD" }],
      txns: [{ id: "t1" }],
    });
    renderDash();
    // Budgets, goals and sharing are still outstanding, so guidance stays —
    // previously it vanished here, exactly when the user knew least about them.
    expect(screen.getByText(/let's get you set up/i)).toBeInTheDocument();
    expect(screen.getByText("2 of 5 done")).toBeInTheDocument();
    // Guidance and real data coexist rather than one hiding the other.
    expect(screen.getByRole("group", { name: /time period/i })).toBeInTheDocument();
  });

  it("does not duplicate the Add Transaction button already in the persistent header", () => {
    // Regression: AppShell's top bar carries "Add transaction" on every page,
    // including this one — the dashboard's own greeting header repeated the
    // identical button pointing at the identical destination, so a visitor
    // saw two at once. AppShell isn't rendered in this test harness (only
    // DashboardPage itself is), so any match here can only be the page's own
    // copy, which must not exist any more.
    setWorkspace({
      accounts: [{ id: "a1", name: "Checking", currency: "USD" }],
      txns: [{ id: "t1" }],
    });
    renderDash();
    expect(screen.queryByRole("link", { name: /^add transaction$/i })).not.toBeInTheDocument();
  });
});
