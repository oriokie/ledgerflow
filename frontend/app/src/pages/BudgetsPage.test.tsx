import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { BudgetStatus } from "../api/types";

const status: BudgetStatus = {
  budget_id: "b1",
  as_of: "2026-01-16",
  period_start: "2026-01-01",
  period_end: "2026-02-01",
  lines: [
    {
      line_id: "l1",
      category_id: "c1",
      category_name: "Groceries",
      limit_minor: 40000,
      carried_minor: 0,
      effective_limit_minor: 40000,
      actual_minor: 52000,
      remaining_minor: -12000,
      percent_used: 130,
      over_budget: true,
    },
    {
      line_id: "l2",
      category_id: "c2",
      category_name: "Transport",
      limit_minor: 20000,
      carried_minor: 0,
      effective_limit_minor: 20000,
      actual_minor: 8000,
      remaining_minor: 12000,
      percent_used: 40,
      over_budget: false,
    },
  ],
};

vi.mock("../hooks/useBudgeting", () => ({
  useBudgets: () => ({ data: [{ id: "b1", name: "Monthly", currency: "USD", period: "monthly", starts_on: "2026-01-01" }], isLoading: false }),
  useBudgetStatus: () => ({ data: status }),
  useAddBudgetLine: () => ({ mutateAsync: vi.fn() }),
  useUpdateBudgetLine: () => ({ mutateAsync: vi.fn() }),
  useRemoveBudgetLine: () => ({ mutateAsync: vi.fn() }),
  useDeleteBudget: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock("../hooks/useFinance", () => ({
  useCategories: () => ({ data: [{ id: "c1", name: "Groceries", kind: "expense", path: "Groceries", depth: 0, parent_id: null }] }),
}));

import { BudgetsPage } from "./BudgetsPage";

describe("BudgetsPage", () => {
  it("shows the summary, an over-budget alert, and category rows", () => {
    render(
      <MemoryRouter>
        <BudgetsPage />
      </MemoryRouter>,
    );

    // Summary stat labels
    expect(screen.getByText("Spent")).toBeInTheDocument();
    expect(screen.getByText("Budgeted")).toBeInTheDocument();

    // Alert for the over-budget category
    expect(screen.getByText(/1 category is over budget/i)).toBeInTheDocument();

    // Category rows (name appears in the alert and the row list)
    expect(screen.getAllByText("Groceries").length).toBeGreaterThan(0);
    expect(screen.getByText("Transport")).toBeInTheDocument();

    // Progress bars rendered for both lines + the overall summary bar
    expect(screen.getAllByRole("progressbar").length).toBeGreaterThanOrEqual(3);
  });
});
