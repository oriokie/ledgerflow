import { Check, Pause, Pencil, Play, Trash2 } from "lucide-react";
import { useState } from "react";
import type { Category, RecurringTransaction } from "../../api/types";
import { formatDate } from "../../lib/money";
import { Button, ConfirmAction, IconButton, Inline, Input, Money } from "../../ui";
import { annualMinor, cadenceLabel, isPeriodical, recognizedMinor, recurringLabel } from "./recurringMath";

/**
 * One recurring charge, shown by the amount that actually lands (the block
 * for quarterly/yearly, a monthly rate for weekly/monthly) so the cash hit
 * is not hidden behind an average.
 */
export function SubscriptionRow({
  rec,
  categories,
  onSetActive,
  onCancel,
  onConfirm,
  onEdit,
}: {
  rec: RecurringTransaction;
  categories: Category[] | undefined;
  onSetActive: (recId: string, active: boolean) => Promise<unknown>;
  onCancel: (recId: string) => Promise<unknown>;
  /** Mark the next occurrence paid/received with an exact amount. */
  onConfirm?: (recId: string, amountMinor: number) => Promise<unknown>;
  /** Absent where the row is read-only (the dashboard strip, digests). */
  onEdit?: (rec: RecurringTransaction) => void;
}) {
  const label = recurringLabel(rec, categories);
  const amount = recognizedMinor(rec);
  const annual = annualMinor(rec);
  const perMonth = !isPeriodical(rec);
  const isIncome = rec.txn_type === "income";
  const isTransfer = rec.txn_type === "transfer";
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [paidAmount, setPaidAmount] = useState(() => (rec.amount_minor / 100).toFixed(2));

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  const confirmLabel = isIncome ? "Mark received" : isTransfer ? "Mark done" : "Mark paid";

  const submitConfirm = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!onConfirm) return;
    const parsed = Number.parseFloat(paidAmount);
    if (!Number.isFinite(parsed) || parsed <= 0) return;
    setBusy(true);
    try {
      await onConfirm(rec.id, Math.round(parsed * 100));
      setConfirming(false);
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
        {confirming && onConfirm && (
          <form onSubmit={submitConfirm} style={{ marginTop: "var(--lf-space-2)" }}>
            <Inline gap={2} wrap align="end">
              <Input
                label={`Amount (${rec.currency})`}
                type="number"
                step="0.01"
                min="0.01"
                value={paidAmount}
                onChange={(e) => setPaidAmount(e.target.value)}
                required
                autoFocus
              />
              <Button type="submit" variant="secondary" size="sm" disabled={busy} loading={busy}>
                {confirmLabel}
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={() => setConfirming(false)}>
                Cancel
              </Button>
            </Inline>
          </form>
        )}
      </div>

      <div className="lf-sub-cost">
        <div className="lf-sub-cost-main">
          <Money amountMinor={amount} currency={rec.currency} neutral />
          {perMonth ? "/mo" : ""}
        </div>
        <div className="lf-sub-cost-sub">
          <Money amountMinor={annual} currency={rec.currency} neutral />/yr
        </div>
      </div>

      <span className="lf-sub-actions">
        {onConfirm && rec.is_active && !confirming && (
          <IconButton
            label={`${confirmLabel} ${label}`}
            icon={<Check size={15} strokeWidth={1.8} />}
            onClick={() => {
              setPaidAmount((rec.amount_minor / 100).toFixed(2));
              setConfirming(true);
            }}
            disabled={busy}
          />
        )}
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
