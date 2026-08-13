import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Category, FinancialAccount, Payee, Transaction } from "../../api/types";
import { TransactionTable } from "./TransactionTable";

const accounts: FinancialAccount[] = [
  { id: "acc", name: "Checking", account_type: "checking", currency: "USD", balance_minor: 0 },
];
const categories: Category[] = [
  { id: "grocery", name: "Groceries", kind: "expense", path: "Groceries", depth: 0, parent_id: null },
  { id: "salary", name: "Salary", kind: "income", path: "Salary", depth: 0, parent_id: null },
];
const payees: Payee[] = [{ id: "payee1", name: "Acme Corp" }];

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
    payee_id: null,
    counter_account_id: null,
    transfer_group: null,
    split_group: null,
    reconciled_at: null,
    memo: `Txn ${id}`,
    ...over,
  };
}

const rows = [txn("t1"), txn("t2"), txn("t3", { transfer_group: "grp" })];

function setup(
  selected: Set<string>,
  handlers: Partial<Record<string, ReturnType<typeof vi.fn>>> = {},
  overrideRows: Transaction[] = rows,
) {
  const onToggle = handlers.onToggle ?? vi.fn();
  const onToggleAll = handlers.onToggleAll ?? vi.fn();
  const onOpen = handlers.onOpen ?? vi.fn();
  const onCategorize = handlers.onCategorize ?? vi.fn();
  render(
    <TransactionTable
      rows={overrideRows}
      accounts={accounts}
      categories={categories}
      payees={payees}
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

describe("the ledger grid", () => {
  it("gives every fact its own column, so a column can be scanned down", () => {
    // The date and account used to sit in a stacked sub-line under the
    // description, which reads fine on a phone and makes the desktop table
    // impossible to scan the way a spreadsheet is scanned.
    setup(new Set());
    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent?.trim());
    expect(headers).toEqual(["", "Date", "Description", "Category", "Account", "Amount"]);
  });

  it("puts the date and the account in their own cells", () => {
    setup(new Set());
    const row = screen.getByText("Txn t1").closest("tr")!;
    const cells = within(row).getAllByRole("cell");
    // checkbox, date, description, category, account, amount
    expect(cells).toHaveLength(6);
    expect(cells[1]).toHaveTextContent("Mar 2");
    expect(cells[2]).toHaveTextContent("Txn t1");
    expect(cells[4]).toHaveTextContent("Checking");
  });

  it("still names both ends of a transfer, on the leg that shows it", () => {
    // A transfer posts as two rows, one per account. Naming both ends keeps
    // the pair legible without pretending it is a single row.
    setup(new Set());
    const row = screen.getByText("Txn t3").closest("tr")!;
    expect(within(row).getByText(/Transfer/)).toBeInTheDocument();
  });

  it("falls back to the payee name when there's no memo", () => {
    const noMemo = [txn("t4", { memo: "", payee_id: "payee1" })];
    setup(new Set(), {}, noMemo);
    expect(screen.getByText("Acme Corp")).toBeInTheDocument();
  });
});
