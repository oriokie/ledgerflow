import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "../../api/client";
import type { Category } from "../../api/types";
import { useAddBudgetLine } from "../../hooks/useBudgeting";
import { majorToMinor } from "../../lib/money";
import { Banner, Button, Card, Inline, Input, Select } from "../../ui";

const lineSchema = z.object({
  category_id: z.string().min(1, "Choose a category."),
  limit: z
    .string()
    .min(1, "Enter a limit greater than zero.")
    .refine((v) => !Number.isNaN(Number(v)) && Number(v) > 0, "Enter a limit greater than zero."),
});
type LineFormValues = z.infer<typeof lineSchema>;

export function AddLineForm({ budgetId, availableCategories }: { budgetId: string; availableCategories: Category[] }) {
  const addLine = useAddBudgetLine();
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<LineFormValues>({ resolver: zodResolver(lineSchema) });

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      await addLine.mutateAsync({
        budgetId,
        payload: { category_id: values.category_id, limit_minor: majorToMinor(Number(values.limit)) },
      });
      reset();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't add that budget line.");
    }
  });

  if (availableCategories.length === 0) return null;

  return (
    <Card eyebrow="Add a category to this budget">
      <form onSubmit={onSubmit} noValidate>
        <Inline gap={3} align="end" wrap={false}>
          <div style={{ flex: 1 }}>
            <Select label="Category" error={errors.category_id?.message} {...register("category_id")}>
              <option value="">Select&hellip;</option>
              {availableCategories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </div>
          <Input label="Limit" amount type="number" step="0.01" min="0.01" error={errors.limit?.message} {...register("limit")} />
          <Button type="submit" variant="secondary" loading={isSubmitting}>
            Add
          </Button>
        </Inline>
      </form>
      {error && (
        <div style={{ marginTop: "var(--lf-space-3)" }}>
          <Banner tone="danger">{error}</Banner>
        </div>
      )}
    </Card>
  );
}
