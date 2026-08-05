import { useState } from "react";
import { ApiError } from "../../api/client";
import type { IncomeFrequency, IncomeKind, Reliability } from "../../api/income";
import { useCreateIncomeSource } from "../../hooks/useIncome";
import { useAuth } from "../../lib/AuthContext";
import { CURRENCY_OPTIONS } from "../../lib/currencies";
import { Banner, Button, Card, Inline, Input, Select, Stack, Text } from "../../ui";
import {
  DAY_OF_MONTH_CADENCES,
  FREQUENCY_LABEL,
  KIND_LABEL,
  RELIABILITY_HELP,
  RELIABILITY_LABEL,
} from "./incomeCopy";

/** What each API field is called on this form, so a server-side rejection can
 * say which box to go and fix. A bare "Ensure this value is greater than or
 * equal to 1." names no field and leaves the user hunting. */
const FIELD_LABEL: Record<string, string> = {
  name: "Name",
  payer: "Paid by",
  currency: "Currency",
  net_minor: "Amount received",
  gross_minor: "Amount earned",
  frequency: "How often",
  pay_day: "Pay day",
  second_pay_day: "Second pay day",
  starts_on: "Starting from",
  reliability: "How reliable",
};

function describeApiError(err: ApiError): string {
  const entries = Object.entries(err.fieldErrors);
  if (entries.length === 0) return String(err.detail);
  return entries
    .map(([field, messages]) => `${FIELD_LABEL[field] ?? field}: ${messages.join(" ")}`)
    .join(" ");
}

/**
 * Add an income source.
 *
 * Two decisions in this form are worth defending.
 *
 * **Net is required, gross is not.** That is the opposite of how payroll
 * software models it and the right way round here: most people know exactly
 * what lands in their account and would have to go and find the gross.
 * Requiring the figure the user does not have is how a form goes unfilled.
 *
 * **Reliability is left blank by default** and filled from the kind by the
 * server. Pre-selecting "fixed" would put a confident projection behind
 * freelance income nobody promised, and a default the user did not choose is
 * still a claim the product made.
 */
export function CreateIncomeSourceForm({
  onCreated,
  onCancel,
}: {
  onCreated: () => void;
  onCancel: () => void;
}) {
  const { activeWorkspace } = useAuth();
  const create = useCreateIncomeSource();

  const [name, setName] = useState("");
  const [payer, setPayer] = useState("");
  const [kind, setKind] = useState<IncomeKind>("employment");
  const [frequency, setFrequency] = useState<IncomeFrequency>("monthly");
  const [reliability, setReliability] = useState<Reliability | "">("");
  const [net, setNet] = useState("");
  const [gross, setGross] = useState("");
  const [payDay, setPayDay] = useState("");
  const [secondPayDay, setSecondPayDay] = useState("");
  const [startsOn, setStartsOn] = useState(() => new Date().toISOString().slice(0, 10));
  const [error, setError] = useState<string | null>(null);

  const baseCurrency = activeWorkspace?.tenant.base_currency ?? "USD";
  const [currency, setCurrency] = useState(baseCurrency);
  const needsPayDay = DAY_OF_MONTH_CADENCES.includes(frequency);
  const needsSecondPayDay = frequency === "semi_monthly";

  const toMinor = (value: string): number | undefined => {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? Math.round(parsed * 100) : undefined;
  };

  /**
   * A day-of-month field as the API will accept it.
   *
   * `Number("")` is 0 and `"0"` is a truthy string, so the obvious
   * `field ? Number(field) : undefined` sent a literal 0 for any day the user
   * typed as 0 — and the server, which requires 1–28, rejected the whole form
   * with "Ensure this value is greater than or equal to 1." against a field
   * the message never named. Out-of-range input is reported here, in the
   * user's terms, instead of being posted and bounced.
   */
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
    // Gross is optional, but a gross that was *typed* has to be usable. An
    // unparseable or zero entry is the user meaning "none", not a figure to
    // post; anything else is checked here so the round-trip isn't wasted.
    const grossMinor = gross.trim() ? toMinor(gross) : undefined;
    if (gross.trim() && (!grossMinor || grossMinor <= 0)) {
      setError("Leave the amount earned blank if you don't know it, rather than entering zero.");
      return;
    }
    if (grossMinor && grossMinor < netMinor) {
      setError("What you earn before deductions can't be less than what lands in your account.");
      return;
    }
    const payDayValue = needsPayDay ? toDay(payDay) : undefined;
    const secondPayDayValue = needsSecondPayDay ? toDay(secondPayDay) : undefined;
    for (const [label, day] of [
      ["Pay day", payDayValue],
      ["Second pay day", secondPayDayValue],
    ] as const) {
      if (day !== undefined && (day < 1 || day > 28)) {
        setError(`${label} must be between 1 and 28, so it lands in every month.`);
        return;
      }
    }
    try {
      await create.mutateAsync({
        name,
        payer: payer || undefined,
        kind,
        currency,
        net_minor: netMinor,
        gross_minor: grossMinor,
        reliability: reliability || undefined,
        frequency,
        pay_day: payDayValue,
        second_pay_day: secondPayDayValue,
        starts_on: startsOn,
      });
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? describeApiError(err) : "Could not save this source.");
    }
  };

  return (
    <Card title="Add income">
      <form onSubmit={submit}>
        <Stack gap={4}>
          {error && <Banner tone="danger">{error}</Banner>}

          <Input
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Monthly salary"
            required
          />

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

          {/* Defaulted to the workspace base currency, because that is what
              nearly every source is paid in — but income is the one thing
              people are most likely to be paid in something else, so the
              choice is offered rather than assumed. It cannot be changed
              afterwards: receipts are already denominated in it. */}
          <Select
            label="Currency"
            hint="Defaults to your workspace currency. This can't be changed once the source is saved."
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            options={CURRENCY_OPTIONS}
          />

          <Input
            label={`Amount received (${currency})`}
            hint="What lands in your account, per payment"
            type="number"
            step="0.01"
            min="0.01"
            value={net}
            onChange={(e) => setNet(e.target.value)}
            required
          />

          <Input
            label={`Amount earned (${currency})`}
            hint="Before tax and deductions. Leave blank if you don't know it."
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
                hint="1–28, so it lands in every month"
                type="number"
                min="1"
                max="28"
                value={payDay}
                onChange={(e) => setPayDay(e.target.value)}
              />
              {needsSecondPayDay && (
                <Input
                  label="Second pay day"
                  hint="1–28"
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
            hint={
              reliability
                ? RELIABILITY_HELP[reliability]
                : "Left to us, this follows from the type you chose."
            }
            value={reliability}
            onChange={(e) => setReliability(e.target.value as Reliability | "")}
            options={[
              { value: "", label: "Decide from the type" },
              ...Object.entries(RELIABILITY_LABEL).map(([value, label]) => ({ value, label })),
            ]}
          />

          <Input
            label="Starting from"
            type="date"
            value={startsOn}
            onChange={(e) => setStartsOn(e.target.value)}
            required
          />

          <Text size="xs" tone="tertiary">
            Adding income here does not post anything to your ledger — it describes what you
            expect, so the cash-flow projection and the committed-income figure have something
            honest to work from.
          </Text>

          <Inline gap={2}>
            <Button type="submit" variant="primary" disabled={create.isPending}>
              {create.isPending ? "Saving…" : "Add income"}
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
