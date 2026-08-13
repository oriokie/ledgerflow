import { useState } from "react";
import { ApiError } from "../../api/client";
import { useRecordReceipt } from "../../hooks/useIncome";
import { Banner, Button, Inline, Input, Stack, useToast } from "../../ui";

const FIELD_LABEL: Record<string, string> = {
  occurred_on: "Date",
  net_minor: "Amount received",
  gross_minor: "Amount earned",
  memo: "Note",
};

function describeApiError(err: ApiError): string {
  const entries = Object.entries(err.fieldErrors);
  if (entries.length === 0) return String(err.detail);
  return entries
    .map(([field, messages]) => `${FIELD_LABEL[field] ?? field}: ${messages.join(" ")}`)
    .join(" ");
}

/**
 * Record a single payment against an income source.
 *
 * This is the other half of the card's headline claim. "Expected" only ever
 * becomes a measured figure — `expected_is_observed`, the averaged amount,
 * the variance — once receipts exist to derive it from; until then it is
 * either what the user typed or, for an irregular source, a guess. This form
 * is the only way a receipt gets created, so it is what turns the card from
 * a promise into a record.
 *
 * Three fields, matching what `record_receipt` actually asks for: the
 * amount, when it arrived, and an optional note. Gross is deliberately
 * omitted here — the create form already treats it as a rarely-known,
 * optional figure, and a receipt is even more likely to be logged from a
 * bank line that only shows the net.
 */
export function RecordReceiptForm({
  sourceId,
  currency,
  onDone,
  onCancel,
}: {
  sourceId: string;
  currency: string;
  onDone: () => void;
  onCancel: () => void;
}) {
  const recordReceipt = useRecordReceipt();
  const toast = useToast();

  const [occurredOn, setOccurredOn] = useState(() => new Date().toISOString().slice(0, 10));
  const [amount, setAmount] = useState("");
  const [memo, setMemo] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    const parsed = Number.parseFloat(amount);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      setError("Enter what you were actually paid.");
      return;
    }
    const netMinor = Math.round(parsed * 100);
    try {
      await recordReceipt.mutateAsync({
        sourceId,
        occurred_on: occurredOn,
        net_minor: netMinor,
        memo: memo.trim() || undefined,
      });
      toast("Payment recorded", { tone: "success" });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? describeApiError(err) : "Couldn't record that payment.");
    }
  };

  return (
    <form onSubmit={submit}>
      <Stack gap={3} style={{ marginTop: "var(--lf-space-3)" }}>
        {error && <Banner tone="danger">{error}</Banner>}
        <Inline gap={2} wrap align="start">
          <Input
            label={`Amount received (${currency})`}
            type="number"
            step="0.01"
            min="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            required
            autoFocus
          />
          <Input
            label="Date"
            type="date"
            value={occurredOn}
            onChange={(e) => setOccurredOn(e.target.value)}
            required
          />
        </Inline>
        <Input
          label="Note"
          optional
          value={memo}
          onChange={(e) => setMemo(e.target.value)}
          placeholder="e.g. arrived a day late"
        />
        <Inline gap={2}>
          <Button type="submit" variant="secondary" size="sm" disabled={recordReceipt.isPending}>
            {recordReceipt.isPending ? "Saving…" : "Save payment"}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
        </Inline>
      </Stack>
    </form>
  );
}
