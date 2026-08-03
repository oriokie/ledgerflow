import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "../../api/client";
import { useCreateBudget } from "../../hooks/useBudgeting";
import { Banner, Button, Card, Grid, Inline, Input, Select, Stack } from "../../ui";

const budgetSchema = z.object({
  name: z.string().min(1, "Give this budget a name."),
  currency: z.string().length(3, "3-letter currency code, e.g. USD."),
  starts_on: z.string().min(1, "Choose a start date."),
  period: z.enum(["weekly", "monthly", "quarterly", "yearly"]),
});
type BudgetFormValues = z.infer<typeof budgetSchema>;

export function CreateBudgetForm({
  onCreated,
  onCancel,
}: {
  onCreated: (budgetId: string) => void;
  onCancel: () => void;
}) {
  const createBudget = useCreateBudget();
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<BudgetFormValues>({
    resolver: zodResolver(budgetSchema),
    defaultValues: { currency: "USD", period: "monthly", starts_on: new Date().toISOString().slice(0, 10) },
  });

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      const budget = await createBudget.mutateAsync(values);
      onCreated(budget.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't create the budget.");
    }
  });

  return (
    <Card style={{ marginBottom: "var(--lf-space-4)" }}>
      <form onSubmit={onSubmit} noValidate>
        <Stack gap={4}>
          <Grid cols={2} gap={4}>
            <Input label="Name" placeholder="e.g. Monthly essentials" error={errors.name?.message} {...register("name")} />
            <Select
              label="Period"
              options={[
                { value: "weekly", label: "Weekly" },
                { value: "monthly", label: "Monthly" },
                { value: "quarterly", label: "Quarterly" },
                { value: "yearly", label: "Yearly" },
              ]}
              {...register("period")}
            />
          </Grid>
          <Grid cols={2} gap={4}>
            <Input label="Currency" maxLength={3} error={errors.currency?.message} {...register("currency")} />
            <Input label="Starts on" type="date" error={errors.starts_on?.message} {...register("starts_on")} />
          </Grid>
          {error && <Banner tone="danger">{error}</Banner>}
          <Inline>
            <Button type="submit" variant="primary" loading={isSubmitting}>
              Create budget
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
