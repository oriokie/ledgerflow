import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReconciliationSummary } from "../../api/finance";
import type { FinancialAccount } from "../../api/types";
import { ReconcilePanel } from "./ReconcilePanel";

const account: FinancialAccount = {
  id: "chk",
  name: "Everyday Checking",
  account_type: "checking",
  currency: "USD",
  balance_minor: 250_00,
};

const summary: ReconciliationSummary = {
  account_id: "chk",
  currency: "USD",
  reconciled_minor: -40_00,
  uncleared_minor: -12_50,
  ledger_balance_minor: -52_50,
  statement_balance_minor: -40_00,
  difference_minor: 0,
  reconciled_count: 1,
  uncleared_count: 1,
  last_reconciled_at: null,
  is_balanced: true,
  uncleared: [
    {
      id: "tx1",
      occurred_at: "2026-07-02T12:00:00Z",
      amount_minor: -12_50,
      currency: "USD",
      memo: "Coffee",
      category: "Living",
    },
  ],
};

const mutateAsync = vi.fn().mockResolvedValue({ updated: 1 });

vi.mock("../../hooks/useFinance", () => ({
  useAccountReconciliation: () => ({ data: summary, isLoading: false }),
  useReconcileTransactions: () => ({ mutateAsync, isPending: false }),
}));

describe("ReconcilePanel", () => {
  it("names the difference as the number to drive to zero", () => {
    render(<ReconcilePanel account={account} />);
    expect(screen.getByText("Reconcile with a statement")).toBeInTheDocument();
    expect(screen.getByText(/driving to zero/i)).toBeInTheDocument();
    expect(screen.getByText(/matches the statement/i)).toBeInTheDocument();
    expect(screen.getByText("Coffee")).toBeInTheDocument();
  });

  it("commits every ticked row in one request — the natural unit of the task", async () => {
    render(<ReconcilePanel account={account} />);
    fireEvent.click(screen.getByRole("checkbox", { name: /coffee/i }));
    fireEvent.click(screen.getByRole("button", { name: /mark 1 as cleared/i }));
    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({
        transaction_ids: ["tx1"],
        reconciled: true,
      }),
    );
  });
});
