import { endOfMonth, format, startOfMonth } from "date-fns";
import { ArrowLeft, ChevronLeft, ChevronRight, FileText } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router-dom";
import type { FinancialAccount, Wallet } from "../../api/types";
import { useAccountStatement } from "../../hooks/useFinance";
import { formatDate } from "../../lib/money";
import { Badge, Button, Card, Figure, FigureRow, IconButton, Money, Select, Skeleton, Text } from "../../ui";
import { AccountTypeIcon } from "./AccountTypeIcon";
import { accountTypeLabel, statementSummary } from "./summary";

const RECENT_LIMIT = 8;

/**
 * An asset account holding less than nothing is almost always a data problem —
 * a missing deposit, a duplicated expense, an import that ran twice — not a
 * fact about the user's money. It was rendering silently, which leaves the
 * reader to notice a minus sign and work out on their own whether it is
 * plausible. Liabilities are excluded: owing money on a card is the normal
 * case, not an anomaly.
 */
function isImplausiblyNegative(account: FinancialAccount): boolean {
  const liability = account.account_type === "credit_card" || account.account_type === "loan";
  return !liability && account.balance_minor < 0;
}

export function AccountDetail({
  account,
  accounts,
  wallets,
  onSelect,
  onBack,
  onAssignWallet,
  onOpenStatement,
}: {
  account: FinancialAccount;
  accounts: FinancialAccount[];
  wallets: Wallet[] | undefined;
  onSelect: (id: string) => void;
  onBack: () => void;
  onAssignWallet: (accountId: string, walletId: string | null) => void;
  onOpenStatement: () => void;
}) {
  const now = useMemo(() => new Date(), []);
  const start = useMemo(() => startOfMonth(now).toISOString(), [now]);
  const end = useMemo(() => endOfMonth(now).toISOString(), [now]);
  const { data: statement, isLoading } = useAccountStatement(account.id, start, end);

  const summary = useMemo(() => statementSummary(statement?.lines), [statement]);
  const recent = useMemo(
    () => (statement?.lines ?? []).slice(-RECENT_LIMIT).reverse(),
    [statement],
  );

  const index = accounts.findIndex((a) => a.id === account.id);
  const prev = index > 0 ? accounts[index - 1] : null;
  const next = index >= 0 && index < accounts.length - 1 ? accounts[index + 1] : null;

  return (
    <Card>
      {/* Header */}
      <div className="lf-acct-detail-head">
        <Button
          variant="ghost"
          size="sm"
          className="lf-acct-back"
          icon={<ArrowLeft size={16} strokeWidth={1.8} />}
          onClick={onBack}
        >
          Accounts
        </Button>
        <AccountTypeIcon type={account.account_type} size="lg" />
        <div className="lf-acct-detail-titles">
          {/* An <h2>, not a <div>: this is the page's primary content, and it
              was absent from the heading outline entirely — a screen reader
              got "h1 Accounts → h2 Wallets" and nothing for the account
              actually being read. */}
          <h2 className="lf-acct-detail-name">{account.name}</h2>
          <div className="lf-acct-detail-meta">
            <span>{accountTypeLabel(account.account_type)}</span>
            <Badge tone="neutral">{account.currency}</Badge>
            {account.mask && <span>••{account.mask}</span>}
          </div>
        </div>
        <div className="lf-acct-nav">
          <IconButton
            label="Previous account"
            variant="ghost"
            disabled={!prev}
            onClick={() => prev && onSelect(prev.id)}
            icon={<ChevronLeft size={18} strokeWidth={1.8} />}
          />
          <IconButton
            label="Next account"
            variant="ghost"
            disabled={!next}
            onClick={() => next && onSelect(next.id)}
            icon={<ChevronRight size={18} strokeWidth={1.8} />}
          />
        </div>
      </div>

      {/* Balance */}
      <div style={{ marginTop: "var(--lf-space-4)" }}>
        <Figure
          label="Current balance"
          size="hero"
          amountMinor={account.balance_minor}
          currency={account.currency}
          neutral
          hint={
            isImplausiblyNegative(account) ? (
              <Badge tone="warning">
                Below zero — check for a missing deposit or a double-counted expense
              </Badge>
            ) : undefined
          }
        />
      </div>

      {/* This-month transaction summary */}
      <div style={{ marginTop: "var(--lf-space-5)" }}>
        <div className="lf-section-head">
          <Text tone="secondary" size="sm" style={{ fontWeight: "var(--lf-weight-semibold)" }}>
            {format(now, "MMMM")} activity
          </Text>
          <Link className="lf-section-link" to={`/transactions?account=${account.id}`}>
            Open in Transactions
          </Link>
        </div>
        {/* Was three <Card>s wrapping a local StatTile — the fifth private
            implementation of the labelled number in this codebase, and three
            bordered boxes nested inside the card that already contains them. */}
        <FigureRow>
          <Figure label="In" amountMinor={summary.in_minor} currency={account.currency} neutral tone="positive" />
          <Figure label="Out" amountMinor={summary.out_minor} currency={account.currency} neutral />
          <Figure
            label="Net"
            amountMinor={summary.net_minor}
            currency={account.currency}
            tone={summary.net_minor < 0 ? "critical" : "default"}
          />
        </FigureRow>
      </div>

      {/* Actions */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--lf-space-2)", marginTop: "var(--lf-space-5)", alignItems: "center" }}>
        <Button variant="secondary" size="sm" icon={<FileText size={15} strokeWidth={1.8} />} onClick={onOpenStatement}>
          Full statement
        </Button>
        {wallets && wallets.length > 0 && (
          <Select
            aria-label={`Assign ${account.name} to a wallet`}
            defaultValue=""
            style={{ maxWidth: 200 }}
            onChange={(e) => onAssignWallet(account.id, e.target.value || null)}
            options={[{ value: "", label: "Assign to wallet…" }, ...wallets.map((w) => ({ value: w.id, label: w.name }))]}
          />
        )}
      </div>

      {/* Recent transactions */}
      <div style={{ marginTop: "var(--lf-space-6)" }}>
        <div className="lf-section-head">
          <Text tone="secondary" size="sm" style={{ fontWeight: "var(--lf-weight-semibold)" }}>
            Recent transactions
          </Text>
        </div>
        {isLoading ? (
          <Skeleton width="70%" />
        ) : recent.length === 0 ? (
          <Text tone="tertiary" size="sm">
            No activity this month.
          </Text>
        ) : (
          <div className="lf-row-list">
            {recent.map((l) => (
              <div key={l.id} className="lf-row-item">
                <div className="lf-row-main">
                  <div className="lf-row-title">{l.memo?.trim() || (l.transfer_group ? "Transfer" : "Transaction")}</div>
                  <div className="lf-row-sub">{formatDate(l.occurred_at)}</div>
                </div>
                <div className="lf-row-right">
                  <Money amountMinor={l.amount_minor} currency={l.currency} isTransfer={!!l.transfer_group} />
                  <div className="lf-row-sub" style={{ marginTop: 1 }}>
                    Balance <Money amountMinor={l.running_balance_minor} currency={l.currency} neutral />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
