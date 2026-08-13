import { Pause, Pencil, Play, Trash2 } from "lucide-react";
import { useState } from "react";
import type { Category, RecurringTransaction } from "../../api/types";
import { formatDate } from "../../lib/money";
import { ConfirmAction, IconButton, Money } from "../../ui";
import { annualMinor, cadenceLabel, monthlyMinor, recurringLabel } from "./recurringMath";

/**
 * One recurring charge, shown by its normalized monthly cost (with the annual
 * figure beneath) so expensive subscriptions are obvious. Pause stops future
 * charges reversibly; cancel removes the schedule after a one-tap confirm.
 */
export function SubscriptionRow({
  rec,
  categories,
  onSetActive,
  onCancel,
  onEdit,
}: {
  rec: RecurringTransaction;
  categories: Category[] | undefined;
  onSetActive: (recId: string, active: boolean) => Promise<unknown>;
  onCancel: (recId: string) => Promise<unknown>;
  /** Absent where the row is read-only (the dashboard strip, digests). */
  onEdit?: (rec: RecurringTransaction) => void;
}) {
  const label = recurringLabel(rec, categories);
  const monthly = monthlyMinor(rec);
  const annual = annualMinor(rec);
  const isIncome = rec.txn_type === "income";
  const isTransfer = rec.txn_type === "transfer";
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="lf-sub-row" data-paused={!rec.is_active}>
      <div className="lf-sub-main">
        <div className="lf-sub-name">{label}</div>
        <div className="lf-sub-meta">
          {isIncome ? "Income · " : isTransfer ? "Transfer / savings · " : ""}
          {cadenceLabel(rec)} · next {formatDate(rec.next_run_on)}
          {rec.ends_on ? ` · ends ${formatDate(rec.ends_on)}` : ""}
          {!rec.is_active ? " · paused" : ""}
        </div>
      </div>

      <div className="lf-sub-cost">
        <div className="lf-sub-cost-main">
          <Money amountMinor={monthly} currency={rec.currency} neutral />/mo
        </div>
        <div className="lf-sub-cost-sub">
          <Money amountMinor={annual} currency={rec.currency} neutral />/yr
        </div>
      </div>

      <span className="lf-sub-actions">
        {onEdit && (
          <IconButton
            label={`Edit ${label}`}
            icon={<Pencil size={15} strokeWidth={1.8} />}
            onClick={() => onEdit(rec)}
          />
        )}
        <IconButton
          label={rec.is_active ? `Pause ${label}` : `Resume ${label}`}
          icon={rec.is_active ? <Pause size={15} strokeWidth={1.8} /> : <Play size={15} strokeWidth={1.8} />}
          onClick={() => run(() => onSetActive(rec.id, !rec.is_active))}
          disabled={busy}
        />
        <ConfirmAction
          label={`Cancel ${label}`}
          icon={<Trash2 size={15} strokeWidth={1.8} />}
          confirmLabel="Cancel"
          cancelLabel="Keep"
          size="sm"
          onConfirm={() => onCancel(rec.id)}
        />
      </span>
    </div>
  );
}
