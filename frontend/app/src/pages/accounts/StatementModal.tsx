import { endOfMonth, format, startOfMonth } from "date-fns";
import { useMemo } from "react";
import type { FinancialAccount, StatementLine } from "../../api/types";
import { useAccountStatement } from "../../hooks/useFinance";
import { formatDate } from "../../lib/money";
import { Modal, Money, Skeleton, Stack, Table, Text } from "../../ui";
import type { Column } from "../../ui";
import { statementSummary } from "./summary";

/** The full month statement for one account: opening balance, every line with a
 * running balance, and an in/out footer. */
export function StatementModal({ account, onClose }: { account: FinancialAccount; onClose: () => void }) {
  const now = useMemo(() => new Date(), []);
  const start = useMemo(() => startOfMonth(now).toISOString(), [now]);
  const end = useMemo(() => endOfMonth(now).toISOString(), [now]);
  const { data, isLoading } = useAccountStatement(account.id, start, end);
  const summary = useMemo(() => statementSummary(data?.lines), [data]);

  const columns: Column<StatementLine>[] = [
    { key: "date", header: "Date", render: (l) => <span className="lf-cell-meta">{formatDate(l.occurred_at)}</span> },
    { key: "memo", header: "Memo", render: (l) => l.memo?.trim() || (l.transfer_group ? "Transfer" : "—") },
    {
      key: "amount",
      header: "Amount",
      align: "right",
      render: (l) => <Money amountMinor={l.amount_minor} currency={l.currency} isTransfer={!!l.transfer_group} />,
    },
    {
      key: "balance",
      header: "Balance",
      align: "right",
      render: (l) => <Money amountMinor={l.running_balance_minor} currency={l.currency} neutral />,
    },
  ];

  return (
    <Modal open onClose={onClose} title={`${account.name} — ${format(now, "MMMM yyyy")}`} size="lg">
      {isLoading && <Skeleton width="60%" />}
      {data && (
        <Stack gap={3}>
          <div className="lf-meter-row">
            <Text tone="tertiary" size="sm">
              Opening balance
            </Text>
            <Money amountMinor={data.opening_balance_minor} currency={account.currency} neutral />
          </div>

          {data.lines.length === 0 ? (
            <Text tone="secondary">No activity this month.</Text>
          ) : (
            <>
              <div style={{ maxHeight: 360, overflowY: "auto" }}>
                <Table columns={columns} rows={data.lines} rowKey={(l) => l.id} responsive={false} caption="Statement lines" />
              </div>
              <div className="lf-meter-row" style={{ borderTop: "1px solid var(--lf-border-subtle)", paddingTop: "var(--lf-space-2)" }}>
                <Text tone="secondary" size="sm">
                  {data.lines.length} transactions
                </Text>
                <span style={{ display: "inline-flex", gap: "var(--lf-space-4)" }}>
                  <Money amountMinor={summary.in_minor} currency={account.currency} neutral className="lf-amount--in" />
                  <Money amountMinor={summary.out_minor} currency={account.currency} neutral className="lf-amount--out" />
                </span>
              </div>
            </>
          )}
        </Stack>
      )}
    </Modal>
  );
}
