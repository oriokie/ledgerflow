import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { FinancialAccount } from "../../api/types";
import { AccountList } from "./AccountList";

const ACCOUNTS: FinancialAccount[] = [
  { id: "chk", name: "Everyday Checking", account_type: "checking", currency: "USD", balance_minor: 250_00 },
  { id: "sav", name: "Rainy Day", account_type: "savings", currency: "USD", balance_minor: 900_00 },
  { id: "cc", name: "Travel Card", account_type: "credit_card", currency: "USD", balance_minor: -120_00 },
];

describe("AccountList", () => {
  it("groups into assets and liabilities and renders each account", () => {
    render(<AccountList accounts={ACCOUNTS} selectedId="chk" onSelect={() => {}} primaryCurrency="USD" />);
    expect(screen.getByText("Assets")).toBeInTheDocument();
    expect(screen.getByText("Liabilities")).toBeInTheDocument();
    expect(screen.getByText("Everyday Checking")).toBeInTheDocument();
    expect(screen.getByText("Travel Card")).toBeInTheDocument();
  });

  it("marks the selected account with aria-current", () => {
    render(<AccountList accounts={ACCOUNTS} selectedId="sav" onSelect={() => {}} primaryCurrency="USD" />);
    const selected = screen.getByText("Rainy Day").closest("button")!;
    expect(selected).toHaveAttribute("aria-current", "true");
    const other = screen.getByText("Everyday Checking").closest("button")!;
    expect(other).toHaveAttribute("aria-current", "false");
  });

  it("calls onSelect with the account id when a row is clicked", () => {
    const onSelect = vi.fn();
    render(<AccountList accounts={ACCOUNTS} selectedId="chk" onSelect={onSelect} primaryCurrency="USD" />);
    fireEvent.click(screen.getByText("Travel Card").closest("button")!);
    expect(onSelect).toHaveBeenCalledWith("cc");
  });

  it("marks a deactivated account as inactive", () => {
    const withInactive: FinancialAccount[] = [
      ...ACCOUNTS,
      { id: "old", name: "Closed Savings", account_type: "savings", currency: "USD", balance_minor: 0, is_archived: true },
    ];
    render(<AccountList accounts={withInactive} selectedId="chk" onSelect={() => {}} primaryCurrency="USD" />);
    expect(screen.getByText(/Inactive/)).toBeInTheDocument();
  });
});
