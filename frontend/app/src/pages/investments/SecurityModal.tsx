import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "../../api/client";
import type { AssetClass } from "../../api/types";
import { useCreateSecurity } from "../../hooks/useInvestments";
import { CURRENCY_OPTIONS } from "../../lib/currencies";
import { Banner, Button, Grid, Input, Modal, Select, Stack, Text } from "../../ui";

const ASSET_CLASSES: { value: AssetClass; label: string }[] = [
  { value: "stock", label: "Stock" },
  { value: "etf", label: "ETF" },
  { value: "mutual_fund", label: "Mutual fund" },
  { value: "bond", label: "Bond" },
  { value: "crypto", label: "Crypto" },
  { value: "cash_equivalent", label: "Cash investment" },
  { value: "real_estate", label: "Real estate" },
  { value: "commodity", label: "Commodity" },
  { value: "other", label: "Other" },
];

const schema = z.object({
  symbol: z.string().min(1, "Give it a symbol or short name."),
  name: z.string().optional(),
  asset_class: z.string().min(1),
  currency: z.string().length(3, "3-letter code, e.g. USD."),
  sector: z.string().optional(),
});
type SecurityForm = z.infer<typeof schema>;

/**
 * Add a security.
 *
 * Deliberately permissive about what counts as one. A household may hold things
 * no data provider lists — a private company stake, a physical asset — and a
 * form that only accepted real tickers would exclude them. Symbol is free text
 * and gets uppercased server-side.
 */
export function SecurityModal({
  open,
  onClose,
  defaultCurrency,
}: {
  open: boolean;
  onClose: () => void;
  defaultCurrency: string;
}) {
  const createSecurity = useCreateSecurity();
  const [error, setError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<SecurityForm>({
    resolver: zodResolver(schema),
    defaultValues: { asset_class: "stock", currency: defaultCurrency },
  });

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      await createSecurity.mutateAsync({
        symbol: values.symbol,
        name: values.name || values.symbol,
        asset_class: values.asset_class as AssetClass,
        currency: values.currency.toUpperCase(),
        sector: values.sector || "",
      });
      reset({ asset_class: "stock", currency: defaultCurrency });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't add that security.");
    }
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="xl"
      title="Add a security"
      description="Anything you can hold — a listed share, a fund, a coin, or something with no ticker at all."
      footerStart={
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
      }
      footer={
        <Button variant="primary" onClick={() => onSubmit()} loading={isSubmitting}>
          Add security
        </Button>
      }
    >
      <form onSubmit={onSubmit} noValidate>
        <Stack gap={4}>
          <Grid cols={2} gap={4}>
            <Input
              label="Symbol"
              required
              placeholder="AAPL"
              hint="Or any short name you'll recognise."
              error={errors.symbol?.message}
              {...register("symbol")}
            />
            <Input
              label="Name"
              optional
              placeholder="Apple Inc"
              error={errors.name?.message}
              {...register("name")}
            />
          </Grid>

          <Grid cols={2} gap={4}>
            <Select label="Type" required options={ASSET_CLASSES} {...register("asset_class")} />
            <Select
              label="Currency"
              required
              options={CURRENCY_OPTIONS}
              hint="Must match the account you'll hold it in."
              error={errors.currency?.message}
              {...register("currency")}
            />
          </Grid>

          <Input
            label="Sector"
            optional
            placeholder="Technology"
            hint="Used for the sector breakdown. Leave blank if you're not sure."
            {...register("sector")}
          />

          <Text tone="tertiary" size="xs">
            Adding a security doesn't record a purchase — you'll do that next.
          </Text>

          {error && <Banner tone="danger">{error}</Banner>}
        </Stack>
      </form>
    </Modal>
  );
}
