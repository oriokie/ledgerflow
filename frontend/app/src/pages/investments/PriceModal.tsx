import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "../../api/client";
import type { HoldingValuation } from "../../api/types";
import { useRecordPrice } from "../../hooks/useInvestments";
import { majorToMinor } from "../../lib/money";
import { Banner, Button, Grid, Input, Modal, Select, Stack, Text } from "../../ui";

const schema = z.object({
  security_id: z.string().min(1, "Pick a holding."),
  price: z
    .string()
    .min(1, "What's it worth per unit?")
    .refine((v) => Number(v) >= 0, "Price can't be negative."),
  as_of: z.string().optional(),
});
type PriceForm = z.infer<typeof schema>;

/**
 * Record a market price.
 *
 * Manual entry today; this is the same service a broker or market-data sync
 * would call, so wiring one later changes nothing else in the module.
 *
 * Prices are per **unit**, unlike trades which take a total. That asymmetry is
 * intentional and matches where each number comes from: a contract note shows a
 * total, a price quote shows a unit price.
 */
export function PriceModal({
  open,
  onClose,
  holdings,
}: {
  open: boolean;
  onClose: () => void;
  holdings: HoldingValuation[];
}) {
  const recordPrice = useRecordPrice();
  const [error, setError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<PriceForm>({ resolver: zodResolver(schema) });

  // Unpriced holdings first: they're the ones distorting the portfolio total,
  // so they're what the user most likely opened this to fix.
  const options = [...holdings]
    .sort((a, b) => Number(a.is_priced) - Number(b.is_priced))
    .map((h) => ({
      value: h.security_id,
      label: h.is_priced ? `${h.symbol} — ${h.security_name}` : `${h.symbol} — not priced yet`,
    }));

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      await recordPrice.mutateAsync({
        security_id: values.security_id,
        price_minor: majorToMinor(Number(values.price)),
        as_of: values.as_of || undefined,
      });
      reset();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't record that price.");
    }
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="xl"
      title="Update a price"
      description="Market value is worked out from the latest price you've recorded. Nothing is posted to your ledger."
      footerStart={
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
      }
      footer={
        <Button variant="primary" onClick={() => onSubmit()} loading={isSubmitting}>
          Save price
        </Button>
      }
    >
      <form onSubmit={onSubmit} noValidate>
        <Stack gap={4}>
          {options.length === 0 ? (
            <Banner tone="info">Record a purchase first — there's nothing to price yet.</Banner>
          ) : (
            <>
              <Select
                label="Holding"
                required
                placeholder="Choose a holding"
                options={options}
                error={errors.security_id?.message}
                {...register("security_id")}
              />
              <Grid cols={2} gap={4}>
                <Input
                  label="Price per unit"
                  required
                  amount
                  inputMode="decimal"
                  placeholder="0.00"
                  error={errors.price?.message}
                  {...register("price")}
                />
                <Input
                  label="As of"
                  optional
                  type="date"
                  hint="Backdate to build up history."
                  {...register("as_of")}
                />
              </Grid>
              <Text tone="tertiary" size="xs">
                Recording prices over time is what makes the performance chart possible.
              </Text>
            </>
          )}

          {error && <Banner tone="danger">{error}</Banner>}
        </Stack>
      </form>
    </Modal>
  );
}
