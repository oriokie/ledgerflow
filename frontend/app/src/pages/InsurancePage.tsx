import { Plus, Shield } from "lucide-react";
import { useState } from "react";
import { z } from "zod";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";

import { ApiError } from "../api/client";
import type { InsurancePolicy, PolicyKind, PremiumFrequency } from "../api/insurance";
import { useAssets } from "../hooks/useAssets";
import {
  useCreatePolicy,
  useDeletePolicy,
  useInsuranceSummary,
  usePolicies,
  usePolicy,
  useUpdatePolicy,
} from "../hooks/useInsurance";
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
  Text,
  useToast,
} from "../ui";
import { POLICY_KIND_LABELS, POLICY_KIND_OPTIONS, PREMIUM_FREQUENCY_OPTIONS } from "./insurance/kinds";

const createSchema = z.object({
  name: z.string().min(1, "Name this policy."),
  kind: z.string().min(1),
  insurer: z.string().optional(),
  currency: z.string().length(3),
  premium: z
    .string()
    .min(1, "What is the premium?")
    .refine((v) => !Number.isNaN(Number(v)) && Number(v) > 0, "Enter an amount greater than zero."),
  premium_frequency: z.string().min(1),
  coverage: z
    .string()
    .optional()
    .refine((v) => !v || (!Number.isNaN(Number(v)) && Number(v) >= 0), "Enter cover of zero or more."),
  covers_asset_id: z.string().optional(),
});
type CreateValues = z.infer<typeof createSchema>;

/**
 * Cover, premium, and the gap against what you own.
 *
 * Nothing here posts to the ledger. A policy is the contract; the premium that
 * actually leaves an account is a bill or a standing order, linked so cash flow
 * does not count it twice.
 */
export function InsurancePage() {
  const { activeWorkspace } = useAuth();
  const books = workspaceCurrency(activeWorkspace?.tenant);
  const { data: policies, isLoading } = usePolicies();
  const { data: summary } = useInsuranceSummary();
  const [showCreate, setShowCreate] = useOpenOnParam();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const list = policies ?? [];
  const currency = summary?.currency ?? books;

  return (
    <>
      <PageHeader
        title="Insurance"
        eyebrow="Position"
        description="What is covered, what it costs, and whether cover still matches what you own."
        actions={
          <Button variant="primary" onClick={() => setShowCreate(true)} icon={<Plus size={15} aria-hidden="true" />}>
            Add a policy
          </Button>
        }
      />

      <Stack gap={4}>
        {isLoading && <SkeletonCard />}

        {!isLoading && list.length === 0 && (
          <Card>
            <EmptyState
              icon={Shield}
              title="No policies recorded"
              body="Cover against a house or a car is unanswerable until the contract is here. Add a policy even if the premium already sits on a bill."
              action={
                <Button variant="primary" onClick={() => setShowCreate(true)}>
                  Add your first policy
                </Button>
              }
              tips={[
                "Link a house or car to see whether cover still matches its value.",
                "If a bill already pays the premium, say so — cash flow will not count it twice.",
                "A gap between cover and value is a fact about two numbers, not a sales pitch.",
              ]}
            />
          </Card>
        )}

        {summary && (
          <Card>
            <FigureRow lead>
              <Figure
                label="Annual premium"
                size="hero"
                amountMinor={summary.annual_premium_minor}
                currency={currency}
                hint={`${summary.count} ${summary.count === 1 ? "policy" : "policies"}`}
              />
              <Figure
                label="Underinsured"
                value={summary.underinsured_count}
                hint={summary.underinsured_count ? "cover below asset value" : "none"}
              />
            </FigureRow>
            {summary.unlinked_count > 0 && (
              <Text size="sm" tone="secondary">
                {summary.unlinked_count}{" "}
                {summary.unlinked_count === 1 ? "premium is" : "premiums are"} not linked to a bill
                and will appear on the cash-flow stack.
              </Text>
            )}
          </Card>
        )}

        {list.length > 0 && (
          <Grid cols={2} gap={3}>
            {list.map((policy) => (
              <PolicyCard key={policy.id} policy={policy} onOpen={() => setSelectedId(policy.id)} />
            ))}
          </Grid>
        )}

        {showCreate && <CreatePolicyModal books={books} onClose={() => setShowCreate(false)} />}
        {selectedId && <PolicyDetailModal id={selectedId} onClose={() => setSelectedId(null)} />}
      </Stack>
    </>
  );
}

