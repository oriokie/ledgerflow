import { Inbox } from "lucide-react";
import { useMemo, useState } from "react";

import type { Plan } from "../../api/platform";
import { ApiError } from "../../api/client";
import { AdminPageHeader } from "../../components/admin/AdminPageHeader";
import { ReasonDialog } from "../../components/admin/AdminShell";
import {
  useCapability,
  usePlanCatalogue,
  usePlatformMe,
  usePlatformPlans,
  useUpdatePlan,
} from "../../hooks/usePlatform";
import {
  Badge,
  Button,
  Card,
  Checkbox,
  EmptyState,
  Input,
  LoadingBlock,
  Modal,
  Stack,
  Switch,
  Table,
  Text,
  Textarea,
  useToast,
} from "../../ui";
import type { Column } from "../../ui";
import { humanize, money } from "./format";

/** The draft an editor accumulates before giving a reason. */
interface PlanDraft {
  name: string;
  description: string;
  price: string;
  max_accounts: string;
  max_members: string;
  ai_insights: boolean;
  is_active: boolean;
  features: string[];
}

function draftFrom(plan: Plan): PlanDraft {
  return {
    name: plan.name,
    description: plan.description,
    price: String(plan.price_minor / 100),
    max_accounts: String(plan.max_accounts),
    max_members: String(plan.max_members),
    ai_insights: plan.ai_insights,
    is_active: plan.is_active,
    features: [...plan.features],
  };
}

/**
 * The commercial catalogue.
 *
 * Everything the pricing page sells and the entitlement layer enforces is a
 * row here. The page exists so that changing what a plan includes is a console
 * action with a reason and an audit entry — not a deploy.
 */
