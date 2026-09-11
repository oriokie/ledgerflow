import { Home, Plus } from "lucide-react";
import { useState } from "react";
import { z } from "zod";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";

import { ApiError } from "../api/client";
import type { TangibleAsset, ValuationSource } from "../api/assets";
import { useAccounts } from "../hooks/useFinance";
import {
  useAsset,
  useAssets,
  useAssetSummary,
  useCreateAsset,
  useDeleteAsset,
  useRecordValuation,
  useUpdateAsset,
} from "../hooks/useAssets";
import { useCurrencyOptions } from "../hooks/useCurrencies";
import { useOpenOnParam } from "../hooks/useOpenOnParam";
import { useAuth } from "../lib/AuthContext";
import { amountInputStep, workspaceCurrency } from "../lib/currencies";
import { majorToMinor } from "../lib/money";
import {
  Badge,
  Banner,
  Button,
  Card,
  ConfirmAction,
  EmptyState,
  Figure,
  FigureRow,
  Grid,
  Inline,
  Input,
  Modal,
  Money,
  PageHeader,
  Select,
  SkeletonCard,
  Stack,
  Switch,
  Text,
  useToast,
} from "../ui";
import { ASSET_KIND_LABELS, ASSET_KIND_OPTIONS, VALUATION_SOURCE_OPTIONS } from "./assets/kinds";

const createSchema = z.object({
  name: z.string().min(1, "Name this."),
  kind: z.string().min(1),
  currency: z.string().length(3),
  value: z
    .string()
    .min(1, "What is it worth today?")
    .refine((v) => !Number.isNaN(Number(v)) && Number(v) > 0, "Enter an amount greater than zero."),
  cost: z
    .string()
    .optional()
    .refine((v) => !v || (!Number.isNaN(Number(v)) && Number(v) >= 0), "Enter a cost of zero or more."),
  acquired_on: z.string().optional(),
  secured_by_debt_id: z.string().optional(),
});
type CreateValues = z.infer<typeof createSchema>;

/**
 * Houses, cars, land — the numbers net worth was missing.
 *
 * Nothing here posts to the ledger. A gain in value is somebody's judgement,
 * not money moving, so it overlays net worth the same way unrealised
 * investment gains do.
 */
export function AssetsPage() {
  const { activeWorkspace } = useAuth();
  const books = workspaceCurrency(activeWorkspace?.tenant);
  const { data: assets, isLoading } = useAssets();
  const { data: summary } = useAssetSummary();
  const [showCreate, setShowCreate] = useOpenOnParam();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const list = assets ?? [];
  const currency = summary?.currency ?? books;

  return (
    <>
      <PageHeader
        title="Property"
        eyebrow="Position"
        description="Houses, cars, land — valued separately from the accounts you transact through, and counted in net worth."
        illustration="vault"
        actions={
          <Button variant="primary" onClick={() => setShowCreate(true)} icon={<Plus size={15} aria-hidden="true" />}>
            Add something you own
          </Button>
        }
      />

      <Stack gap={4}>
      {isLoading && <SkeletonCard />}

      {!isLoading && list.length === 0 && (
        <Card>
          <EmptyState
            icon={Home}
            illustration="vault"
            title="Nothing recorded yet"
            body="A net worth that omits the house is not net worth. Add what you own — even a rough estimate is better than a silent zero."
            action={
              <Button variant="primary" onClick={() => setShowCreate(true)}>
                Add your first asset
              </Button>
            }
            tips={[
              "Link a mortgage or car loan to see equity and loan-to-value.",
              "Revalue when you have a new figure. Between valuations the chart interpolates; it never invents growth past the last one.",
              "Leave something out of net worth if it is not really yours to count.",
            ]}
          />
        </Card>
      )}

      {summary && (
        <Card>
          <FigureRow lead>
            <Figure
              label="Worth"
              size="hero"
              amountMinor={summary.value_minor}
              currency={currency}
              hint={
                summary.unvalued_count
                  ? `${summary.unvalued_count} still unvalued`
                  : `${summary.count} recorded`
              }
            />
            <Figure label="Secured debt" amountMinor={summary.debt_minor} currency={currency} />
            <Figure label="Your equity" amountMinor={summary.equity_minor} currency={currency} />
          </FigureRow>
        </Card>
      )}

      {list.length > 0 && (
        <Grid cols={2} gap={3}>
          {list.map((asset) => (
            <AssetCard key={asset.id} asset={asset} onOpen={() => setSelectedId(asset.id)} />
          ))}
        </Grid>
      )}

      {showCreate && <CreateAssetModal books={books} onClose={() => setShowCreate(false)} />}
      {selectedId && <AssetDetailModal id={selectedId} onClose={() => setSelectedId(null)} />}
      </Stack>
    </>
  );
}

