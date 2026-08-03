import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Category, FinancialAccount, Transaction } from "../../api/types";
import { TransactionTable } from "./TransactionTable";

const accounts: FinancialAccount[] = [
  { id: "acc", name: "Checking", account_type: "checking", currency: "USD", balance_minor: 0 },
];
const categories: Category[] = [
  { id: "grocery", name: "Groceries", kind: "expense", path: "Groceries", depth: 0, parent_id: null },
  { id: "salary", name: "Salary", kind: "income", path: "Salary", depth: 0, parent_id: null },
];

function txn(id: string, over: Partial<Transaction> = {}): Transaction {
  return {
    id,
    financial_account_id: "acc",
    amount_minor: -1200,
    currency: "USD",
    occurred_at: "2024-03-02T10:00:00Z",
    status: "posted",
    source: "manual",
    category_id: null,
    counter_account_id: null,
    transfer_group: null,
    memo: `Txn ${id}`,
    ...over,
  };
}

const rows = [txn("t1"), txn("t2"), txn("t3", { transfer_group: "grp" })];

function setup(selected: Set<string>, handlers: Partial<Record<string, ReturnType<typeof vi.fn>>> = {}) {
  const onToggle = handlers.onToggle ?? vi.fn();
  const onToggleAll = handlers.onToggleAll ?? vi.fn();
  const onOpen = handlers.onOpen ?? vi.fn();
  const onCategorize = handlers.onCategorize ?? vi.fn();
  render(
    <TransactionTable
      rows={rows}
      accounts={accounts}
      categories={categories}
      selected={selected}
      onToggle={onToggle}
      onToggleAll={onToggleAll}
      onOpen={onOpen}
      onCategorize={onCategorize}
    />,
  );
  return { onToggle, onToggleAll, onOpen, onCategorize };
}

describe("TransactionTable", () => {
  it("toggles a single row without opening the detail", () => {
    const { onToggle, onOpen } = setup(new Set());
    fireEvent.click(screen.getByRole("checkbox", { name: /select txn t1/i }));
    expect(onToggle).toHaveBeenCalledWith("t1");
    expect(onOpen).not.toHaveBeenCalled(); // checkbox click doesn't bubble to row
  });

  it("select-all is indeterminate when only some rows are selected", () => {
    setup(new Set(["t1"]));
    const all = screen.getByRole("checkbox", { name: /select all/i }) as HTMLInputElement;
    expect(all.indeterminate).toBe(true);
    expect(all.checked).toBe(false);
  });

  it("categorizes inline via the row's category select", () => {
    const { onCategorize } = setup(new Set());
    const select = screen.getByRole("combobox", { name: /category for txn t1/i });
    fireEvent.change(select, { target: { value: "grocery" } });
    expect(onCategorize).toHaveBeenCalledWith("t1", "grocery");
  });

  it("shows a plain Transfer label (no category picker) for transfers", () => {
    setup(new Set());
    expect(screen.queryByRole("combobox", { name: /category for txn t3/i })).not.toBeInTheDocument();
  });

  it("opens the detail when the row body is clicked", () => {
    const { onOpen } = setup(new Set());
    fireEvent.click(screen.getByText("Txn t2"));
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: "t2" }));
  });
});