export function AdminPlansPage() {
  const { data: me } = usePlatformMe();
  const can = useCapability(me);
  const { data: plans, isLoading } = usePlatformPlans(true);
  const { data: catalogue } = usePlanCatalogue();
  const update = useUpdatePlan();
  const toast = useToast();

  const [editing, setEditing] = useState<Plan | null>(null);
  const [draft, setDraft] = useState<PlanDraft | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const labels = catalogue?.labels ?? {};
  const editable = can("plan.manage");

  /** Features a tier grants by default — locked on in the editor, because the
   * resolution is a union: an override can add, never remove. */
  const tierDefaults = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const tier of catalogue?.tiers ?? []) map.set(tier.tier, new Set(tier.features));
    return map;
  }, [catalogue]);

  const openEditor = (plan: Plan) => {
    setEditing(plan);
    setDraft(draftFrom(plan));
    setError(null);
  };

  const payloadFrom = (d: PlanDraft) => ({
    name: d.name,
    description: d.description,
    price_minor: Math.round(Number.parseFloat(d.price || "0") * 100),
    max_accounts: Number(d.max_accounts),
    max_members: Number(d.max_members),
    ai_insights: d.ai_insights,
    is_active: d.is_active,
    features: d.features,
  });

  const onConfirm = async (reason: string) => {
    if (!editing || !draft) return;
    setError(null);
    try {
      await update.mutateAsync({
        planId: editing.id,
        payload: { ...payloadFrom(draft), reason },
      });
      toast("Plan updated — the change is in the audit log.", { tone: "success" });
      setConfirming(false);
      setEditing(null);
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Could not save the plan.");
    }
  };

  const columns: Column<Plan>[] = [
    {
      key: "name",
      header: "Plan",
      render: (row) => (
        <div>
          <strong>{row.name}</strong>
          <Text size="xs" tone="tertiary">
            {humanize(row.tier)} · {humanize(row.interval)}
          </Text>
        </div>
      ),
    },
    {
      key: "price",
      header: "Price",
      align: "right",
      render: (row) =>
        row.price_minor === 0 ? "Free" : `${money(row.price_minor, row.currency)}`,
    },
    {
      key: "limits",
      header: "Limits",
      hideMobile: true,
      render: (row) => `${row.max_accounts} accounts · ${row.max_members} seats`,
    },
    {
      key: "features",
      header: "Includes",
      hideMobile: true,
      render: (row) => (
        <span>
          {row.resolved_features.length} features
          {row.features.length > 0 && (
            <Text as="span" size="xs" tone="tertiary">
              {" "}
              · {row.features.length} extra
            </Text>
          )}
        </span>
      ),
    },
    {
      key: "subscribers",
      header: "Subscribers",
      align: "right",
      render: (row) => String(row.subscriber_count),
    },
    {
      key: "state",
      header: "State",
      render: (row) =>
        row.is_active ? <Badge tone="success">Active</Badge> : <Badge tone="neutral">Retired</Badge>,
    },
    {
      key: "actions",
      header: "",
      render: (row) =>
        editable ? (
          <Button size="sm" variant="ghost" onClick={() => openEditor(row)}>
            Edit
          </Button>
        ) : null,
    },
  ];

  return (
    <Stack gap={4}>
      <AdminPageHeader
        title="Plans"
        description="The commercial catalogue: what each plan costs, its limits, and the features it unlocks. The pricing page and the entitlement checks both read these rows — an edit here changes what every subscriber gets, so each one asks for a reason."
        meta={plans ? `${plans.length} plan${plans.length === 1 ? "" : "s"}` : undefined}
      />

      {isLoading && !plans ? (
        <LoadingBlock />
      ) : plans?.length ? (
        <Table columns={columns} rows={plans} rowKey={(r) => r.id} responsive stickyHeader />
      ) : (
        <Card>
          <EmptyState
            icon={Inbox}
            title="No plans"
            body="Seed the catalogue to offer subscriptions."
          />
        </Card>
      )}

      {editing && draft && (
        <Modal open onClose={() => setEditing(null)} title={`Edit ${editing.name}`}>
          <Stack gap={3}>
            <Text size="sm" tone="secondary">
              {editing.subscriber_count === 0
                ? "No live subscribers are on this plan."
                : `${editing.subscriber_count} live subscriber${
                    editing.subscriber_count === 1 ? "" : "s"
                  } will be affected by limit and feature changes.`}
            </Text>

            <Input
              label="Name"
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
            <Textarea
              label="Description"
              hint="The pitch line the pricing page shows."
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            />
            <Input
              label={`Price per ${editing.interval === "annual" ? "year" : "month"} (${editing.currency})`}
              type="number"
              min="0"
              step="0.01"
              value={draft.price}
              onChange={(e) => setDraft({ ...draft, price: e.target.value })}
            />
            <div className="lf-grid lf-grid--2 lf-gap-3">
              <Input
                label="Max accounts"
                type="number"
                min="1"
                value={draft.max_accounts}
                onChange={(e) => setDraft({ ...draft, max_accounts: e.target.value })}
              />
              <Input
                label="Max people"
                type="number"
                min="1"
                value={draft.max_members}
                onChange={(e) => setDraft({ ...draft, max_members: e.target.value })}
              />
            </div>
            <Switch
              label="AI insights"
              checked={draft.ai_insights}
              onChange={(e) => setDraft({ ...draft, ai_insights: e.target.checked })}
            />
            <Switch
              label="Active — offered to new signups"
              checked={draft.is_active}
              onChange={(e) => setDraft({ ...draft, is_active: e.target.checked })}
            />

            <div>
              <Text size="sm" weight="medium">
                Features
              </Text>
              <Text size="xs" tone="tertiary">
                Features from the {humanize(editing.tier)} tier are always included — an override
                can add to a tier, never subtract from it. Universal features (the ledger,
                reconciliation, export, 2FA) are on every plan and are not listed.
              </Text>
              <div className="lf-admin-feature-grid">
                {Object.entries(labels)
                  .filter(([key]) => !(catalogue?.universal ?? []).includes(key))
                  .map(([key, label]) => {
                    const inherited = tierDefaults.get(editing.tier)?.has(key) ?? false;
                    const checked = inherited || draft.features.includes(key);
                    return (
                      <Checkbox
                        key={key}
                        label={inherited ? `${label} — included with ${humanize(editing.tier)}` : label}
                        checked={checked}
                        disabled={inherited}
                        onChange={(e) =>
                          setDraft({
                            ...draft,
                            features: e.target.checked
                              ? [...draft.features, key]
                              : draft.features.filter((f) => f !== key),
                          })
                        }
                      />
                    );
                  })}
              </div>
            </div>

            <div className="lf-inline lf-gap-2">
              <Button variant="primary" onClick={() => setConfirming(true)}>
                Save changes
              </Button>
              <Button variant="ghost" onClick={() => setEditing(null)}>
                Cancel
              </Button>
            </div>
          </Stack>
        </Modal>
      )}

      {confirming && editing && (
        <ReasonDialog
          open
          title={`Update ${editing.name}`}
          confirmLabel="Save plan"
          destructive={editing.subscriber_count > 0}
          pending={update.isPending}
          error={error}
          onClose={() => setConfirming(false)}
          onConfirm={onConfirm}
          description={
            editing.subscriber_count > 0
              ? `This plan has ${editing.subscriber_count} live subscriber${
                  editing.subscriber_count === 1 ? "" : "s"
                }. The change takes effect for all of them.`
              : undefined
          }
        />
      )}
    </Stack>
  );
}
