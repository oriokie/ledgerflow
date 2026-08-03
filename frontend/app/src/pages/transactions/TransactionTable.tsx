import { useEffect, useMemo, useRef } from "react";
import type { Category, FinancialAccount, Transaction } from "../../api/types";
import { formatDate } from "../../lib/money";
import { Money } from "../../ui";

function describe(txn: Transaction, categoryName: string | undefined): string {
  return txn.memo?.trim() || categoryName || (txn.transfer_group ? "Transfer" : "Transaction");
}

/**
 * How settled this row is, as the ledger's own certainty signal.
 *
 * `pending` means the bank has observed the charge but not cleared it, so the
 * amount can still change. Rendering it identically to a reconciled figure
 * asks the reader to treat an estimate as a fact — the same mistake the Debt
 * score made. See docs/redesign/03-design-system.md §2.5.
 */
function certaintyOf(txn: Transaction): "settled" | "pending" {
  return txn.status === "pending" ? "pending" : "settled";
}

export function TransactionTable({
  rows,
  accounts,
  categories,
  selected,
  onToggle,
  onToggleAll,
  onOpen,
  onCategorize,
}: {
  rows: Transaction[];
  accounts: FinancialAccount[] | undefined;
  categories: Category[] | undefined;
  selected: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: () => void;
  onOpen: (txn: Transaction) => void;
  onCategorize: (txnId: string, categoryId: string | null) => void;
}) {
  const accountById = useMemo(() => new Map((accounts ?? []).map((a) => [a.id, a.name])), [accounts]);
  const categoryById = useMemo(() => new Map((categories ?? []).map((c) => [c.id, c.name])), [categories]);
  const expenseCats = useMemo(() => (categories ?? []).filter((c) => c.kind === "expense"), [categories]);
  const incomeCats = useMemo(() => (categories ?? []).filter((c) => c.kind === "income"), [categories]);

  const allSelected = rows.length > 0 && rows.every((r) => selected.has(r.id));
  const someSelected = rows.some((r) => selected.has(r.id));

  const headRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (headRef.current) headRef.current.indeterminate = someSelected && !allSelected;
  }, [someSelected, allSelected]);

  return (
    <div className="lf-table-wrap lf-table-wrap--sticky">
      <table className="lf-table lf-txn-table">
        <caption className="lf-visually-hidden">Transactions, newest first</caption>
        <thead>
          <tr>
            <th className="lf-txn-check" scope="col">
              <input
                ref={headRef}
                type="checkbox"
                aria-label="Select all on this page"
                checked={allSelected}
                onChange={onToggleAll}
              />
            </th>
            <th scope="col">Transaction</th>
            <th scope="col">Category</th>
            <th scope="col" className="lf-col-amount">
              Amount
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((txn) => {
            const isTransfer = !!txn.transfer_group;
            const catName = txn.category_id ? categoryById.get(txn.category_id) : undefined;
            const options = txn.amount_minor < 0 ? expenseCats : incomeCats;
            const account = accountById.get(txn.financial_account_id);
            const counterAccount = txn.counter_account_id
              ? accountById.get(txn.counter_account_id)
              : undefined;
            const certainty = certaintyOf(txn);
            return (
              <tr
                key={txn.id}
                data-selected={selected.has(txn.id)}
                data-certainty={certainty}
                onClick={() => onOpen(txn)}
                style={{ cursor: "pointer" }}
              >
                <td className="lf-txn-check" onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    aria-label={`Select ${describe(txn, catName)}`}
                    checked={selected.has(txn.id)}
                    onChange={() => onToggle(txn.id)}
                  />
                </td>
                <td>
                  <span className="lf-cell-primary">{describe(txn, catName)}</span>
                  <br />
                  <span className="lf-cell-meta">
                    {formatDate(txn.occurred_at)}
                    {account ? ` · ${account}` : ""}
                    {/* A transfer posts as two rows, one per account, which is
                        correct in the ledger and baffling in a list: the same
                        money appears twice with no indication the two are one
                        movement. Naming both ends on each leg makes the pair
                        legible without pretending it is a single row. */}
                    {isTransfer && counterAccount ? (
                      <>
                        {" "}
                        <span aria-hidden="true">⇄</span> {counterAccount}
                      </>
                    ) : null}
                  </span>
                </td>
                <td className="lf-txn-cat" onClick={(e) => e.stopPropagation()}>
                  {isTransfer ? (
                    <span className="lf-cell-meta">Transfer</span>
                  ) : (
                    <select
                      className="lf-select lf-txn-cat-select"
                      aria-label={`Category for ${describe(txn, catName)}`}
                      value={txn.category_id ?? ""}
                      onChange={(e) => onCategorize(txn.id, e.target.value || null)}
                    >
                      <option value="">Uncategorized</option>
                      {options.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  )}
                </td>
                <td className="lf-col-amount">
                  <Money amountMinor={txn.amount_minor} currency={txn.currency} isTransfer={isTransfer} />
                  {certainty === "pending" && (
                    <span className="lf-txn-pending">
                      Pending
                      <span className="lf-visually-hidden"> — not yet cleared, this amount can still change</span>
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
