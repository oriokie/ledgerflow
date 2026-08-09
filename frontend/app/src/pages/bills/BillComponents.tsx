import { Trash2 } from "lucide-react";
import { useState } from "react";
import type { Bill, FinancialAccount } from "../../api/types";
import { formatDateLong } from "../../lib/money";
import { Button, Card, ConfirmAction, Money } from "../../ui";
import { daysUntil, dueLabel, type BillTotals } from "./billsMath";

export function DuePill({ days }: { days: number }) {
  const { text, tone } = dueLabel(days);
  return (
    <span className="lf-due-pill" data-tone={tone}>
      {text}
    </span>
  );
}

export function BillRow({
  bill,
  accounts,
  asOf,
  onPay,
  onCancel,
}: {
  bill: Bill;
  accounts: FinancialAccount[] | undefined;
  asOf: Date;
  onPay: (billId: string, accountId: string) => Promise<unknown>;
  onCancel?: (billId: string) => Promise<unknown>;
}) {
  const [payFrom, setPayFrom] = useState("");
  const [busy, setBusy] = useState(false);
  const days = daysUntil(bill.due_on, asOf);

  const pay = async () => {
    const accountId = payFrom || accounts?.[0]?.id;
    if (!accountId) return;
    setBusy(true);
    try {
      await onPay(bill.id, accountId);
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!onCancel) return;
    await onCancel(bill.id);
  };

  return (
    <div className="lf-bill-row">
      <div className="lf-bill-main">
        <div className="lf-bill-name">{bill.name}</div>
        <div className="lf-sub-meta">{formatDateLong(bill.due_on)}</div>
      </div>
      <DuePill days={days} />
      <span className="lf-bill-amount">
        <Money amountMinor={bill.amount_minor} currency={bill.currency} neutral />
      </span>
      <span className="lf-bill-pay">
        {accounts && accounts.length > 0 && (
          <select className="lf-select" aria-label={`Pay ${bill.name} from`} value={payFrom} onChange={(e) => setPayFrom(e.target.value)}>
            <option value="">Select account…</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        )}
        <Button variant="secondary" size="sm" loading={busy} onClick={pay}>
          Mark paid
        </Button>
        {onCancel && (
          <ConfirmAction
            label={`Cancel ${bill.name}`}
            icon={<Trash2 size={15} strokeWidth={1.8} />}
            confirmLabel="Cancel bill"
            cancelLabel="Keep"
            size="sm"
            onConfirm={cancel}
          />
        )}
      </span>
    </div>
  );
}

export function BillGroup({
  title,
  tone,
  bills,
  accounts,
  asOf,
  onPay,
  onCancel,
}: {
  title: string;
  tone?: "danger" | "warning";
  bills: Bill[];
  accounts: FinancialAccount[] | undefined;
  asOf: Date;
  onPay: (billId: string, accountId: string) => Promise<unknown>;
  onCancel?: (billId: string) => Promise<unknown>;
}) {
  if (bills.length === 0) return null;
  return (
    <div>
      <div className="lf-group-head">
        <span className="lf-group-title" data-tone={tone}>
          {title}
        </span>
        <span className="lf-group-count">{bills.length}</span>
      </div>
      <Card>
        {bills.map((b) => (
          <BillRow key={b.id} bill={b} accounts={accounts} asOf={asOf} onPay={onPay} onCancel={onCancel} />
        ))}
      </Card>
    </div>
  );
}

export function BillsSummary({ totals, currency }: { totals: BillTotals; currency: string }) {
  return (
    <Card>
      <div className="lf-stat-band">
        <div className="lf-stat-band-item">
          <span className="lf-stat-label">Overdue{totals.overdue_count > 0 ? ` (${totals.overdue_count})` : ""}</span>
          <Money amountMinor={totals.overdue_minor} currency={currency} neutral hero />
        </div>
        <div className="lf-stat-band-divider" />
        <div className="lf-stat-band-item">
          <span className="lf-stat-label">Due this week</span>
          <Money amountMinor={totals.due7_minor} currency={currency} neutral />
        </div>
        <div className="lf-stat-band-divider" />
        <div className="lf-stat-band-item">
          <span className="lf-stat-label">Due in 30 days</span>
          <Money amountMinor={totals.due30_minor} currency={currency} neutral />
        </div>
      </div>
    </Card>
  );
}
