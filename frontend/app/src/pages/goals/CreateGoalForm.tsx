import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "../../api/client";
import type { GoalKind, GoalPriority } from "../../api/types";
import { useCreateGoal } from "../../hooks/useGoals";
import { CURRENCY_OPTIONS } from "../../lib/currencies";
import { majorToMinor } from "../../lib/money";
import { Banner, Button, Card, Grid, Inline, Input, Select, Stack, Text } from "../../ui";
import { GOAL_KIND_OPTIONS, GOAL_PRIORITY_LABELS } from "./kinds";

const goalSchema = z.object({
  name: z.string().min(1, "Give this goal a name."),
  kind: z.string().min(1),
  currency: z.string().length(3, "3-letter currency code, e.g. USD."),
  target: z
    .string()
    .min(1, "Enter a target greater than zero.")
    .refine((v) => !Number.isNaN(Number(v)) && Number(v) > 0, "Enter a target greater than zero."),
  target_date: z.string().optional(),
  priority: z.string().optional(),
  // What the user intends to put in monthly. Optional — the forecast falls
  // back to observed behaviour, and demanding a number up front is a barrier
  // at exactly the moment the user is least sure.
  planned_monthly: z
    .string()
    .optional()
    .refine((v) => !v || (!Number.isNaN(Number(v)) && Number(v) > 0), "Enter an amount greater than zero."),
});
type GoalFormValues = z.infer<typeof goalSchema>;

const PRIORITY_OPTIONS = (Object.keys(GOAL_PRIORITY_LABELS) as unknown as GoalPriority[]).map((p) => ({
  value: String(p),
  label: GOAL_PRIORITY_LABELS[p],
}));

export function CreateGoalForm({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
  const createGoal = useCreateGoal();
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<GoalFormValues>({
    resolver: zodResolver(goalSchema),
    // Priority is left unset so the server fills it from the kind — a user who
    // doesn't care still gets a sensible funding order.
    defaultValues: { currency: "USD", kind: "custom", priority: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      await createGoal.mutateAsync({
        name: values.name,
        kind: values.kind as GoalKind,
        currency: values.currency.toUpperCase(),
        target_minor: majorToMinor(Number(values.target)),
        target_date: values.target_date || undefined,
        priority: values.priority ? (Number(values.priority) as GoalPriority) : undefined,
        planned_monthly_minor: values.planned_monthly
          ? majorToMinor(Number(values.planned_monthly))
          : undefined,
      });
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't create that goal.");
    }
  });

  return (
    <Card style={{ marginBottom: "var(--lf-space-4)" }}>
      <form onSubmit={onSubmit} noValidate>
        <Stack gap={4}>
          <Input
            label="Goal name"
            placeholder="e.g. Emergency fund, Japan trip"
            required
            error={errors.name?.message}
            {...register("name")}
          />

          <Grid cols={2} gap={4}>
            <Select
              label="What kind of goal?"
              options={GOAL_KIND_OPTIONS}
              hint="Shapes the suggestions and default priority."
              {...register("kind")}
            />
            <Select
              label="Priority"
              placeholder="Set from goal type"
              options={PRIORITY_OPTIONS}
              hint="Which goals to fund first when money is tight."
              {...register("priority")}
            />
          </Grid>

          <Grid cols={2} gap={4}>
            <Input
              label="Target amount"
              amount
              required
              type="number"
              step="0.01"
              min="0.01"
              error={errors.target?.message}
              {...register("target")}
            />
            <Select
              label="Currency"
              options={CURRENCY_OPTIONS}
              error={errors.currency?.message}
              {...register("currency")}
            />
          </Grid>

          <Grid cols={2} gap={4}>
            <Input
              label="Target date"
              optional
              type="date"
              hint="Needed to work out what you must save each month."
              {...register("target_date")}
            />
            <Input
              label="Planned monthly contribution"
              optional
              amount
              type="number"
              step="0.01"
              min="0.01"
              hint="What you intend to put in. We'll compare it to what you actually do."
              error={errors.planned_monthly?.message}
              {...register("planned_monthly")}
            />
          </Grid>

          <Text tone="tertiary" size="xs">
            Goals track money you already hold — creating one doesn't move anything between accounts.
          </Text>

          {error && <Banner tone="danger">{error}</Banner>}
          <Inline>
            <Button type="submit" variant="primary" loading={isSubmitting}>
              Create goal
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
