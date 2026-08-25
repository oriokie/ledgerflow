import { useState } from "react";
import { ApiError } from "../../api/client";
import type { IncomeFrequency, IncomeKind, IncomeSource, Reliability } from "../../api/income";
import { useAccounts } from "../../hooks/useFinance";
import { useUpdateIncomeSource } from "../../hooks/useIncome";
import { Banner, Button, Card, Inline, Input, Select, Stack, Text } from "../../ui";
import {
  DAY_OF_MONTH_CADENCES,
  FREQUENCY_LABEL,
  KIND_LABEL,
  RELIABILITY_HELP,
  RELIABILITY_LABEL,
} from "./incomeCopy";

const FIELD_LABEL: Record<string, string> = {
  name: "Name",
  payer: "Paid by",
  net_minor: "Amount received",
  gross_minor: "Amount earned",
  frequency: "How often",
  pay_day: "Pay day",
  second_pay_day: "Second pay day",
  starts_on: "Starting from",
  ends_on: "Ending on",
  reliability: "How reliable",
};

function describeApiError(err: ApiError): string {
  const entries = Object.entries(err.fieldErrors);
  if (entries.length === 0) return String(err.detail);
  return entries
    .map(([field, messages]) => `${FIELD_LABEL[field] ?? field}: ${messages.join(" ")}`)
    .join(" ");
}

/** Edit an existing income source without touching receipt history. */
export function EditIncomeSourceForm({
  source,
  onDone,
  onCancel,
}: {
  source: IncomeSource;
  onDone: () => void;
  onCancel: () => void;
}) {
  const update = useUpdateIncomeSource();
  const { data: accounts } = useAccounts();

  const [name, setName] = useState(source.name);
  const [payer, setPayer] = useState(source.payer);
  const [kind, setKind] = useState<IncomeKind>(source.kind);
  const [frequency, setFrequency] = useState<IncomeFrequency>(source.frequency);
  const [reliability, setReliability] = useState<Reliability>(source.reliability);
  const [net, setNet] = useState((source.stated_net_minor / 100).toFixed(2));
  const [gross, setGross] = useState(
    source.stated_gross_minor != null ? (source.stated_gross_minor / 100).toFixed(2) : "",
  );
  const [payDay, setPayDay] = useState(source.pay_day != null ? String(source.pay_day) : "");
  const [secondPayDay, setSecondPayDay] = useState(
    source.second_pay_day != null ? String(source.second_pay_day) : "",
  );
  const [startsOn, setStartsOn] = useState(source.starts_on);
  const [endsOn, setEndsOn] = useState(source.ends_on ?? "");
  const [depositAccountId, setDepositAccountId] = useState(source.deposit_account_id ?? "");
  const [error, setError] = useState<string | null>(null);

  const currency = source.currency;
  const needsPayDay = DAY_OF_MONTH_CADENCES.includes(frequency);
  const needsSecondPayDay = frequency === "semi_monthly";
  const matchingAccounts = (accounts ?? []).filter((a) => a.currency === currency && !a.is_archived);

  const toMinor = (value: string): number | undefined => {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? Math.round(parsed * 100) : undefined;
  };

  const toDay = (value: string): number | undefined => {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : undefined;
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    const netMinor = toMinor(net);
    if (!netMinor || netMinor <= 0) {
      setError("Enter what actually lands in your account.");
      return;
    }
    const grossMinor = gross.trim() ? toMinor(gross) : null;
    if (gross.trim() && (!grossMinor || grossMinor <= 0)) {
      setError("Leave the amount earned blank if you don't know it.");
      return;
    }
    if (grossMinor && grossMinor < netMinor) {
      setError("What you earn before deductions can't be less than what lands in your account.");
      return;
    }
    const payDayValue = needsPayDay ? toDay(payDay) : null;
    const secondPayDayValue = needsSecondPayDay ? toDay(secondPayDay) : null;
    try {
      await update.mutateAsync({
        sourceId: source.id,
        payload: {
          name,
          payer: payer || undefined,
          kind,
          net_minor: netMinor,
          gross_minor: grossMinor,
          reliability,
          frequency,
          pay_day: payDayValue,
          second_pay_day: secondPayDayValue,
          starts_on: startsOn,
          ends_on: endsOn.trim() ? endsOn : null,
          deposit_account_id: depositAccountId || undefined,
        },
      });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? describeApiError(err) : "Could not save changes.");
    }
  };

  return (
    <Card title={`Edit ${source.name}`}>
      <form onSubmit={submit}>
        <Stack gap={4}>
          {error && <Banner tone="danger">{error}</Banner>}

          <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} required />

          <Input
            label="Paid by"
            optional
            value={payer}
            onChange={(e) => setPayer(e.target.value)}
            placeholder="Employer or client"
          />

          <Select
            label="Type"
            value={kind}
            onChange={(e) => setKind(e.target.value as IncomeKind)}
            options={Object.entries(KIND_LABEL).map(([value, label]) => ({ value, label }))}
          />

          <Text size="sm" tone="tertiary">
            Currency: {currency} (cannot be changed once saved)
          </Text>

          <Input
            label={`Amount received (${currency})`}
            type="number"
            step="0.01"
            min="0.01"
            value={net}
            onChange={(e) => setNet(e.target.value)}
            required
          />

          <Input
            label={`Amount earned (${currency})`}
            optional
            type="number"
            step="0.01"
            min="0.01"
            value={gross}
            onChange={(e) => setGross(e.target.value)}
          />

          <Select
            label="How often"
            value={frequency}
            onChange={(e) => setFrequency(e.target.value as IncomeFrequency)}
            options={Object.entries(FREQUENCY_LABEL).map(([value, label]) => ({ value, label }))}
          />

          {needsPayDay && (
            <Inline gap={3}>
              <Input
                label="Pay day"
                type="number"
                min="1"
                max="28"
                value={payDay}
                onChange={(e) => setPayDay(e.target.value)}
              />
              {needsSecondPayDay && (
                <Input
                  label="Second pay day"
                  type="number"
                  min="1"
                  max="28"
                  value={secondPayDay}
                  onChange={(e) => setSecondPayDay(e.target.value)}
                />
              )}
            </Inline>
          )}

          <Select
            label="How reliable"
            hint={RELIABILITY_HELP[reliability]}
            value={reliability}
            onChange={(e) => setReliability(e.target.value as Reliability)}
            options={Object.entries(RELIABILITY_LABEL).map(([value, label]) => ({ value, label }))}
          />

          <Input label="Starting from" type="date" value={startsOn} onChange={(e) => setStartsOn(e.target.value)} required />

          <Input
            label="Ending on"
            type="date"
            optional
            value={endsOn}
            onChange={(e) => setEndsOn(e.target.value)}
          />

          <Select
            label="Usually deposits to"
            optional
            hint="Default account when you record a payment."
            value={depositAccountId}
            onChange={(e) => setDepositAccountId(e.target.value)}
            options={[
              { value: "", label: "Choose each time" },
              ...matchingAccounts.map((a) => ({ value: a.id, label: a.name })),
            ]}
          />

          <Inline gap={2}>
            <Button type="submit" variant="primary" disabled={update.isPending}>
              {update.isPending ? "Saving…" : "Save changes"}
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
