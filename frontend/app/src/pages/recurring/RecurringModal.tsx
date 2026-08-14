import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "../../api/client";
import type { RecurringTransaction } from "../../api/types";
import {
  useAccounts,
  useCategories,
  useCreateRecurring,
  useUpdateRecurring,
} from "../../hooks/useFinance";
import { useAuth } from "../../lib/AuthContext";
import { CURRENCY_OPTIONS } from "../../lib/currencies";
import { majorToMinor, minorToMajor } from "../../lib/money";
import { Banner, Button, Grid, Input, Modal, SegmentedControl, Select, Stack, Text } from "../../ui";
import { CADENCE_OPTIONS, cadenceByValue, cadenceFor } from "./recurringMath";

const schema = z.object({
  txn_type: z.enum(["expense", "income", "transfer"]),
  financial_account_id: z.string().min(1, "Choose an account."),
  counter_account_id: z.string().optional(),
  category_id: z.string().optional(),
  amount: z
    .string()
    .min(1, "Enter an amount.")
    .refine((v) => !Number.isNaN(Number(v)) && Number(v) > 0, "Enter an amount greater than zero."),
  currency: z.string().length(3, "3-letter code."),
  cadence: z.string().min(1, "Choose how often."),
  starts_on: z.string().min(1, "Choose a start date."),
  ends_on: z.string().optional(),
  memo: z.string().optional(),
}).superRefine((values, ctx) => {
  if (values.txn_type === "transfer") {
    if (!values.counter_account_id) {
      ctx.addIssue({ code: "custom", path: ["counter_account_id"], message: "Choose a destination account." });
    } else if (values.counter_account_id === values.financial_account_id) {
      ctx.addIssue({
        code: "custom",
        path: ["counter_account_id"],
        message: "From and To accounts must be different.",
      });
    }
  } else if (!values.category_id) {
    ctx.addIssue({ code: "custom", path: ["category_id"], message: "Choose a category." });
  }
});
type FormValues = z.infer<typeof schema>;

/**
 * Create or edit a recurring transaction.
 *
 * One form for both, because they are the same set of decisions and two copies
 * of a form drift — always toward the one nobody is testing.
 *
 * **Editing is deliberately partial.** Type, account and currency are locked
 * once a schedule exists: every occurrence already posted from the template
 * carries all three, so changing one would reinterpret history rather than
 * correct the plan. Those are a cancel-and-recreate, which leaves the posted
 * transactions visibly attached to the schedule that actually produced them.
 * The server enforces the same rule — this form just doesn't offer the fields.
 */
