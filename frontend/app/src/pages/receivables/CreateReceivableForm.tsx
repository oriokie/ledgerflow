import { useState } from "react";
import { ApiError } from "../../api/client";
import type { ReceivableKind } from "../../api/receivables";
import { useCreateReceivable } from "../../hooks/useReceivables";
import { useAuth } from "../../lib/AuthContext";
import { CURRENCY_OPTIONS } from "../../lib/currencies";
import { Banner, Button, Card, Grid, Inline, Input, Select, Stack, Text } from "../../ui";
import { KIND_LABEL } from "./receivablesCopy";

/**
 * Record that someone owes you money.
 *
 * **A repayment date is optional**, and that is the important decision here.
 * Most informal lending has no date attached — you lend a friend money and it
 * comes back when it comes back. Requiring one would either block the entry or
 * invite a made-up date, and a made-up date produces a confident "14 days
 * overdue" that nobody actually agreed to. Where there's no date the list
 * falls back to how long the money has been out, which is honest and still
 * useful.
 */
export function CreateReceivableForm({
  onCreated,
  onCancel,
}: {
  onCreated: () => void;
  onCancel: () => void;
}) {
  const { activeWorkspace } = useAuth();
  const create = useCreateReceivable();

  const [counterparty, setCounterparty] = useState("");
  const [kind, setKind] = useState<ReceivableKind>("personal");
  const [description, setDescription] = useState("");
  const [currency, setCurrency] = useState(activeWorkspace?.tenant.base_currency ?? "USD");
  const [amount, setAmount] = useState("");
  const [lentOn, setLentOn] = useState(() => new Date().toISOString().slice(0, 10));
  const [dueOn, setDueOn] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    const parsed = Number.parseFloat(amount);
    const principalMinor = Number.isFinite(parsed) ? Math.round(parsed * 100) : 0;
    if (principalMinor <= 0) {
      setError("Enter how much they owe you.");
      return;
    }
    if (!counterparty.trim()) {
      setError("Say who owes it — a claim against nobody can't be chased.");
      return;
    }
    if (dueOn && dueOn < lentOn) {
      setError("A repayment date can't be before the money went out.");
      return;
    }
    try {
      await create.mutateAsync({
        counterparty: counterparty.trim(),
        kind,
        description: description || undefined,
        currency,
        principal_minor: principalMinor,
        lent_on: lentOn,
        due_on: dueOn || undefined,
      });
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Could not save this.");
    }
  };

  return (
    <Card title="Add what you're owed">
      <form onSubmit={submit}>
        <Stack gap={4}>
          {error && <Banner tone="danger">{error}</Banner>}

          <Grid cols={2} gap={4}>
            <Input
              label="Who owes you"
              value={counterparty}
              onChange={(e) => setCounterparty(e.target.value)}
              placeholder="A name — a friend, a client, an employer"
              required
            />
            <Select
              label="What kind"
              value={kind}
              onChange={(e) => setKind(e.target.value as ReceivableKind)}
              options={Object.entries(KIND_LABEL).map(([value, label]) => ({ value, label }))}
            />
          </Grid>

          <Grid cols={2} gap={4}>
            <Input
              label={`Amount (${currency})`}
              type="number"
              step="0.01"
              min="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              required
            />
            <Select
              label="Currency"
              hint="This can't be changed once there are repayments against it."
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              options={CURRENCY_OPTIONS}
            />
          </Grid>

          <Input
            label="What it was for"
            optional
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="e.g. Rent share, invoice #204"
          />

          <Grid cols={2} gap={4}>
            <Input
              label="Lent on"
              type="date"
              value={lentOn}
              onChange={(e) => setLentOn(e.target.value)}
              required
            />
            <Input
              label="Expected back"
              optional
              type="date"
              hint="Leave blank if nothing was agreed."
              value={dueOn}
              onChange={(e) => setDueOn(e.target.value)}
            />
          </Grid>

          <Text size="xs" tone="tertiary">
            This doesn't post anything to your ledger — the money already left your account when
            you lent it. What this adds is the record of where it went and whether it comes back.
          </Text>

          <Inline gap={2}>
            <Button type="submit" variant="primary" disabled={create.isPending}>
              {create.isPending ? "Saving…" : "Add"}
            </Button>
            <Button type="button" variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
          </Inline>
        </Stack>
      </form>
    </Card>
  );
}
