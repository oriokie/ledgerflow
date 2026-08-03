import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";
import { ApiError } from "../../api/client";
import { useAccounts, useCategories, useCreateTransaction, useCreateTransfer } from "../../hooks/useFinance";
import { majorToMinor } from "../../lib/money";
import { Banner, Button, Card, Grid, Inline, Input, SegmentedControl, Select, Stack } from "../../ui";
import { useState } from "react";

const txnSchema = z.object({
  type: z.enum(["expense", "income", "transfer"]),
  financial_account_id: z.string().min(1, "Choose an account."),
  category_id: z.string().optional(),
  to_account_id: z.string().optional(),
  amount: z
    .string()
    .min(1, "Enter an amount.")
    .refine((v) => !Number.isNaN(Number(v)) && Number(v) > 0, "Enter an amount greater than zero."),
  occurred_at: z.string().min(1, "Choose a date."),
  memo: z.string().optional(),
});
type TxnFormValues = z.infer<typeof txnSchema>;

export function AddTransactionForm({ onClose }: { onClose: () => void }) {
  const { data: accounts } = useAccounts();
  const { data: categories } = useCategories();
  const createTransaction = useCreateTransaction();
  const createTransfer = useCreateTransfer();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<TxnFormValues>({
    resolver: zodResolver(txnSchema),
    defaultValues: { type: "expense", occurred_at: new Date().toISOString().slice(0, 10) },
  });
  const txnType = watch("type");
  const usableCategories = categories?.filter((c) => c.kind === txnType) ?? [];
  const noAccounts = accounts !== undefined && accounts.length === 0;

  const onSubmit = handleSubmit(async (values) => {
    setServerError(null);
    try {
      if (values.type === "transfer") {
        if (!values.to_account_id) return setServerError("Choose a destination account.");
        await createTransfer.mutateAsync({
          from_account_id: values.financial_account_id,
          to_account_id: values.to_account_id,
          amount_minor: majorToMinor(Number(values.amount)),
          occurred_at: new Date(values.occurred_at).toISOString(),
          memo: values.memo,
        });
      } else {
        if (!values.category_id) return setServerError("Choose a category.");
        await createTransaction.mutateAsync({
          type: values.type,
          financial_account_id: values.financial_account_id,
          category_id: values.category_id,
          amount_minor: majorToMinor(Number(values.amount)),
          occurred_at: new Date(values.occurred_at).toISOString(),
          memo: values.memo,
        });
      }
      reset({ type: values.type, occurred_at: values.occurred_at, financial_account_id: values.financial_account_id });
      onClose();
    } catch (err) {
      setServerError(err instanceof ApiError ? err.detail : "Couldn't save this transaction.");
    }
  });

  return (
    <Card style={{ marginBottom: "var(--lf-space-4)" }}>
      {noAccounts ? (
        <Stack gap={3}>
          <div>
            <strong>You'll need an account first</strong>
            <p style={{ color: "var(--lf-text-secondary)", fontSize: "var(--lf-text-sm)", marginTop: 4 }}>
              A transaction has to land somewhere. Add a checking account, savings, or a card, then come back to
              log this.
            </p>
          </div>
          <Inline gap={2}>
            <Link className="lf-btn lf-btn--primary lf-btn--sm" to="/accounts">
              Add an account
            </Link>
            <Button variant="ghost" size="sm" onClick={onClose}>
              Not now
            </Button>
          </Inline>
        </Stack>
      ) : (
        <form onSubmit={onSubmit} noValidate>
        <Stack gap={4}>
          <SegmentedControl
            legend="Transaction type"
            value={txnType}
            onChange={(v) => setValue("type", v)}
            options={[
              { value: "expense", label: "Expense" },
              { value: "income", label: "Income" },
              { value: "transfer", label: "Transfer" },
            ]}
          />

          <Grid cols={2} gap={4}>
            <Select
              label={txnType === "transfer" ? "From account" : "Account"}
              error={errors.financial_account_id?.message}
              {...register("financial_account_id")}
            >
              <option value="">Select an account…</option>
              {accounts?.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>

            {txnType === "transfer" ? (
              <Select label="To account" {...register("to_account_id")}>
                <option value="">Select…</option>
                {accounts?.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </Select>
            ) : (
              <Select label="Category" {...register("category_id")}>
                <option value="">Select a category…</option>
                {usableCategories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            )}
          </Grid>

          <Grid cols={2} gap={4}>
            <Input label="Amount" amount type="number" step="0.01" min="0.01" error={errors.amount?.message} {...register("amount")} />
            <Input label="Date" type="date" error={errors.occurred_at?.message} {...register("occurred_at")} />
          </Grid>

          <Input label="Memo (optional)" {...register("memo")} />

          {serverError && <Banner tone="danger">{serverError}</Banner>}
          <Inline>
            <Button type="submit" variant="primary" loading={isSubmitting}>
              {txnType === "transfer" ? "Move money" : "Save transaction"}
            </Button>
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
          </Inline>
        </Stack>
      </form>
      )}
    </Card>
  );
}