export function RecurringModal({
  open,
  onClose,
  editing,
}: {
  open: boolean;
  onClose: () => void;
  /** The schedule to edit. Absent means create a new one. */
  editing?: RecurringTransaction | null;
}) {
  const { activeWorkspace } = useAuth();
  const { data: accounts } = useAccounts();
  const { data: categories } = useCategories();
  const createRecurring = useCreateRecurring();
  const updateRecurring = useUpdateRecurring();
  const [serverError, setServerError] = useState<string | null>(null);
  const isEdit = !!editing;

  const baseCurrency = activeWorkspace?.tenant.base_currency ?? "USD";

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
      currency: baseCurrency,
      cadence: "monthly",
      starts_on: new Date().toISOString().slice(0, 10),
      ends_on: "",
    },
  });

  // Load the schedule being edited into the form, and reset back to a blank
  // create form when the modal is reopened without one. Keyed on the id so
  // switching directly from editing one row to another refills the fields.
  useEffect(() => {
    if (!open) return;
    if (editing) {
      reset({
        txn_type:
          editing.txn_type === "income"
            ? "income"
            : editing.txn_type === "transfer"
              ? "transfer"
              : "expense",
        financial_account_id: editing.financial_account_id ?? "",
        counter_account_id: editing.counter_account_id ?? "",
        category_id: editing.category_id ?? "",
        amount: String(minorToMajor(editing.amount_minor)),
        currency: editing.currency,
        cadence: cadenceFor(editing)?.value ?? "monthly",
        starts_on: editing.next_run_on,
        ends_on: editing.ends_on ?? "",
        memo: editing.memo ?? "",
      });
    } else {
      reset({
        txn_type: "expense",
        financial_account_id: "",
        counter_account_id: "",
        category_id: "",
        amount: "",
        currency: baseCurrency,
        cadence: "monthly",
        starts_on: new Date().toISOString().slice(0, 10),
        ends_on: "",
        memo: "",
      });
    }
    setServerError(null);
  }, [open, editing, reset, baseCurrency]);

  const txnType = watch("txn_type");
  const fromAccountId = watch("financial_account_id");
  const isTransfer = txnType === "transfer";
  const fromAccount = accounts?.find((account) => account.id === fromAccountId);
  const usableCategories = categories?.filter((c) => c.kind === txnType) ?? [];

  const onSubmit = handleSubmit(async (values) => {
    setServerError(null);
    const cadence = cadenceByValue(values.cadence);
    if (!cadence) {
      setServerError("Choose how often this repeats.");
      return;
    }
    const endsOn = values.ends_on?.trim() ? values.ends_on : null;
    try {
      if (editing) {
        await updateRecurring.mutateAsync({
          recId: editing.id,
          category_id: isTransfer ? undefined : values.category_id,
          counter_account_id: isTransfer ? values.counter_account_id : undefined,
          amount_minor: majorToMinor(Number(values.amount)),
          frequency: cadence.frequency,
          interval: cadence.interval,
          starts_on: values.starts_on,
          ends_on: endsOn,
          memo: values.memo ?? "",
        });
      } else {
        await createRecurring.mutateAsync({
          txn_type: values.txn_type,
          financial_account_id: values.financial_account_id,
          counter_account_id: isTransfer ? values.counter_account_id : undefined,
          category_id: isTransfer ? undefined : values.category_id,
          amount_minor: majorToMinor(Number(values.amount)),
          currency: values.currency.toUpperCase(),
          frequency: cadence.frequency,
          interval: cadence.interval,
          starts_on: values.starts_on,
          ends_on: endsOn ?? undefined,
          memo: values.memo,
        });
      }
      onClose();
    } catch (err) {
      setServerError(
        err instanceof ApiError
          ? err.detail
          : isEdit
            ? "Couldn't save your changes."
            : "Couldn't create the schedule.",
      );
    }
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? "Edit recurring transaction" : "New recurring transaction"}
      footer={
        <Button variant="primary" onClick={() => onSubmit()} loading={isSubmitting}>
          {isEdit ? "Save changes" : "Create schedule"}
        </Button>
      }
    >
      <form onSubmit={onSubmit} noValidate>
        <Stack gap={4}>
          {isEdit ? (
            <Text size="xs" tone="tertiary">
              Changes apply from the next transaction onward. Anything this schedule has already
              posted stays exactly as it is.
            </Text>
          ) : null}

          {!isEdit && (
            <SegmentedControl
              legend="Type"
              value={txnType}
              onChange={(v) => setValue("txn_type", v)}
              options={[
                { value: "expense", label: "Expense" },
                { value: "income", label: "Income" },
                { value: "transfer", label: "Transfer / Savings" },
              ]}
            />
          )}

          <Grid cols={2} gap={4}>
            <Select
              label={isTransfer ? "From account" : "Account"}
              error={errors.financial_account_id?.message}
              disabled={isEdit}
              hint={isEdit ? "Locked — transactions already posted here." : undefined}
              {...register("financial_account_id")}
            >
              <option value="">Select…</option>
              {accounts?.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
            {isTransfer ? (
              <Select
                label="To account"
                error={errors.counter_account_id?.message}
                {...register("counter_account_id")}
              >
                <option value="">Select…</option>
                {accounts
                  ?.filter(
                    (a) =>
                      a.id !== fromAccountId &&
                      (!fromAccount || a.currency === fromAccount.currency),
                  )
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
              </Select>
            ) : (
              <Select label="Category" error={errors.category_id?.message} {...register("category_id")}>
                <option value="">Select…</option>
                {usableCategories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            )}
          </Grid>

          <Grid cols={2} gap={4}>
            <Input
              label="Amount"
              amount
              type="number"
              step="0.01"
              min="0.01"
              error={errors.amount?.message}
              {...register("amount")}
            />
            <Select label="How often" options={CADENCE_OPTIONS} {...register("cadence")} />
          </Grid>

          <Grid cols={2} gap={4}>
            <Input
              label={isEdit ? "Next transaction on" : "Starts on"}
              type="date"
              error={errors.starts_on?.message}
              {...register("starts_on")}
            />
            <Input
              label="Ends on"
              type="date"
              optional
              hint="Leave blank if it does not end."
              error={errors.ends_on?.message}
              {...register("ends_on")}
            />
          </Grid>

          <Select
            label="Currency"
            options={CURRENCY_OPTIONS}
            disabled={isEdit}
            hint={isEdit ? "Locked — transactions already posted in it." : undefined}
            error={errors.currency?.message}
            {...register("currency")}
          />

          <Input
            label="Name / memo"
            placeholder={isTransfer ? "e.g. Monthly savings" : "e.g. Netflix, Rent"}
            {...register("memo")}
          />

          {serverError && <Banner tone="danger">{serverError}</Banner>}
        </Stack>
      </form>
    </Modal>
  );
}
