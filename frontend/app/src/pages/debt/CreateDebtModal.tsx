import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "../../api/client";
import { useCreateDebt } from "../../hooks/useDebt";
import { useAuth } from "../../lib/AuthContext";
import { CURRENCY_OPTIONS } from "../../lib/currencies";
import { majorToMinor } from "../../lib/money";
import { Banner, Button, Grid, Input, Modal, Select, Stack, Text } from "../../ui";

const KINDS = [
  { value: "credit_card", label: "Credit card" },
  { value: "personal_loan", label: "Personal loan" },
  { value: "mortgage", label: "Mortgage" },
  { value: "vehicle loan", label: "Vehicle loan" },
  { value: "student_loan", label: "Student loan" },
  { value: "bnpl", label: "Buy now, pay later" },
  { value: "other", label: "Money owed to someone" },
];

const schema = z.object({
  name: z.string().min(1, "Give it a name you'll recognise."),
  debt_kind: z.string().min(1),
  lender: z.string().optional(),
  currency: z.string().length(3),
  balance: z
    .string()
    .min(1, "How much is owed?")
    .refine((v) => !Number.isNaN(Number(v)) && Number(v) >= 0, "Enter the amount owed."),
  apr: z
    .string()
    .optional()
    .refine((v) => !v || (Number(v) >= 0 && Number(v) <= 100), "Enter it as a percentage, e.g. 19.9"),
  minimum: z
    .string()
    .optional()
    .refine((v) => !v || Number(v) >= 0, "Can't be negative."),
  payment_day: z
    .string()
    .optional()
    .refine((v) => !v || (Number(v) >= 1 && Number(v) <= 28), "Pick a day from 1 to 28."),
});
type DebtForm = z.infer<typeof schema>;

/**
 * Add a debt.
 *
 * This replaces sending the user to `/accounts?add=1`, which is what made
 * "Add a credit card or loan" look broken: it opened a generic account form,
 * created something with no terms, and left the debt planner still empty.
 *
 * **Only the name and the amount are required.** A debt to a friend has no APR,
 * no minimum payment and no statement day, and demanding them would either
 * block the entry or invite invented figures — and an invented APR silently
 * corrupts every payoff plan derived from it. The terms can be filled in later
 * from the debt's own Edit terms action, which is where a user goes once they
 * have the paperwork in front of them.
 */
export function CreateDebtModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { activeWorkspace } = useAuth();
  const createDebt = useCreateDebt();
  const [error, setError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<DebtForm>({
    resolver: zodResolver(schema),
    defaultValues: {
      debt_kind: "credit_card",
      currency: activeWorkspace?.tenant.base_currency ?? "USD",
    },
  });

  // An informal debt is the case where terms genuinely don't exist, so the
  // form says so rather than leaving the empty fields looking unfinished.
  const isInformal = watch("debt_kind") === "other";

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      await createDebt.mutateAsync({
        name: values.name,
        currency: values.currency.toUpperCase(),
        balance_minor: majorToMinor(Number(values.balance)),
        debt_kind: values.debt_kind,
        lender: values.lender || undefined,
        apr: values.apr ? values.apr : undefined,
        minimum_payment_minor: values.minimum ? majorToMinor(Number(values.minimum)) : undefined,
        payment_day: values.payment_day ? Number(values.payment_day) : undefined,
      });
      reset();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't add that debt.");
    }
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="xl"
      title="Add a debt"
      description="Anything you owe — a card, a loan, or money borrowed from someone you know."
      footerStart={
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
      }
      footer={
        <Button variant="primary" onClick={() => onSubmit()} loading={isSubmitting}>
          Add debt
        </Button>
      }
    >
      <form onSubmit={onSubmit} noValidate>
        <Stack gap={4}>
          <Grid cols={2} gap={4}>
            <Input
              label="Name"
              required
              placeholder="e.g. Visa, or Borrowed from Wanjiru"
              error={errors.name?.message}
              {...register("name")}
            />
            <Select label="Type" options={KINDS} {...register("debt_kind")} />
          </Grid>

          <Grid cols={2} gap={4}>
            <Input
              label="Amount owed"
              required
              amount
              type="number"
              step="0.01"
              min="0"
              hint="What's outstanding today."
              error={errors.balance?.message}
              {...register("balance")}
            />
            <Select
              label="Currency"
              options={CURRENCY_OPTIONS}
              error={errors.currency?.message}
              {...register("currency")}
            />
          </Grid>

          <Input
            label="Owed to"
            optional
            placeholder="Lender, bank, or a person"
            {...register("lender")}
          />

          <Text tone="tertiary" size="xs">
            {isInformal
              ? "Nothing below is required. A loan from a friend usually has no interest rate or minimum payment, and leaving them blank is more honest than entering a zero you'd have to remember was a guess."
              : "Leave the terms blank if you don't have them to hand — you can add them later, and the payoff planner will use them as soon as they're there."}
          </Text>

          <Grid cols={3} gap={4}>
            <Input
              label="Interest rate"
              optional
              type="number"
              step="0.01"
              min="0"
              hint="% per year"
              error={errors.apr?.message}
              {...register("apr")}
            />
            <Input
              label="Minimum payment"
              optional
              amount
              type="number"
              step="0.01"
              min="0"
              error={errors.minimum?.message}
              {...register("minimum")}
            />
            <Input
              label="Payment day"
              optional
              type="number"
              min="1"
              max="28"
              hint="1–28"
              error={errors.payment_day?.message}
              {...register("payment_day")}
            />
          </Grid>

          {error && <Banner tone="danger">{error}</Banner>}
        </Stack>
      </form>
    </Modal>
  );
}
