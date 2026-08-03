import { Receipt } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router-dom";
import type { Category, FinancialAccount, Transaction } from "../../api/types";
import { Card, EmptyState, Money } from "../../ui";

export function RecentActivity({
  transactions,
  accounts,
  categories,
  currency,
}: {
  transactions: Transaction[] | undefined;
  accounts: FinancialAccount[] | undefined;
  categories: Category[] | undefined;
  currency: string;
}) {
  const accountName = useMemo(() => {
    const m = new Map<string, string>();
    for (const a of accounts ?? []) m.set(a.id, a.name);
    return m;
  }, [accounts]);

  const categoryName = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of categories ?? []) m.set(c.id, c.name);
    return m;
  }, [categories]);

  const rows = (transactions ?? []).slice(0, 6);

  return (
    <Card
      title="Recent activity"
      action={
        <Link to="/transactions" className="lf-section-link">
          View all
        </Link>
      }
    >
      {rows.length === 0 ? (
        <EmptyState icon={Receipt} title="No transactions yet" body="Your latest activity will show up here." />
      ) : (
        <div className="lf-row-list">
          {rows.map((t) => {
            const cat = t.category_id ? categoryName.get(t.category_id) : null;
            const acct = accountName.get(t.financial_account_id);
            const title = t.memo?.trim() || cat || (t.transfer_group ? "Transfer" : "Transaction");
            const sub = [cat && cat !== title ? cat : null, acct, formatDay(t.occurred_at)]
              .filter(Boolean)
              .join(" · ");
            return (
              <div key={t.id} className="lf-row-item">
                <div className="lf-row-main">
                  <div className="lf-row-title">{title}</div>
                  <div className="lf-row-sub">{sub}</div>
                </div>
                <div className="lf-row-right">
                  <Money
                    amountMinor={t.amount_minor}
                    currency={t.currency || currency}
                    isTransfer={!!t.transfer_group}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

function formatDay(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
