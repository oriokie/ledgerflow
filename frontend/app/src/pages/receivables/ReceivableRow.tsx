import { Check, Trash2 } from "lucide-react";
import { useState } from "react";
import type { Receivable } from "../../api/receivables";
import {
  useDeleteReceivable,
  useRecordRepayment,
  useWriteOffReceivable,
} from "../../hooks/useReceivables";
import { formatAmount } from "../../lib/money";
import { Button, IconButton, Input, Text } from "../../ui";
import { ageNote } from "./receivablesCopy";

/**
 * One claim, with the two things you can do about it: record money coming
 * back, or give up on it.
 *
 * Repayment is inline rather than behind a modal because part-payments are the
 * norm with informal lending — someone hands you 2,000 of the 5,000 they owe —
 * and a modal for a single number is friction on the action this screen exists
 * to make easy.
 */
export function ReceivableRow({ row }: { row: Receivable }) {
  const recordRepayment = useRecordRepayment();
  const writeOff = useWriteOffReceivable();
  const remove = useDeleteReceivable();

  const [paying, setPaying] = useState(false);
  const [amount, setAmount] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const age = ageNote(row);
  const isClosed = row.status !== "outstanding";

  const submitRepayment = async () => {
    const parsed = Number.parseFloat(amount);
    const minor = Number.isFinite(parsed) ? Math.round(parsed * 100) : 0;
    if (minor <= 0) {
      setError("Enter how much came back.");
      return;
    }
    setError(null);
    await recordRepayment.mutateAsync({
      id: row.id,
      amount_minor: minor,
      received_on: new Date().toISOString().slice(0, 10),
    });
    setAmount("");
    setPaying(false);
  };

  return (
    <div className="lf-sub-row" data-paused={isClosed}>
      <div className="lf-sub-main">
        <div className="lf-sub-name">{row.counterparty}</div>
        <div className="lf-sub-meta">
          {row.description ? `${row.description} · ` : ""}
          <span className={`lf-tone-${age.tone}`}>{age.text}</span>
          {row.repaid_minor > 0 && row.status === "outstanding" && (
            <> · {formatAmount(row.repaid_minor, row.currency)} back so far</>
          )}
        </div>
        {paying && (
          <div className="lf-onboard-cta-row" style={{ marginTop: "var(--lf-space-2)" }}>
            <Input
              label="How much came back"
              type="number"
              step="0.01"
              min="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              error={error ?? undefined}
            />
            <Button
              variant="primary"
              size="sm"
              loading={recordRepayment.isPending}
              onClick={submitRepayment}
            >
              Record
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setPaying(false)}>
              Cancel
            </Button>
          </div>
        )}
      </div>

      <div className="lf-sub-cost">
        <div className="lf-sub-cost-main">
          {formatAmount(row.outstanding_minor, row.currency)}
        </div>
        {row.repaid_minor > 0 && (
          <div className="lf-sub-cost-sub">
            of {formatAmount(row.principal_minor, row.currency)}
          </div>
        )}
      </div>

      {confirmDelete ? (
        <span className="lf-sub-actions" style={{ alignItems: "center", gap: "var(--lf-space-2)" }}>
          <Button
            variant="danger"
            size="sm"
            loading={remove.isPending}
            onClick={() => remove.mutate(row.id)}
          >
            Delete
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>
            Keep
          </Button>
        </span>
      ) : (
        <span className="lf-sub-actions">
          {!isClosed && (
            <>
              <Button variant="secondary" size="sm" onClick={() => setPaying((v) => !v)}>
                Got paid
              </Button>
              {/* Writing off keeps the record. That a loan was never repaid is
                  worth remembering — for the user, and for anyone deciding
                  whether to lend to that person again. */}
              <Button
                variant="ghost"
                size="sm"
                loading={writeOff.isPending}
                onClick={() => writeOff.mutate(row.id)}
              >
                Write off
              </Button>
            </>
          )}
          {row.status === "settled" && (
            <Text as="span" tone="tertiary" size="sm">
              <Check size={14} aria-hidden="true" /> Settled
            </Text>
          )}
          <IconButton
            label={`Delete the record of ${row.counterparty}`}
            icon={<Trash2 size={15} strokeWidth={1.8} />}
            onClick={() => setConfirmDelete(true)}
          />
        </span>
      )}
    </div>
  );
}