function AssetCard({ asset, onOpen }: { asset: TangibleAsset; onOpen: () => void }) {
  return (
    <Card>
      <button type="button" className="lf-asset-card" onClick={onOpen}>
        <div className="lf-asset-card-head">
          <strong>{asset.name}</strong>
          <Badge tone="neutral">{ASSET_KIND_LABELS[asset.kind]}</Badge>
        </div>
        {asset.value_minor == null ? (
          <Text size="sm" tone="tertiary">
            Not yet valued
          </Text>
        ) : (
          <Money amountMinor={asset.value_minor} currency={asset.currency} />
        )}
        {asset.equity_minor != null && asset.debt_minor > 0 && (
          <Text size="xs" tone="secondary" as="div">
            Equity <Money amountMinor={asset.equity_minor} currency={asset.currency} />
            {asset.loan_to_value_pct != null ? ` · ${asset.loan_to_value_pct}% LTV` : ""}
          </Text>
        )}
      </button>
    </Card>
  );
}

function CreateAssetModal({ books, onClose }: { books: string; onClose: () => void }) {
  const create = useCreateAsset();
  const { data: accounts } = useAccounts();
  const currencySelect = useCurrencyOptions();
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);
  const liabilities = (accounts ?? []).filter(
    (a) => a.account_type === "loan" || a.account_type === "credit_card",
  );

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { kind: "property", currency: books },
  });
  const currency = watch("currency") || books;

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      await create.mutateAsync({
        name: values.name,
        kind: values.kind as TangibleAsset["kind"],
        currency: values.currency,
        acquired_on: values.acquired_on || null,
        acquisition_cost_minor: values.cost ? majorToMinor(Number(values.cost), values.currency) : null,
        initial_value_minor: majorToMinor(Number(values.value), values.currency),
        secured_by_debt_id: values.secured_by_debt_id || null,
      });
      toast("Recorded. It now counts in net worth.", { tone: "success" });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't save this.");
    }
  });

  return (
    <Modal open onClose={onClose} title="Add something you own">
      <form onSubmit={onSubmit} noValidate>
        <Stack gap={3}>
          <Input label="Name" required error={errors.name?.message} {...register("name")} />
          <Grid cols={2} gap={3}>
            <Select label="Kind" options={ASSET_KIND_OPTIONS} {...register("kind")} />
            <Select label="Currency" options={currencySelect} {...register("currency")} />
          </Grid>
          <Grid cols={2} gap={3}>
            <Input
              label="Worth today"
              amount
              type="number"
              step={amountInputStep(currency)}
              min="0"
              required
              error={errors.value?.message}
              {...register("value")}
            />
            <Input
              label="What it cost (optional)"
              amount
              type="number"
              step={amountInputStep(currency)}
              min="0"
              {...register("cost")}
            />
          </Grid>
          <Input label="Acquired on" type="date" {...register("acquired_on")} />
          {liabilities.length > 0 && (
            <Select label="Secured by (optional)" {...register("secured_by_debt_id")}>
              <option value="">Owned outright</option>
              {liabilities.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
          )}
          {error && <Banner tone="danger">{error}</Banner>}
          <Inline>
            <Button type="submit" variant="primary" loading={isSubmitting}>
              Save
            </Button>
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
          </Inline>
        </Stack>
      </form>
    </Modal>
  );
}

