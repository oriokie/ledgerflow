import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { RecurringTransaction } from "../api/types";

const { createRecurring } = vi.hoisted(() => ({ createRecurring: vi.fn() }));

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
  useCategories: () => ({
    data: [
      { id: "cat-expense", name: "Rent", kind: "expense" },
      { id: "cat-income", name: "Salary", kind: "income" },
    ],
  }),
  useSetRecurringActive: () => ({ mutateAsync: vi.fn() }),
  useCancelRecurring: () => ({ mutateAsync: vi.fn() }),
  useAccounts: () => ({
    data: [
      { id: "checking", name: "Checking", currency: "USD" },
      { id: "savings", name: "Savings", currency: "USD" },
    ],
  }),
  useCreateRecurring: () => ({ mutateAsync: createRecurring }),
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

  it("creates a recurring savings transfer with distinct accounts", async () => {
    const user = userEvent.setup();
    createRecurring.mockResolvedValue({});
    render(<RecurringPage />);

    await user.click(screen.getByRole("button", { name: "New recurring transaction" }));
    const modal = screen.getByRole("dialog", { name: "New recurring transaction" });
    await user.click(within(modal).getByLabelText("Transfer / Savings"));

    const from = within(modal).getByLabelText("From account");
    const to = within(modal).getByLabelText("To account");
    await user.selectOptions(from, "checking");
    expect(within(to).queryByRole("option", { name: "Checking" })).not.toBeInTheDocument();
    await user.selectOptions(to, "savings");
    await user.type(within(modal).getByLabelText("Amount"), "200");
    await user.type(within(modal).getByLabelText("Name / memo"), "Emergency fund");
    await user.click(within(modal).getByRole("button", { name: "Create schedule" }));

    await waitFor(() =>
      expect(createRecurring).toHaveBeenCalledWith(
        expect.objectContaining({
          txn_type: "transfer",
          financial_account_id: "checking",
          counter_account_id: "savings",
          category_id: undefined,
          amount_minor: 20000,
          memo: "Emergency fund",
        }),
      ),
    );
  });
});
