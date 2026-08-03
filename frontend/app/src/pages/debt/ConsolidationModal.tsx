import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { debtApi } from "../../api/debt";
import { ApiError } from "../../api/client";
import type { ConsolidationResult, DebtView } from "../../api/types";
import { formatAmountSigned, majorToMinor } from "../../lib/money";
import { Banner, Button, Checkbox, Grid, Input, Modal, Money, Stack, Text } from "../../ui";

const schema = z.object({
  new_apr: z
    .string()
    .min(1, "What rate is the loan?")
    .refine((v) => Number(v) >= 0 && Number(v) <= 100, "Enter it as a percentage, e.g. 9.9"),
  new_payment: z
    .string()
    .min(1, "What's the monthly payment?")
    .refine((v) => Number(v) > 0, "Must be greater than zero."),
  fees: z.string().optional(),
});
type ConsolidationForm = z.infer<typeof schema>;

/**
 * Consolidation simulator.
 *
 * Simulation only. The verdict is judged on **lifetime cost, never the monthly
 * payment** — consolidation almost always lowers the monthly figure, that's
 * its selling point, but stretching the term can raise the total even at a
 * lower rate. Showing both side by side is the only honest way to present it,
 * because the cheaper-looking option often isn't the cheaper one.
 */
export function ConsolidationModal({
  open,
  debts,
  onClose,
}: {
  open: boolean;
  debts: DebtView[];
  onClose: () => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<ConsolidationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ConsolidationForm>({ resolver: zodResolver(schema) });

  // Only debts with terms can be modelled; offering the rest would produce a
  // comparison against figures we don't have.
  const eligible = debts.filter((d) => d.has_terms && d.minimum_payment_minor > 0);
  const currency = eligible[0]?.currency ?? "USD";

  const toggle = (id: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const close = () => {
    setResult(null);
    setError(null);
    setSelected(new Set());
    onClose();
  };

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    setPending(true);
    try {
      const outcome = await debtApi.simulateConsolidation({
        account_ids: [...selected],
        new_apr: values.new_apr,
        new_minimum_payment_minor: majorToMinor(Number(values.new_payment)),
        fees_minor: values.fees ? majorToMinor(Number(values.fees)) : 0,
      });
      setResult(outcome);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't run that simulation.");
    } finally {
      setPending(false);
    }
  });

  return (
    <Modal
      open={open}
      onClose={close}
      size="xl"
      title="Combine debts into one loan?"
      description="Pick the debts and enter the loan you've been offered. Nothing changes — this only compares."
      footerStart={
        <Button variant="secondary" onClick={close}>
          Close
        </Button>
      }
      footer={
        <Button
          variant="primary"
          onClick={() => onSubmit()}
          loading={pending}
          disabled={selected.size < 2}
        >
          {result ? "Recalculate" : "Compare"}
        </Button>
      }
    >
      <form onSubmit={onSubmit} noValidate>
        <Stack gap={4}>
          {eligible.length < 2 ? (
            <Banner tone="info">
              You need at least two debts with a rate and minimum payment recorded before they can
              be combined.
            </Banner>
          ) : (
            <>
              <fieldset className="lf-consolidate-picker">
                <legend>Which debts?</legend>
                {eligible.map((debt) => (
                  <Checkbox
                    key={debt.account_id}
                    label={`${debt.name} — ${debt.apr}%`}
                    checked={selected.has(debt.account_id)}
                    onChange={() => toggle(debt.account_id)}
                  />
                ))}
                {selected.size === 1 && (
                  <Text tone="tertiary" size="xs">
                    Pick at least two — combining one debt isn't consolidation.
                  </Text>
                )}
              </fieldset>

              <Grid cols={2} gap={4}>
                <Input
                  label="Loan rate"
                  required
                  inputMode="decimal"
                  placeholder="9.9"
                  trailing="%"
                  error={errors.new_apr?.message}
                  {...register("new_apr")}
                />
                <Input
                  label="Monthly payment"
                  required
                  amount
                  inputMode="decimal"
                  placeholder="0.00"
                  error={errors.new_payment?.message}
                  {...register("new_payment")}
                />
              </Grid>

              <Input
                label="Arrangement fees"
                optional
                amount
                inputMode="decimal"
                placeholder="0.00"
                hint="Added to the new balance."
                {...register("fees")}
              />
            </>
          )}

          {result && (
            <div className="lf-refi-result" data-worthwhile={result.is_worthwhile || undefined}>
              <p className="lf-refi-verdict">
                {result.is_worthwhile
                  ? `Combining would save about ${formatAmountSigned(result.lifetime_saving_minor, currency)} overall.`
                  : `This lowers your monthly payment but costs about ${formatAmountSigned(Math.abs(result.lifetime_saving_minor), currency)} more overall.`}
              </p>

              {/* The trap consolidation adverts rely on, named explicitly. */}
              {!result.is_worthwhile && result.new_monthly_minor < result.current_monthly_minor && (
                <p className="lf-refi-caution">
                  A smaller monthly payment over a longer term can cost more in total, even at a
                  lower rate.
                </p>
              )}

              <dl className="lf-refi-figures">
                <div>
                  <dt>Monthly now</dt>
                  <dd>
                    <Money amountMinor={result.current_monthly_minor} currency={currency} neutral />
                  </dd>
                </div>
                <div>
                  <dt>Monthly after</dt>
                  <dd>
                    <Money amountMinor={result.new_monthly_minor} currency={currency} neutral />
                  </dd>
                </div>
                <div>
                  <dt>Total now</dt>
                  <dd>
                    <Money
                      amountMinor={result.current_total_cost_minor}
                      currency={currency}
                      neutral
                    />
                  </dd>
                </div>
                <div>
                  <dt>Total after</dt>
                  <dd>
                    <Money amountMinor={result.new_total_cost_minor} currency={currency} neutral />
                  </dd>
                </div>
              </dl>

              <Text tone="tertiary" size="xs">
                Replacing an average rate of {result.current_weighted_apr}% with {result.new_apr}%
                across {result.debt_count} debts.
              </Text>
            </div>
          )}

          {error && <Banner tone="danger">{error}</Banner>}
        </Stack>
      </form>
    </Modal>
  );
}