function PolicyCard({ policy, onOpen }: { policy: InsurancePolicy; onOpen: () => void }) {
  return (
    <Card>
      <button type="button" className="lf-asset-card" onClick={onOpen}>
        <div className="lf-asset-card-head">
          <strong>{policy.name}</strong>
          <Badge tone={policy.underinsured ? "warning" : "neutral"}>{POLICY_KIND_LABELS[policy.kind]}</Badge>
        </div>
        <Money amountMinor={policy.annual_premium_minor} currency={policy.currency} />
        <Text size="xs" tone="secondary" as="div">
          a year
          {policy.covers_asset_name ? ` · covers ${policy.covers_asset_name}` : ""}
        </Text>
        {policy.underinsured && (
          <Text size="xs" tone="secondary" as="div">
            Cover is below the linked asset's value
          </Text>
        )}
      </button>
    </Card>
  );
}

function CreatePolicyModal({ books, onClose }: { books: string; onClose: () => void }) {
  const create = useCreatePolicy();
  const { data: assets } = useAssets();
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { kind: "home", currency: books, premium_frequency: "annual" },
  });
  const currency = watch("currency") || books;

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      await create.mutateAsync({
        name: values.name,
        kind: values.kind as PolicyKind,
        currency: values.currency,
        insurer: values.insurer || "",
        premium_minor: majorToMinor(Number(values.premium), values.currency),
        premium_frequency: values.premium_frequency as PremiumFrequency,
        coverage_minor: values.coverage ? majorToMinor(Number(values.coverage), values.currency) : null,
        covers_asset_id: values.covers_asset_id || null,
      });
      toast("Policy recorded.", { tone: "success" });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't save this.");
    }
  });

  return (
    <Modal open onClose={onClose} title="Add a policy">
      <form onSubmit={onSubmit} noValidate>
        <Stack gap={3}>
          <Input label="Name" required error={errors.name?.message} {...register("name")} />
          <Grid cols={2} gap={3}>
            <Select label="Kind" options={POLICY_KIND_OPTIONS} {...register("kind")} />
            <Input label="Insurer" {...register("insurer")} />
          </Grid>
          <Grid cols={2} gap={3}>
            <Input
              label="Premium"
              amount
              type="number"
              step={amountInputStep(currency)}
              min="0"
              required
              error={errors.premium?.message}
              {...register("premium")}
            />
            <Select label="Paid" options={PREMIUM_FREQUENCY_OPTIONS} {...register("premium_frequency")} />
          </Grid>
          <Input
            label="Cover (optional)"
            amount
            type="number"
            step={amountInputStep(currency)}
            min="0"
            error={errors.coverage?.message}
            {...register("coverage")}
          />
          {(assets ?? []).length > 0 && (
            <Select label="Covers (optional)" {...register("covers_asset_id")}>
              <option value="">Not linked to an asset</option>
              {(assets ?? []).map((a) => (
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

function PolicyDetailModal({ id, onClose }: { id: string; onClose: () => void }) {
  const { data: policy, isLoading } = usePolicy(id);
  const update = useUpdatePolicy();
  const remove = useDeletePolicy();
  const toast = useToast();

  return (
    <Modal open onClose={onClose} title={policy?.name ?? "Policy"}>
      {isLoading || !policy ? (
        <Text tone="tertiary">Loading…</Text>
      ) : (
        <Stack gap={4}>
          <Text size="sm" tone="secondary">
            {POLICY_KIND_LABELS[policy.kind]}
            {policy.insurer ? ` · ${policy.insurer}` : ""}
          </Text>
          {policy.underinsured && (
            <Banner tone="warning">
              Cover of <Money amountMinor={policy.coverage_minor ?? 0} currency={policy.currency} /> is
              below {policy.covers_asset_name}'s value of{" "}
              <Money amountMinor={policy.asset_value_minor ?? 0} currency={policy.currency} />.
            </Banner>
          )}
          <FigureRow>
            <Figure label="Annual premium" amountMinor={policy.annual_premium_minor} currency={policy.currency} />
            {policy.coverage_minor != null && (
              <Figure label="Cover" amountMinor={policy.coverage_minor} currency={policy.currency} />
            )}
          </FigureRow>
          <Inline>
            <Button
              variant="secondary"
              onClick={async () => {
                await update.mutateAsync({ id: policy.id, payload: { is_active: !policy.is_active } });
                toast(policy.is_active ? "Policy paused." : "Policy active again.", { tone: "success" });
              }}
            >
              {policy.is_active ? "Pause" : "Resume"}
            </Button>
            <ConfirmAction
              label="Remove"
              confirmLabel="Remove"
              variant="danger"
              onConfirm={async () => {
                await remove.mutateAsync(policy.id);
                toast("Policy removed.", { tone: "success" });
                onClose();
              }}
            />
          </Inline>
        </Stack>
      )}
    </Modal>
  );
}
