import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Bill } from "../api/types";

function bill(over: Partial<Bill> & { due_on: string; name: string }): Bill {
  return {
    id: Math.random().toString(36).slice(2),
    amount_minor: 1000,
    currency: "USD",
    status: "upcoming",
    payee_id: null,
    category_id: null,
    recurrence_frequency: "monthly",
    autopay_account_id: null,
    paid_at: null,
    notes: "",
    ...over,
  };
}

// Dates far in the past/future so bucketing is independent of the test clock.
const bills: Bill[] = [
  bill({ name: "Rent", due_on: "2020-01-01", amount_minor: 5000 }), // long overdue
  bill({ name: "Insurance", due_on: "2099-01-01", amount_minor: 3000 }), // far future → later
];

vi.mock("../hooks/useFinance", () => ({
  useBills: () => ({ data: bills }),
  useAccounts: () => ({ data: [{ id: "a1", name: "Checking", account_type: "checking", currency: "USD", balance_minor: 0 }] }),
  usePayBill: () => ({ mutateAsync: vi.fn() }),
  useCancelBill: () => ({ mutateAsync: vi.fn().mockResolvedValue(undefined) }),
  useCategories: () => ({ data: [] }),
  useCreateBill: () => ({ mutateAsync: vi.fn() }),
}));

import { BillsPage } from "./BillsPage";
import { ToastProvider } from "../ui";

describe("BillsPage", () => {
  it("shows the summary and groups bills by urgency", () => {
    render(
      <MemoryRouter>
        <BillsPage />
      </MemoryRouter>,
    );
    expect(screen.getByText("Overdue (1)")).toBeInTheDocument(); // summary stat label
    expect(screen.getByText("Due this week")).toBeInTheDocument();
    expect(screen.getByText("Rent")).toBeInTheDocument();
    expect(screen.getByText("Insurance")).toBeInTheDocument();
    // The overdue bill exposes an overdue pill
    expect(screen.getByText(/overdue$/)).toBeInTheDocument();
  });

  it("confirms a payment with a toast", async () => {
    render(
      <MemoryRouter>
        <ToastProvider>
          <BillsPage />
        </ToastProvider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getAllByRole("button", { name: "Mark paid" })[0]);
    expect(await screen.findByText("Rent marked as paid")).toBeInTheDocument();
  });

  it("cancels a bill only after a confirm step, then toasts", async () => {
    render(
      <MemoryRouter>
        <ToastProvider>
          <BillsPage />
        </ToastProvider>
      </MemoryRouter>,
    );
    // Row cancel is an icon button; first click reveals the confirm.
    fireEvent.click(screen.getByRole("button", { name: /cancel rent/i }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel bill" }));
    expect(await screen.findByText("Rent cancelled")).toBeInTheDocument();
  });
});
