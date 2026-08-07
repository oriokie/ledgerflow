import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { RecurringTransaction } from "../api/types";

function rec(over: Partial<RecurringTransaction>): RecurringTransaction {
  return {
    id: Math.random().toString(36).slice(2),
    txn_type: "expense",
    amount_minor: 1500,
    currency: "USD",
    frequency: "monthly",
    interval: 1,
    next_run_on: "2026-02-01",
    occurrences_created: 1,
    is_active: true,
    memo: "",
    category_id: null,
    financial_account_id: null,
    payee_id: null,
    ...over,
  };
}

const recurring = [
  rec({ id: "r1", memo: "Netflix", amount_minor: 1500 }),
  rec({ id: "r2", memo: "Gym", amount_minor: 4000 }),
];

vi.mock("../hooks/useFinance", () => ({
  useRecurring: () => ({ data: recurring }),
  useCategories: () => ({ data: [] }),
  useSetRecurringActive: () => ({ mutateAsync: vi.fn() }),
  useCancelRecurring: () => ({ mutateAsync: vi.fn() }),
  useAccounts: () => ({ data: [] }),
  useCreateRecurring: () => ({ mutateAsync: vi.fn() }),
  useUpdateRecurring: () => ({ mutateAsync: vi.fn() }),
}));

// The create/edit modal defaults its currency to the workspace's, so the page
// now reaches into auth context even while the modal is closed.
vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ activeWorkspace: { tenant: { id: "t1", base_currency: "USD" } } }),
}));

import { RecurringPage } from "./RecurringPage";

describe("RecurringPage", () => {
  it("shows recurring spend, the review nudge, and a row per subscription", () => {
    render(<RecurringPage />);

    expect(screen.getByText("Recurring monthly")).toBeInTheDocument();
    // Insight nudge mentions the count
    expect(screen.getByText(/2 subscriptions costing about/i)).toBeInTheDocument();
    // Priciest first
    const gymRow = screen.getByText("Gym").closest(".lf-sub-row");
    expect(gymRow).toBeInTheDocument();
    expect(screen.getByText("Netflix")).toBeInTheDocument();
    // Money renders the cents in their own span (see Money's ".lf-amount-cents"
    // convention, ui/Figure.test.tsx), so the figure is split across nodes —
    // check the row's cost text rather than a single getByText string match.
    expect(gymRow?.querySelector(".lf-sub-cost-main")?.textContent).toBe("$40.00/mo");
  });
});
