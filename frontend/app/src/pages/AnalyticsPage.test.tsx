import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { CategoryBreakdownRow, SpendingTrendPoint } from "../api/types";

const trend: SpendingTrendPoint[] = [
  { period_start: "2026-05-01", income_minor: 100000, expense_minor: 80000, net_minor: 20000 },
  { period_start: "2026-06-01", income_minor: 120000, expense_minor: 60000, net_minor: 60000 },
];
const breakdown: CategoryBreakdownRow[] = [
  { category_id: "a", category_name: "Food", amount_minor: 6000 },
  { category_id: "b", category_name: "Transport", amount_minor: 4000 },
];

vi.mock("../hooks/useFinance", () => ({
  useCashflowStatement: () => ({ data: undefined, isLoading: false }),
  useAccounts: () => ({ data: [{ id: "acc1", name: "Checking", account_type: "checking", currency: "USD", balance_minor: 0 }] }),
  useCategoryBreakdown: () => ({ data: breakdown }),
  useCategoryTrend: () => ({ data: [], isLoading: false }),
}));
vi.mock("../hooks/useIntelligence", () => ({
  useSpendingTrend: () => ({ data: trend }),
}));
vi.mock("../hooks/useIncome", () => ({
  useIncomeSources: () => ({ data: [] }),
}));
vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ activeWorkspace: { tenant: { id: "t1", base_currency: "USD" } } }),
}));

import { AnalyticsPage } from "./AnalyticsPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <AnalyticsPage />
    </MemoryRouter>,
  );
}

describe("AnalyticsPage", () => {
  it("shows the comparison, breakdown, and drills down on click", () => {
    renderPage();

    // Comparison cards
    expect(screen.getByText("This month vs last")).toBeInTheDocument();
    expect(screen.getByText("Savings rate")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument(); // savings rate now

    // Breakdown + prompt to drill
    expect(screen.getByText("Spending by category")).toBeInTheDocument();
    expect(screen.getByText(/select a category/i)).toBeInTheDocument();

    // Drill down
    fireEvent.click(screen.getByRole("button", { name: /Food/ }));
    expect(screen.getByText(/averaging/i)).toBeInTheDocument();

    // The two-panel area uses the responsive split (collapses to one column on mobile)
    expect(document.querySelector(".lf-analytics-split")).not.toBeNull();
  });
});
