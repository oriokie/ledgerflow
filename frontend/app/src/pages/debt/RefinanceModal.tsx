import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "../../api/client";
import type { DebtView, RefinanceResult } from "../../api/types";
import { useSimulateRefinance } from "../../hooks/useDebt";
import { formatAmountSigned, majorToMinor, minorToMajor } from "../../lib/money";
import { Banner, Button, Grid, Input, Modal, Money, Stack, Text } from "../../ui";

const schema = z.object({
  new_apr: z
    .string()
    .min(1, "What rate are you being offered?")
    .refine((v) => Number(v) >= 0 && Number(v) <= 100, "Enter it as a percentage, e.g. 6.9"),
  new_payment: z
    .string()
    .min(1, "What would the monthly payment be?")
    .refine((v) => Number(v) > 0, "Must be greater than zero."),
  closing_costs: z.string().optional(),
  capitalise: z.boolean().optional(),
});
type RefinanceForm = z.infer<typeof schema>;

function months(n: number | null): string {
  if (n === null) return "—";
  if (n < 12) return `${n} months`;
  const years = Math.floor(n / 12);
  const rest = n % 12;
  return rest ? `${years}y ${rest}m` : `${years} years`;
}

/**
 * Refinance simulator.
 *
 * Simulation only — nothing about the existing debt changes, and the modal
 * says so, because "record a refinance" could reasonably be read as applying
 * one.
 *
 * The result leads with **breakeven**, not the lifetime saving. A lower rate
 * always flatters the total-interest figure, but closing costs are paid up
 * front: a deal that saves money over twenty years can cost money over three,
 * and if the user expects to move or repay before breakeven the saving never
 * arrives at all.
 */
export function RefinanceModal({ debt, onClose }: { debt: DebtView | null; onClose: () => void }) {
  const simulate = useSimulateRefinance();
  const [result, setResult] = useState<RefinanceResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RefinanceForm>({
    resolver: zodResolver(schema),
    values: debt
      ? {
          new_apr: "",
          new_payment: debt.minimum_payment_minor
            ? String(minorToMajor(debt.minimum_payment_minor))
            : "",
          closing_costs: "",
          capitalise: true,
        }
      : undefined,
  });

  const close = () => {
    setResult(null);
    setError(null);
    onClose();
  };

  const onSubmit = handleSubmit(async (values) => {
    if (!debt) return;
    setError(null);
    try {
      const outcome = await simulate.mutateAsync({
        accountId: debt.account_id,
        payload: {
          new_apr: values.new_apr,
          new_minimum_payment_minor: majorToMinor(Number(values.new_payment)),
          closing_costs_minor: values.closing_costs
            ? majorToMinor(Number(values.closing_costs))
            : 0,
          capitalise_costs: values.capitalise ?? true,
        },
      });
      setResult(outcome);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't run that simulation.");
    }
  });

  const currency = debt?.currency ?? "USD";

  return (
    <Modal
      open={debt !== null}
      onClose={close}
      size="xl"
      title={debt ? `Refinance ${debt.name}?` : "Refinance"}
      description="Enter the terms you've been offered. Nothing about your existing debt changes — this only compares."
      footerStart={
        <Button variant="secondary" onClick={close}>
          Close
        </Button>
      }
      footer={
        <Button variant="primary" onClick={() => onSubmit()} loading={isSubmitting}>
          {result ? "Recalculate" : "Compare"}
        </Button>
      }
    >
      <form onSubmit={onSubmit} noValidate>
        <Stack gap={4}>
          <Grid cols={2} gap={4}>
            <Input
              label="New rate"
              required
              inputMode="decimal"
              placeholder="6.9"
              trailing="%"
              hint={debt ? `You currently pay ${debt.apr}%.` : undefined}
              error={errors.new_apr?.message}
              {...register("new_apr")}
            />
            <Input
              label="New monthly payment"
              required
              amount
              inputMode="decimal"
              placeholder="0.00"
              error={errors.new_payment?.message}
              {...register("new_payment")}
            />
          </Grid>

          <Input
            label="Fees and closing costs"
            optional
            amount
            inputMode="decimal"
            placeholder="0.00"
            hint="Arrangement, valuation, legal — anything you'd pay to switch."
            {...register("closing_costs")}
          />

          {result && (
            <div className="lf-refi-result" data-worthwhile={result.is_worthwhile || undefined}>
              <p className="lf-refi-verdict">
                {result.is_worthwhile
                  ? `Switching would save about ${formatAmountSigned(result.lifetime_saving_minor, currency)} over the life of the debt.`
                  : result.lifetime_saving_minor > 0
                    ? "This costs less overall, but never quite pays back the fees."
                    : `This would cost about ${formatAmountSigned(Math.abs(result.lifetime_saving_minor), currency)} more overall.`}
              </p>

              <dl className="lf-refi-figures">
                <div>
                  {/* Leading figure: a saving that arrives after you've moved
                      or repaid is not a saving. */}
                  <dt>Breakeven</dt>
                  <dd>
                    {result.breakeven_month === null
                      ? "Never"
                      : `Month ${result.breakeven_month}`}
                  </dd>
                </div>
                <div>
                  <dt>Time saved</dt>
                  <dd>
                    {result.months_saved === null
                      ? "—"
                      : result.months_saved > 0
                        ? `${result.months_saved} months`
                        : "None"}
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
                Paying off in {months(result.current_months)} now, {months(result.new_months)} after.
                {result.breakeven_month !== null &&
                  ` If you expect to repay or move before month ${result.breakeven_month}, switching costs you money.`}
              </Text>
            </div>
          )}

          {error && <Banner tone="danger">{error}</Banner>}
        </Stack>
      </form>
    </Modal>
  );
}
