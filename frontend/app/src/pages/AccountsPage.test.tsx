import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { FinancialAccount } from "../api/types";

const accounts: FinancialAccount[] = [
  { id: "chk", name: "Everyday Checking", account_type: "checking", currency: "USD", balance_minor: 250_00 },
  { id: "cc", name: "Travel Card", account_type: "credit_card", currency: "USD", balance_minor: -120_00 },
];

vi.mock("../hooks/useFinance", () => ({
  useAccounts: () => ({ data: accounts, isLoading: false }),
  useWallets: () => ({ data: [] }),
  useCreateAccount: () => ({ mutateAsync: vi.fn() }),
  useCreateWallet: () => ({ mutateAsync: vi.fn() }),
  useAssignAccountToWallet: () => ({ mutate: vi.fn() }),
  useAccountStatement: () => ({ data: { opening_balance_minor: 0, lines: [] }, isLoading: false }),
  useUpdateAccount: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useArchiveAccount: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUnarchiveAccount: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteAccount: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock("../hooks/useLedger", () => ({ useLedgerAccounts: () => ({ data: undefined }) }));
vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ activeWorkspace: { role: "owner", tenant: { id: "t1", base_currency: "USD" } } }),
}));

import { AccountsPage } from "./AccountsPage";

describe("AccountsPage", () => {
  it("shows the balance summary, the account list, and the selected account's detail", () => {
    render(
      <MemoryRouter>
        <AccountsPage />
      </MemoryRouter>,
    );

    // Summary bar (labels also repeat as list group headers — expect ≥1)
    expect(screen.getAllByText("Assets").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Liabilities").length).toBeGreaterThan(0);
    expect(screen.getByText("Net worth")).toBeInTheDocument();

    // Detail panel for the auto-selected (first) account
    expect(screen.getByText("Current balance")).toBeInTheDocument();
    expect(screen.getByText(/no activity this month/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /full statement/i })).toBeInTheDocument();

    // Both accounts are reachable in the list.
    expect(screen.getAllByText("Everyday Checking").length).toBeGreaterThan(0);
    expect(screen.getByText("Travel Card")).toBeInTheDocument();
  });
});
