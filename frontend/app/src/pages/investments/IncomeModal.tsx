import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "../../api/client";
import type { FinancialAccount, HoldingValuation } from "../../api/types";
import { useRecordDividend, useRecordInterest } from "../../hooks/useInvestments";
import { majorToMinor } from "../../lib/money";
import {
  Banner,
  Button,
  Grid,
  Input,
  Modal,
  SegmentedControl,
  Select,
  Stack,
  Text,
  useToast,
} from "../../ui";

const schema = z.object({
  kind: z.enum(["interest", "dividend"]),
  security_id: z.string().min(1, "Pick a holding."),
  financial_account_id: z.string().min(1, "Where did the money land?"),
  amount: z
    .string()
    .min(1, "How much was paid?")
    .refine((v) => !Number.isNaN(Number(v)) && Number(v) > 0, "Enter an amount greater than zero."),
  occurred_on: z.string().optional(),
  memo: z.string().optional(),
});
type IncomeForm = z.infer<typeof schema>;

/**
 * Record income paid out by a holding.
 *
 * **Interest and dividends are kept apart** rather than collapsed into one
 * "income" button. They are taxed differently in most jurisdictions, and a
 * money-market fund paying monthly interest is a different cash-flow shape from
 * an equity paying a discretionary dividend twice a year — reporting has to be
 * able to tell them apart, so the entry point does too.
 *
 * Neither is added to cost basis: both are a return *on* the investment, not a
 * further investment in it. Reinvesting is two events — record the payment
 * here, then record the purchase it funded.
 */
export function IncomeModal({
  open,
  onClose,
  holdings,
  accounts,
}: {
  open: boolean;
  onClose: () => void;
  holdings: HoldingValuation[];
  accounts: FinancialAccount[];
}) {
  const recordInterest = useRecordInterest();
  const recordDividend = useRecordDividend();
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<IncomeForm>({
    resolver: zodResolver(schema),
    defaultValues: { kind: "interest", occurred_on: new Date().toISOString().slice(0, 10) },
  });
  const kind = watch("kind");

  const holdingOptions = holdings.map((h) => ({
    value: h.security_id,
    label: `${h.symbol} — ${h.security_name}`,
  }));
  const accountOptions = accounts.map((a) => ({ value: a.id, label: a.name }));

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    const payload = {
      security_id: values.security_id,
      financial_account_id: values.financial_account_id,
      amount_minor: majorToMinor(Number(values.amount)),
      occurred_on: values.occurred_on || undefined,
      memo: values.memo || undefined,
    };
    try {
      if (values.kind === "interest") await recordInterest.mutateAsync(payload);
      else await recordDividend.mutateAsync(payload);
      toast(values.kind === "interest" ? "Interest recorded" : "Dividend recorded");
      reset({ kind: values.kind, occurred_on: values.occurred_on });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't record that payment.");
    }
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="xl"
      title="Record a payment"
      description="Interest or a dividend paid out by something you hold. This posts to your ledger and shows up in cash flow."
      footerStart={
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
      }
      footer={
        <Button variant="primary" onClick={() => onSubmit()} loading={isSubmitting}>
          Record payment
        </Button>
      }
    >
      <form onSubmit={onSubmit} noValidate>
        <Stack gap={4}>
          {holdingOptions.length === 0 ? (
            <Banner tone="info">Record a purchase first — there's nothing paying out yet.</Banner>
          ) : (
            <>
              <SegmentedControl
                legend="Type"
                value={kind}
                onChange={(v) => setValue("kind", v)}
                options={[
                  { value: "interest", label: "Interest" },
                  { value: "dividend", label: "Dividend" },
                ]}
              />
              <Text tone="tertiary" size="xs">
                {kind === "interest"
                  ? "Money-market funds, bonds and deposits pay interest, usually on a fixed cycle."
                  : "Shares and equity funds pay dividends, usually when the company decides to."}
              </Text>

              <Select
                label="Holding"
                required
                placeholder="Choose a holding"
                options={holdingOptions}
                error={errors.security_id?.message}
                {...register("security_id")}
              />
              <Select
                label="Paid into"
                required
                placeholder="Choose an account"
                options={accountOptions}
                error={errors.financial_account_id?.message}
                {...register("financial_account_id")}
              />
              <Grid cols={2} gap={4}>
                <Input
                  label="Amount"
                  required
                  amount
                  type="number"
                  step="0.01"
                  min="0.01"
                  error={errors.amount?.message}
                  {...register("amount")}
                />
                <Input
                  label="Paid on"
                  type="date"
                  hint="Backdate it to keep the history straight."
                  {...register("occurred_on")}
                />
              </Grid>
              <Input label="Note" optional placeholder="e.g. Q1 coupon" {...register("memo")} />
              <Text tone="tertiary" size="xs">
                This is a return on the investment, so it doesn't change what the holding cost you.
                Reinvesting? Record the payment here, then record the purchase it paid for.
              </Text>
            </>
          )}

          {error && <Banner tone="danger">{error}</Banner>}
        </Stack>
      </form>
    </Modal>
  );
}
