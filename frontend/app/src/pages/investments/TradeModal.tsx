import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "../../api/client";
import type { HoldingValuation, Security } from "../../api/types";
import { useAccounts } from "../../hooks/useFinance";
import { useTrade } from "../../hooks/useInvestments";
import { majorToMinor } from "../../lib/money";
import { Banner, Button, Grid, Input, Modal, Select, Stack, Text } from "../../ui";

const schema = z.object({
  financial_account_id: z.string().min(1, "Pick an account."),
  security_id: z.string().min(1, "Pick a security."),
  quantity: z
    .string()
    .min(1, "How many units?")
    .refine((v) => Number(v) > 0, "Units must be greater than zero."),
  amount: z
    .string()
    .min(1, "What was the total?")
    .refine((v) => Number(v) > 0, "Amount must be greater than zero."),
  fee: z
    .string()
    .optional()
    .refine((v) => !v || Number(v) >= 0, "Fees can't be negative."),
  occurred_on: z.string().optional(),
});
type TradeForm = z.infer<typeof schema>;

/**
 * Record a buy or a sell.
 *
 * The amount asked for is the **total consideration**, not a unit price. That's
 * what appears on a contract note, so it's what the user has in front of them —
 * and deriving total from a rounded unit price would introduce a discrepancy
 * against the cash that actually left the account.
 *
 * Fees are collected separately because they're treated differently: on a buy
 * they're capitalised into cost basis, on a sell they reduce proceeds. Folding
 * them into the amount would quietly misstate the gain either way.
 */
export function TradeModal({
  open,
  action,
  onClose,
  securities,
  holdings,
}: {
  open: boolean;
  action: "buy" | "sell";
  onClose: () => void;
  securities: Security[];
  holdings: HoldingValuation[];
}) {
  const { data: accounts } = useAccounts();
  const trade = useTrade();
  const [error, setError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<TradeForm>({ resolver: zodResolver(schema) });

  // Selling is only meaningful against something already held, so the picker
  // narrows to open positions rather than offering every known security.
  const sellable = securities.filter((s) => holdings.some((h) => h.security_id === s.id));
  const options = (action === "sell" ? sellable : securities).map((s) => ({
    value: s.id,
    label: `${s.symbol} — ${s.name}`,
  }));

  const investmentAccounts = (accounts ?? [])
    .filter((a) => a.account_type === "investment")
    .map((a) => ({ value: a.id, label: a.name }));

  const selectedId = watch("security_id");
  const position = holdings.find((h) => h.security_id === selectedId);

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      await trade.mutateAsync({
        action,
        payload: {
          financial_account_id: values.financial_account_id,
          security_id: values.security_id,
          quantity: values.quantity,
          amount_minor: majorToMinor(Number(values.amount)),
          fee_minor: values.fee ? majorToMinor(Number(values.fee)) : 0,
          occurred_on: values.occurred_on || undefined,
        },
      });
      reset();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : `Couldn't record that ${action}.`);
    }
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="xl"
      title={action === "buy" ? "Record a purchase" : "Record a sale"}
      description={
        action === "buy"
          ? "This posts to your ledger, so the position reconciles against the cash that bought it."
          : "Units are sold oldest-first, and the gain is worked out against what those units actually cost."
      }
      footerStart={
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
      }
      footer={
        <Button variant="primary" onClick={() => onSubmit()} loading={isSubmitting}>
          {action === "buy" ? "Record purchase" : "Record sale"}
        </Button>
      }
    >
      <form onSubmit={onSubmit} noValidate>
        <Stack gap={4}>
          {options.length === 0 ? (
            <Banner tone="info">
              {action === "sell"
                ? "You don't hold anything yet. Record a purchase first."
                : "Add a security before recording a purchase."}
            </Banner>
          ) : (
            <>
              <Select
                label="Account"
                required
                placeholder="Choose an account"
                options={investmentAccounts}
                hint="Only investment accounts can hold securities."
                error={errors.financial_account_id?.message}
                {...register("financial_account_id")}
              />

              <Select
                label="Security"
                required
                placeholder="Choose a security"
                options={options}
                error={errors.security_id?.message}
                {...register("security_id")}
              />

              {/* Showing what's held prevents the most common sell error before
                  the server has to reject it. */}
              {action === "sell" && position && (
                <Text tone="tertiary" size="sm">
                  You hold {position.quantity} units of {position.symbol}.
                </Text>
              )}

              <Grid cols={2} gap={4}>
                <Input
                  label="Units"
                  required
                  inputMode="decimal"
                  placeholder="10"
                  hint="Fractions are fine for crypto and some funds."
                  error={errors.quantity?.message}
                  {...register("quantity")}
                />
                <Input
                  label="Total amount"
                  required
                  amount
                  inputMode="decimal"
                  placeholder="0.00"
                  hint={
                    action === "buy"
                      ? "What left your account, before fees."
                      : "What the sale raised, before fees."
                  }
                  error={errors.amount?.message}
                  {...register("amount")}
                />
              </Grid>

              <Grid cols={2} gap={4}>
                <Input
                  label="Fees"
                  optional
                  amount
                  inputMode="decimal"
                  placeholder="0.00"
                  hint={
                    action === "buy"
                      ? "Added to what the position cost you."
                      : "Deducted from the proceeds."
                  }
                  error={errors.fee?.message}
                  {...register("fee")}
                />
                <Input
                  label="Date"
                  optional
                  type="date"
                  hint="Defaults to today."
                  {...register("occurred_on")}
                />
              </Grid>
            </>
          )}

          {error && <Banner tone="danger">{error}</Banner>}
        </Stack>
      </form>
    </Modal>
  );
}
