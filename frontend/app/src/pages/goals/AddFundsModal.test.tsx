import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FinancialAccount, SavingsGoal } from "../../api/types";

const mutateAsync = vi.fn().mockResolvedValue({});
vi.mock("../../hooks/useGoals", () => ({
  useContributeToGoal: () => ({ mutateAsync, isPending: false }),
}));

let accounts: FinancialAccount[] = [];
vi.mock("../../hooks/useFinance", () => ({
  useAccounts: () => ({ data: accounts }),
}));

import { AddFundsModal } from "./AddFundsModal";

function account(over: Partial<FinancialAccount> = {}): FinancialAccount {
  return {
    id: "a1",
    name: "Checking",
    account_type: "checking",
    currency: "USD",
    balance_minor: 500_00,
    ...over,
  };
}

function goal(over: Partial<SavingsGoal> = {}): SavingsGoal {
  return {
    id: "g1",
    name: "Japan trip",
    kind: "vacation",
    currency: "USD",
    target_minor: 1000_00,
    target_date: null,
    priority: 3,
    tracking: "manual",
    linked_account_id: null,
    status: "active",
    notes: "",
    saved_minor: 100_00,
    remaining_minor: 900_00,
    percent: 10,
    is_met: false,
    required_monthly_minor: null,
    planned_monthly_minor: null,
    auto_contribute_enabled: false,
    auto_contribute_minor: null,
    auto_contribute_day: null,
    ...over,
  };
}

function setAmount(value: string) {
  fireEvent.change(screen.getByLabelText(/amount to add/i), { target: { value } });
}

beforeEach(() => {
  mutateAsync.mockClear();
  accounts = [
    account(),
    account({ id: "a2", name: "Savings", account_type: "savings", balance_minor: 200_00 }),
  ];
});

describe("AddFundsModal", () => {
  it("defaults to tracking, and says plainly that no balance changes", async () => {
    render(<AddFundsModal open onClose={() => {}} goal={goal()} />);
    setAmount("50");

    expect(await screen.findByText(/no account balance changes/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /add funds/i }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    // The default must not move money — that's the invariant the old inline
    // quick-add relied on and users depend on.
    expect(mutateAsync.mock.calls[0][0]).toMatchObject({
      goalId: "g1",
      amountMinor: 50_00,
      fromAccountId: undefined,
    });
  });

  it("sends the funding account when the user chooses to move money", async () => {
    render(<AddFundsModal open onClose={() => {}} goal={goal({ linked_account_id: "a2" })} />);
    setAmount("50");
    fireEvent.click(screen.getByRole("radio", { name: /move the money now/i }));
    fireEvent.change(screen.getByRole("combobox", { name: /from/i }), { target: { value: "a1" } });

    fireEvent.click(screen.getByRole("button", { name: /transfer and add/i }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    expect(mutateAsync.mock.calls[0][0]).toMatchObject({
      amountMinor: 50_00,
      fromAccountId: "a1",
    });
  });

  it("previews the source balance dropping before the user commits", () => {
    render(<AddFundsModal open onClose={() => {}} goal={goal({ linked_account_id: "a2" })} />);
    setAmount("50");
    fireEvent.click(screen.getByRole("radio", { name: /move the money now/i }));
    fireEvent.change(screen.getByRole("combobox", { name: /from/i }), { target: { value: "a1" } });

    // 500.00 -> 450.00 on the source, 100.00 -> 150.00 on the goal.
    expect(screen.getByText(/450\.00/)).toBeInTheDocument();
    expect(screen.getByText(/150\.00/)).toBeInTheDocument();
  });

  it("refuses to transfer without a named source", async () => {
    render(<AddFundsModal open onClose={() => {}} goal={goal({ linked_account_id: "a2" })} />);
    setAmount("50");
    fireEvent.click(screen.getByRole("radio", { name: /move the money now/i }));

    fireEvent.click(screen.getByRole("button", { name: /transfer and add/i }));
    expect(await screen.findByText(/which account the money is coming from/i)).toBeInTheDocument();
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("excludes accounts in another currency, which the API would refuse anyway", () => {
    accounts = [account(), account({ id: "a3", name: "Euro pot", currency: "EUR" })];
    render(<AddFundsModal open onClose={() => {}} goal={goal({ linked_account_id: "a1" })} />);
    fireEvent.click(screen.getByRole("radio", { name: /move the money now/i }));

    expect(screen.queryByRole("option", { name: /Euro pot/i })).not.toBeInTheDocument();
  });

  it("disables transferring when there's nowhere to move money between", () => {
    accounts = [account()];
    render(<AddFundsModal open onClose={() => {}} goal={goal()} />);
    // One account and no linked destination: tracking still works, funding can't.
    expect(screen.getByRole("radio", { name: /move the money now/i })).toBeDisabled();
  });

  it("warns when the transfer would overdraw the source but still allows it", () => {
    render(<AddFundsModal open onClose={() => {}} goal={goal({ linked_account_id: "a2" })} />);
    setAmount("900");
    fireEvent.click(screen.getByRole("radio", { name: /move the money now/i }));
    fireEvent.change(screen.getByRole("combobox", { name: /from/i }), { target: { value: "a1" } });

    expect(screen.getByText(/leave it overdrawn/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /transfer and add/i })).not.toBeDisabled();
  });
});
