import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Transaction } from "../api/types";

const rows: Transaction[] = [
  {
    id: "t1",
    financial_account_id: "acc",
    amount_minor: -1500,
    currency: "USD",
    occurred_at: "2024-03-01T10:00:00Z",
    status: "posted",
    source: "manual",
    category_id: null,
    counter_account_id: null,
    transfer_group: null,
    memo: "Coffee",
    split_group: null,
  },
];

vi.mock("../hooks/useFinance", () => ({
  useAccounts: () => ({ data: [{ id: "acc", name: "Checking", account_type: "checking", currency: "USD", balance_minor: 0 }] }),
  useCategories: () => ({ data: [{ id: "c1", name: "Groceries", kind: "expense", path: "Groceries", depth: 0, parent_id: null }] }),
  useTransactions: () => ({ data: { results: rows, next: null, previous: null }, isLoading: false }),
  useUpdateTransaction: () => ({ mutate: vi.fn() }),
  useBulkUpdateTransactions: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useBulkVoidTransactions: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

import { TransactionsPage } from "./TransactionsPage";

describe("TransactionsPage", () => {
  it("renders search, filters, and the transaction list", () => {
    render(
      <MemoryRouter>
        <TransactionsPage />
      </MemoryRouter>,
    );
    expect(screen.getByLabelText(/search transactions/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /filters/i })).toBeInTheDocument();
    expect(screen.getByText("Coffee")).toBeInTheDocument();
  });

  it("reveals the bulk action bar once a row is selected", () => {
    render(
      <MemoryRouter>
        <TransactionsPage />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("region", { name: /bulk actions/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: /select coffee/i }));

    const bar = screen.getByRole("region", { name: /bulk actions/i });
    expect(bar).toBeInTheDocument();
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /set category for selected/i })).toBeInTheDocument();
  });
});
