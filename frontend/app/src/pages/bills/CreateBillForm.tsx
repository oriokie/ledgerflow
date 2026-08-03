import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "../../api/client";
import { useCategories, useCreateBill } from "../../hooks/useFinance";
import { majorToMinor } from "../../lib/money";
import { Banner, Button, Card, Grid, Inline, Input, Select, Stack } from "../../ui";

const billSchema = z.object({
  name: z.string().min(1, "Name this bill."),
  amount: z
    .string()
    .min(1, "Enter an amount greater than zero.")
    .refine((v) => !Number.isNaN(Number(v)) && Number(v) > 0, "Enter an amount greater than zero."),
  currency: z.string().length(3, "3-letter currency code, e.g. USD."),
  due_on: z.string().min(1, "Choose a due date."),
  category_id: z.string().optional(),
});
type BillFormValues = z.infer<typeof billSchema>;

export function CreateBillForm({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
  const { data: categories } = useCategories();
  const createBill = useCreateBill();
  const [error, setError] = useState<string | null>(null);
  const expenseCategories = categories?.filter((c) => c.kind === "expense") ?? [];

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<BillFormValues>({ resolver: zodResolver(billSchema), defaultValues: { currency: "USD" } });

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      await createBill.mutateAsync({
        name: values.name,
        amount_minor: majorToMinor(Number(values.amount)),
        currency: values.currency.toUpperCase(),
        due_on: values.due_on,
        category_id: values.category_id || undefined,
      });
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't create that bill.");
    }
  });

  return (
    <Card style={{ marginBottom: "var(--lf-space-4)" }}>
      <form onSubmit={onSubmit} noValidate>
        <Stack gap={4}>
          <Input label="Bill name" placeholder="e.g. Rent, Electric" error={errors.name?.message} {...register("name")} />
          <Grid cols={2} gap={4}>
            <Input label="Amount" amount type="number" step="0.01" min="0.01" error={errors.amount?.message} {...register("amount")} />
            <Input label="Currency" maxLength={3} error={errors.currency?.message} {...register("currency")} />
          </Grid>
          <Grid cols={2} gap={4}>
            <Input label="Due on" type="date" error={errors.due_on?.message} {...register("due_on")} />
            <Select label="Category (optional)" {...register("category_id")}>
              <option value="">None</option>
              {expenseCategories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </Grid>
          {error && <Banner tone="danger">{error}</Banner>}
          <Inline>
            <Button type="submit" variant="primary" loading={isSubmitting}>
              Create bill
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
