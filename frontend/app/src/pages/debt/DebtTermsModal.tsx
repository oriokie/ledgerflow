import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "../../api/client";
import type { DebtView } from "../../api/types";
import { useSetDebtTerms } from "../../hooks/useDebt";
import { majorToMinor, minorToMajor } from "../../lib/money";
import { Banner, Button, Grid, Input, Modal, Select, Stack, Text } from "../../ui";

const COMPOUNDING = [
  { value: "monthly", label: "Monthly (most common)" },
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "quarterly", label: "Quarterly" },
  { value: "annual", label: "Annually" },
];

const KINDS = [
  { value: "credit_card", label: "Credit card" },
  { value: "mortgage", label: "Mortgage" },
  { value: "personal_loan", label: "Personal loan" },
  { value: "student_loan", label: "Student loan" },
  { value: "vehicle loan", label: "Vehicle loan" },
  { value: "bnpl", label: "Buy now, pay later" },
  { value: "other", label: "Other" },
];

const schema = z.object({
  debt_kind: z.string().min(1),
  apr: z
    .string()
    .min(1, "What rate are you charged?")
    .refine((v) => Number(v) >= 0 && Number(v) <= 100, "Enter it as a percentage, e.g. 19.9"),
  minimum: z
    .string()
    .min(1, "What's the minimum payment?")
    .refine((v) => Number(v) >= 0, "Can't be negative."),
  original_principal: z.string().optional(),
  payment_day: z.string().optional(),
  compounding: z.string().optional(),
  monthly_fee: z.string().optional(),
  annual_fee: z.string().optional(),
  annual_fee_month: z.string().optional(),
});
type TermsForm = z.infer<typeof schema>;

/**
 * Repayment terms for one debt.
 *
 * Terms are the contract, not a transaction — saving them moves no money and
 * posts nothing to the ledger. Said plainly in the modal, because "record my
 * credit card" could reasonably be read as recording a payment.
 */
export function DebtTermsModal({
  debt,
  onClose,
}: {
  debt: DebtView | null;
  onClose: () => void;
}) {
  const setTerms = useSetDebtTerms();
  const [error, setError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<TermsForm>({
    resolver: zodResolver(schema),
    values: debt
      ? {
          debt_kind: debt.debt_kind,
          apr: debt.apr ? String(debt.apr) : "",
          minimum: debt.minimum_payment_minor
            ? String(minorToMajor(debt.minimum_payment_minor))
            : "",
          original_principal: debt.original_principal_minor
            ? String(minorToMajor(debt.original_principal_minor))
            : "",
          payment_day: debt.payment_day ? String(debt.payment_day) : "",
          compounding: debt.compounding ?? "monthly",
          monthly_fee: debt.fees?.monthly_minor
            ? String(minorToMajor(debt.fees.monthly_minor))
            : "",
          annual_fee: debt.fees?.annual_minor
            ? String(minorToMajor(debt.fees.annual_minor))
            : "",
          annual_fee_month: "",
        }
      : undefined,
  });

  const onSubmit = handleSubmit(async (values) => {
    if (!debt) return;
    setError(null);
    try {
      await setTerms.mutateAsync({
        accountId: debt.account_id,
        payload: {
          debt_kind: values.debt_kind,
          apr: values.apr,
          minimum_payment_minor: majorToMinor(Number(values.minimum)),
          original_principal_minor: values.original_principal
            ? majorToMinor(Number(values.original_principal))
            : null,
          payment_day: values.payment_day ? Number(values.payment_day) : null,
          compounding: values.compounding || "monthly",
          monthly_fee_minor: values.monthly_fee ? majorToMinor(Number(values.monthly_fee)) : 0,
          annual_fee_minor: values.annual_fee ? majorToMinor(Number(values.annual_fee)) : 0,
          annual_fee_month: values.annual_fee_month
            ? Number(values.annual_fee_month)
            : undefined,
        },
      });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't save those terms.");
    }
  });

  return (
    <Modal
      open={debt !== null}
      onClose={onClose}
      size="xl"
      title={debt ? `Terms for ${debt.name}` : "Debt terms"}
      description="The rate and minimum payment. Saving these doesn't move any money — it's what your payoff plan is worked out from."
      footerStart={
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
      }
      footer={
        <Button variant="primary" onClick={() => onSubmit()} loading={isSubmitting}>
          Save terms
        </Button>
      }
    >
      <form onSubmit={onSubmit} noValidate>
        <Stack gap={4}>
          <Select label="Type of debt" required options={KINDS} {...register("debt_kind")} />

          <Grid cols={2} gap={4}>
            <Input
              label="Interest rate"
              required
              inputMode="decimal"
              placeholder="19.9"
              trailing="%"
              hint="The APR on your statement."
              error={errors.apr?.message}
              {...register("apr")}
            />
            <Input
              label="Minimum payment"
              required
              amount
              inputMode="decimal"
              placeholder="0.00"
              hint="What you must pay each month to stay current."
              error={errors.minimum?.message}
              {...register("minimum")}
            />
          </Grid>

          <Grid cols={2} gap={4}>
            <Input
              label="Original amount"
              optional
              amount
              inputMode="decimal"
              placeholder="0.00"
              hint="Lets us show how far through you are."
              {...register("original_principal")}
            />
            <Input
              label="Payment day"
              optional
              inputMode="numeric"
              placeholder="15"
              hint="Day of the month, 1–28."
              {...register("payment_day")}
            />
          </Grid>

          {/* Progressive disclosure: compounding and fees matter enormously for
              a few products and not at all for most, so they're one click away
              rather than cluttering the common case. */}
          <details className="lf-terms-advanced">
            <summary>Interest and fees</summary>
            <Stack gap={4}>
              <Select
                label="Interest compounds"
                options={COMPOUNDING}
                hint="Daily compounding costs slightly more than monthly at the same rate."
                {...register("compounding")}
              />

              <Grid cols={2} gap={4}>
                <Input
                  label="Monthly fee"
                  optional
                  amount
                  inputMode="decimal"
                  placeholder="0.00"
                  hint="Servicing or maintenance charges."
                  {...register("monthly_fee")}
                />
                <Input
                  label="Annual fee"
                  optional
                  amount
                  inputMode="decimal"
                  placeholder="0.00"
                  hint="Charged once a year."
                  {...register("annual_fee")}
                />
              </Grid>

              <Text tone="tertiary" size="xs">
                Fees are added to what you owe rather than reducing it, so they're shown apart from
                interest in your borrowing cost.
              </Text>
            </Stack>
          </details>

          <Text tone="tertiary" size="xs">
            Your balance comes from your transactions and isn't edited here.
          </Text>

          {error && <Banner tone="danger">{error}</Banner>}
        </Stack>
      </form>
    </Modal>
  );
}
