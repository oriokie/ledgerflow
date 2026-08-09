import type { FinancialAccount } from "../../api/types";
import { Card, Money } from "../../ui";
import { AccountTypeIcon } from "./AccountTypeIcon";
import { accountTypeLabel, groupAccounts } from "./summary";

function subtotal(accounts: FinancialAccount[], currency: string): number {
  return accounts
    .filter((a) => a.currency === currency)
    .reduce((sum, a) => sum + Math.abs(a.balance_minor), 0);
}

function AccountRow({
  account,
  selected,
  onSelect,
}: {
  account: FinancialAccount;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <button
      type="button"
      className="lf-acct-item"
      aria-current={selected}
      onClick={() => onSelect(account.id)}
    >
      <AccountTypeIcon type={account.account_type} />
      <span className="lf-acct-item-main">
        <span className="lf-acct-item-name">{account.name}</span>
        <span className="lf-acct-item-meta">
          {accountTypeLabel(account.account_type)}
          {account.mask ? ` · ••${account.mask}` : ""}
          {account.is_archived ? " · Inactive" : ""}
        </span>
      </span>
      <span className="lf-acct-item-balance">
        <Money amountMinor={account.balance_minor} currency={account.currency} neutral />
      </span>
    </button>
  );
}

/**
 * The account picker. Accounts are split into assets and liabilities, each with
 * a primary-currency subtotal, and the current selection is highlighted.
 */
export function AccountList({
  accounts,
  selectedId,
  onSelect,
  primaryCurrency,
}: {
  accounts: FinancialAccount[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  primaryCurrency: string;
}) {
  const { assets, liabilities } = groupAccounts(accounts);

  const groups: { label: string; items: FinancialAccount[] }[] = [
    { label: "Assets", items: assets },
    { label: "Liabilities", items: liabilities },
  ];

  return (
    <Card className="lf-acct-list" style={{ padding: "var(--lf-space-3)" }}>
      {groups
        .filter((g) => g.items.length > 0)
        .map((group) => (
          <div key={group.label} className="lf-acct-group">
            <div className="lf-acct-group-head">
              <span className="lf-acct-group-label">{group.label}</span>
              <span className="lf-acct-group-total">
                <Money amountMinor={subtotal(group.items, primaryCurrency)} currency={primaryCurrency} neutral />
              </span>
            </div>
            {group.items.map((a) => (
              <AccountRow
                key={a.id}
                account={a}
                selected={a.id === selectedId}
                onSelect={onSelect}
              />
            ))}
          </div>
        ))}
    </Card>
  );
}