function AssetDetailModal({ id, onClose }: { id: string; onClose: () => void }) {
  const { data: asset, isLoading } = useAsset(id);
  const record = useRecordValuation();
  const update = useUpdateAsset();
  const remove = useDeleteAsset();
  const { data: accounts } = useAccounts();
  const toast = useToast();
  const [value, setValue] = useState("");
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10));
  const [source, setSource] = useState("owner");
  const [error, setError] = useState<string | null>(null);

  const liabilities = (accounts ?? []).filter(
    (a) => a.account_type === "loan" || a.account_type === "credit_card",
  );

  const saveValuation = async () => {
    if (!asset) return;
    const amount = Number(value);
    if (!amount || amount <= 0) {
      setError("Enter what it is worth.");
      return;
    }
    setError(null);
    try {
      await record.mutateAsync({
        id: asset.id,
        payload: {
          value_minor: majorToMinor(amount, asset.currency),
          as_of: asOf,
          source: source as ValuationSource,
        },
      });
      setValue("");
      toast("Valuation recorded.", { tone: "success" });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't record that valuation.");
    }
  };

  return (
    <Modal open onClose={onClose} title={asset?.name ?? "Asset"}>
      {isLoading || !asset ? (
        <Text tone="tertiary">Loading…</Text>
      ) : (
        <Stack gap={4}>
          <Text size="sm" tone="secondary">
            {ASSET_KIND_LABELS[asset.kind]}
            {asset.acquired_on ? ` · acquired ${asset.acquired_on}` : ""}
          </Text>
          {asset.value_minor == null ? (
            <Banner tone="warning">Not yet valued — it does not change net worth until you give it a figure.</Banner>
          ) : (
            <FigureRow>
              <Figure label="Worth" amountMinor={asset.value_minor} currency={asset.currency} />
              {asset.debt_minor > 0 && (
                <Figure label="Secured debt" amountMinor={asset.debt_minor} currency={asset.currency} />
              )}
              {asset.equity_minor != null && (
                <Figure label="Equity" amountMinor={asset.equity_minor} currency={asset.currency} />
              )}
            </FigureRow>
          )}

          <Stack gap={3}>
            <Text size="sm">New valuation</Text>
            <Grid cols={2} gap={3}>
              <Input
                label="Amount"
                amount
                type="number"
                min="0"
                step={amountInputStep(asset.currency)}
                value={value}
                onChange={(e) => setValue(e.target.value)}
              />
              <Input label="As of" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
            </Grid>
            <Select
              label="Source"
              value={source}
              options={VALUATION_SOURCE_OPTIONS}
              onChange={(e) => setSource(e.target.value)}
            />
            {error && <Banner tone="danger">{error}</Banner>}
            <Button variant="secondary" onClick={saveValuation} loading={record.isPending}>
              Record valuation
            </Button>
          </Stack>

          {liabilities.length > 0 && (
            <Select
              label="Secured by"
              value={asset.secured_debt_account_id ?? ""}
              onChange={async (e) => {
                try {
                  await update.mutateAsync({
                    id: asset.id,
                    payload: { secured_by_debt_id: e.target.value || null },
                  });
                } catch (err) {
                  setError(err instanceof ApiError ? err.detail : "Couldn't update the loan link.");
                }
              }}
            >
              <option value="">Owned outright</option>
              {liabilities.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
          )}

          <Switch
            label="Include in net worth"
            checked={asset.include_in_net_worth}
            onChange={async (e) => {
              try {
                await update.mutateAsync({
                  id: asset.id,
                  payload: { include_in_net_worth: e.target.checked },
                });
              } catch (err) {
                setError(err instanceof ApiError ? err.detail : "Couldn't update that.");
              }
            }}
          />

          {asset.valuations?.length ? (
            <div>
              <Text size="sm" tone="secondary">
                History
              </Text>
              <ul className="lf-asset-history">
                {asset.valuations.map((v) => (
                  <li key={v.id}>
                    <span>{v.as_of}</span>
                    <Money amountMinor={v.value_minor} currency={asset.currency} />
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <ConfirmAction
            label="Remove"
            confirmLabel="Remove"
            variant="danger"
            onConfirm={async () => {
              await remove.mutateAsync(asset.id);
              onClose();
            }}
          />
        </Stack>
      )}
    </Modal>
  );
}
