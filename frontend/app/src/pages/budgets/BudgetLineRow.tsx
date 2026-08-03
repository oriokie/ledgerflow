import { Check, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import type { BudgetLineStatus } from "../../api/types";
import { formatAmount, majorToMinor, minorToMajor } from "../../lib/money";
import { Button, IconButton, Input, Money } from "../../ui";
import { BudgetProgressBar } from "./BudgetProgressBar";
import { lineState } from "./budgetMath";

const STATE_LABEL: Record<string, string> = { under: "on track", warning: "nearing limit", over: "over budget" };

/**
 * One budgeted category: figures, the state-coloured progress bar with the pace
 * marker, and fast in-place editing — click the pencil to change the limit, the
 * trash to remove (with a one-tap confirm). Both call back to the page's
 * mutations and show their own busy state.
 */
export function BudgetLineRow({
  line,
  currency,
  pacePercent,
  paceJudgeable = true,
  onUpdateLimit,
  onRemove,
}: {
  line: BudgetLineStatus;
  currency: string;
  pacePercent: number;
  /** False early in the period, when "on track" is true by construction. */
  paceJudgeable?: boolean;
  onUpdateLimit: (lineId: string, limitMinor: number) => Promise<unknown>;
  onRemove: (lineId: string) => Promise<unknown>;
}) {
  const state = lineState(line);
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [busy, setBusy] = useState(false);

  const startEdit = () => {
    setValue(String(minorToMajor(line.limit_minor)));
    setEditing(true);
  };

  const save = async () => {
    const n = Number(value);
    if (Number.isNaN(n) || n < 0) return;
    setBusy(true);
    try {
      await onUpdateLimit(line.line_id, majorToMinor(n));
      setEditing(false);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await onRemove(line.line_id);
    } finally {
      setBusy(false);
      setConfirmRemove(false);
    }
  };

  return (
    <div className="lf-budget-line">
      <div className="lf-budget-line-head">
        <span className="lf-budget-line-name">{line.category_name}</span>
        <span className="lf-budget-line-figures">
          <Money amountMinor={line.actual_minor} currency={currency} neutral /> of{" "}
          {formatAmount(line.effective_limit_minor, currency)}
        </span>
      </div>

      <BudgetProgressBar
        percentUsed={line.percent_used}
        state={state}
        pacePercent={pacePercent}
        ariaLabel={`${line.category_name}: ${Math.round(line.percent_used)}% of budget used`}
      />

      {editing ? (
        <div className="lf-budget-edit">
          <Input
            label=""
            aria-label={`New limit for ${line.category_name}`}
            amount
            type="number"
            step="0.01"
            min="0"
            autoFocus
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") save();
              if (e.key === "Escape") setEditing(false);
            }}
          />
          <Button variant="primary" size="sm" icon={<Check size={15} strokeWidth={2} />} loading={busy} onClick={save}>
            Save
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        </div>
      ) : (
        <div className="lf-budget-line-foot">
          <span className="lf-budget-line-status" data-tone={state === "under" ? undefined : state}>
            {state === "over"
              ? `Over by ${formatAmount(line.actual_minor - line.effective_limit_minor, currency)}`
              : // "on track" is a pace claim, and early in a period it is
                // true of every line regardless of behaviour. The remaining
                // figure is a fact and always shows; only the verdict waits.
                `${formatAmount(line.remaining_minor, currency)} left${
                  state === "under" && !paceJudgeable ? "" : ` · ${STATE_LABEL[state]}`
                }`}
            {line.carried_minor > 0 ? ` · incl. ${formatAmount(line.carried_minor, currency)} rollover` : ""}
          </span>

          {confirmRemove ? (
            <span className="lf-budget-line-actions" style={{ alignItems: "center", gap: "var(--lf-space-2)" }}>
              <span className="lf-budget-line-status">Remove?</span>
              <Button variant="danger" size="sm" loading={busy} onClick={remove}>
                Remove
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setConfirmRemove(false)}>
                Keep
              </Button>
            </span>
          ) : (
            <span className="lf-budget-line-actions">
              <IconButton label={`Edit ${line.category_name} limit`} icon={<Pencil size={15} strokeWidth={1.8} />} onClick={startEdit} />
              <IconButton label={`Remove ${line.category_name}`} icon={<Trash2 size={15} strokeWidth={1.8} />} onClick={() => setConfirmRemove(true)} />
            </span>
          )}
        </div>
      )}
    </div>
  );
}
