import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "../../api/client";
import { useAccounts, useCategories, useCreateRecurring } from "../../hooks/useFinance";
import { majorToMinor } from "../../lib/money";
import { Banner, Button, Grid, Input, Modal, SegmentedControl, Select, Stack } from "../../ui";

const schema = z.object({
  txn_type: z.enum(["expense", "income"]),
  financial_account_id: z.string().min(1, "Choose an account."),
  category_id: z.string().min(1, "Choose a category."),
  amount: z
    .string()
    .min(1, "Enter an amount.")
    .refine((v) => !Number.isNaN(Number(v)) && Number(v) > 0, "Enter an amount greater than zero."),
  currency: z.string().length(3, "3-letter code."),
  frequency: z.enum(["daily", "weekly", "monthly", "yearly"]),
  starts_on: z.string().min(1, "Choose a start date."),
  memo: z.string().optional(),
});
type FormValues = z.infer<typeof schema>;

export function CreateRecurringModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { data: accounts } = useAccounts();
  const { data: categories } = useCategories();
  const createRecurring = useCreateRecurring();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      txn_type: "expense",
      currency: "USD",
      frequency: "monthly",
      starts_on: new Date().toISOString().slice(0, 10),
    },
  });
  const txnType = watch("txn_type");
  const usableCategories = categories?.filter((c) => c.kind === txnType) ?? [];

  const onSubmit = handleSubmit(async (values) => {
    setServerError(null);
    try {
      await createRecurring.mutateAsync({
        txn_type: values.txn_type,
        financial_account_id: values.financial_account_id,
        category_id: values.category_id,
        amount_minor: majorToMinor(Number(values.amount)),
        currency: values.currency.toUpperCase(),
        frequency: values.frequency,
        starts_on: values.starts_on,
        memo: values.memo,
      });
      reset({ txn_type: values.txn_type, currency: values.currency, frequency: values.frequency, starts_on: values.starts_on });
      onClose();
    } catch (err) {
      setServerError(err instanceof ApiError ? err.detail : "Couldn't create the schedule.");
    }
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New recurring charge"
      footer={
        <Button variant="primary" onClick={() => onSubmit()} loading={isSubmitting}>
          Create schedule
        </Button>
      }
    >
      <form onSubmit={onSubmit} noValidate>
        <Stack gap={4}>
          <SegmentedControl
            legend="Type"
            value={txnType}
            onChange={(v) => setValue("txn_type", v)}
            options={[
              { value: "expense", label: "Expense" },
              { value: "income", label: "Income" },
            ]}
          />

          <Grid cols={2} gap={4}>
            <Select label="Account" error={errors.financial_account_id?.message} {...register("financial_account_id")}>
              <option value="">Select…</option>
              {accounts?.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
            <Select label="Category" error={errors.category_id?.message} {...register("category_id")}>
              <option value="">Select…</option>
              {usableCategories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </Grid>

          <Grid cols={2} gap={4}>
            <Input label="Amount" amount type="number" step="0.01" min="0.01" error={errors.amount?.message} {...register("amount")} />
            <Select
              label="Frequency"
              options={[
                { value: "daily", label: "Daily" },
                { value: "weekly", label: "Weekly" },
                { value: "monthly", label: "Monthly" },
                { value: "yearly", label: "Yearly" },
              ]}
              {...register("frequency")}
            />
          </Grid>

          <Grid cols={2} gap={4}>
            <Input label="Starts on" type="date" error={errors.starts_on?.message} {...register("starts_on")} />
            <Input label="Currency" maxLength={3} error={errors.currency?.message} {...register("currency")} />
          </Grid>

          <Input label="Name / memo" placeholder="e.g. Netflix, Rent" {...register("memo")} />

          {serverError && <Banner tone="danger">{serverError}</Banner>}
        </Stack>
      </form>
    </Modal>
  );
}
