import { useState } from "react";
import { ApiError } from "../../api/client";
import { useAccounts } from "../../hooks/useFinance";
import { useRecordReceipt } from "../../hooks/useIncome";
import { Banner, Button, Inline, Input, Select, Stack, useToast } from "../../ui";

const FIELD_LABEL: Record<string, string> = {
  occurred_on: "Date",
  net_minor: "Amount received",
  gross_minor: "Amount earned",
  deposit_account_id: "Account",
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
 * Posts to the ledger so the arrival appears on Transactions. Recording a
 * payment creates a receipt and a transaction only — it does not change the
 * income source's planned amount or other details.
 */
export function RecordReceiptForm({
  sourceId,
  currency,
  statedNetMinor,
  depositAccountId,
  onDone,
  onCancel,
}: {
  sourceId: string;
  currency: string;
  statedNetMinor?: number;
  depositAccountId?: string | null;
  onDone: () => void;
  onCancel: () => void;
}) {
  const recordReceipt = useRecordReceipt();
  const { data: accounts } = useAccounts();
  const toast = useToast();

  const matchingAccounts = (accounts ?? []).filter((a) => a.currency === currency && !a.is_archived);
  const defaultAccount =
    (depositAccountId && matchingAccounts.find((a) => a.id === depositAccountId)?.id) ||
    matchingAccounts[0]?.id ||
    "";

  const [occurredOn, setOccurredOn] = useState(() => new Date().toISOString().slice(0, 10));
  const [amount, setAmount] = useState(() =>
    statedNetMinor != null ? (statedNetMinor / 100).toFixed(2) : "",
  );
  const [accountId, setAccountId] = useState(defaultAccount);
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
    if (!accountId) {
      setError("Choose which account this payment landed in.");
      return;
    }
    const netMinor = Math.round(parsed * 100);
    try {
      await recordReceipt.mutateAsync({
        sourceId,
        occurred_on: occurredOn,
        net_minor: netMinor,
        deposit_account_id: accountId,
        memo: memo.trim() || undefined,
      });
      toast("Payment recorded on Transactions", { tone: "success" });
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
        <Select
          label="Deposited to"
          hint="Creates the matching income on your Transactions page."
          value={accountId}
          onChange={(e) => setAccountId(e.target.value)}
          options={[
            { value: "", label: "Select account…" },
            ...matchingAccounts.map((a) => ({ value: a.id, label: a.name })),
          ]}
          required
        />
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
