import { Check, CreditCard, Smartphone } from "lucide-react";
import { useState } from "react";
import { ApiError } from "../api/client";
import type { Payment, Plan } from "../api/types";
import { useAccounts } from "../hooks/useFinance";
import { useMembers } from "../hooks/useTenancy";
import { PlanUsage } from "./billing/PlanUsage";
import {
  useAddPaymentMethod,
  useCancelSubscription,
  useRemovePaymentMethod,
  useSetDefaultPaymentMethod,
  useRetrySubscription,
  usePaymentMethods,
  usePayments,
  usePlans,
  useSubscribe,
  useSubscription,
} from "../hooks/useBilling";
import { useAuth } from "../lib/AuthContext";
import { formatDateLong } from "../lib/money";
import {
  Badge,
  Banner,
  Button,
  Card,
  CardHeader,
  ConfirmAction,
  Grid,
  Heading,
  Inline,
  Input,
  Modal,
  Money,
  PageHeader,
  SegmentedControl,
  Stack,
  Table,
  Text,
} from "../ui";
import type { Column } from "../ui";

const STATUS_TONE: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  active: "success",
  trialing: "success",
  past_due: "warning",
  incomplete: "warning",
  canceled: "danger",
};

const PAYMENT_TONE: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  succeeded: "success",
  pending: "warning",
  failed: "danger",
  refunded: "neutral",
};

export function BillingPage() {
  const { activeWorkspace } = useAuth();
  const [interval, setInterval] = useState<"monthly" | "yearly">("monthly");
  const { data: plans } = usePlans();
  const { data: subscription } = useSubscription();
  const { data: accounts } = useAccounts();
  const { data: members } = useMembers();
  const { data: methods } = usePaymentMethods();
  const { data: payments } = usePayments();
  const subscribe = useSubscribe();
  const cancel = useCancelSubscription();
  const retry = useRetrySubscription();
  const addMethod = useAddPaymentMethod();
  const setDefaultMethod = useSetDefaultPaymentMethod();
  const removeMethod = useRemovePaymentMethod();

  const [showAddCard, setShowAddCard] = useState(false);
  const [showAddMpesa, setShowAddMpesa] = useState(false);
  const [pendingPlan, setPendingPlan] = useState<Plan | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const canManage = activeWorkspace?.role === "owner" || activeWorkspace?.role === "admin";
  const shownPlans = plans?.filter((p) => p.interval === interval) ?? [];
  const currentPlanId = subscription?.plan.id;
  const currentTier = subscription?.plan.tier;
  const tierRank: Record<string, number> = { free: 0, plus: 1, family: 2, business: 3 };

  const choosePlan = async (plan: Plan) => {
    setBanner(null);
    setError(null);
    // Free plan needs no payment method; paid plans do.
    if (plan.price_minor === 0) {
      try {
        await subscribe.mutateAsync({ planId: plan.id });
        setBanner(`You're now on the ${plan.name} plan.`);
      } catch (err) {
        setBanner(err instanceof ApiError ? err.detail : "Couldn't change plan.");
      }
      return;
    }
    if (!methods || methods.length === 0) {
      // No payment method yet — prompt to add one, remember the intended plan.
      setPendingPlan(plan);
      setShowAddCard(true);
      return;
    }
    try {
      const defaultMethod = methods.find((m) => m.is_default) ?? methods[0];
      await subscribe.mutateAsync({ planId: plan.id, paymentMethodId: defaultMethod.id });
      setBanner(`You're now on the ${plan.name} plan.`);
    } catch (err) {
      setBanner(err instanceof ApiError ? err.detail : "Couldn't change plan.");
    }
  };

  const onAddedMethod = async () => {
    // If the person was mid-upgrade, complete it now that a method exists.
    if (pendingPlan) {
      const plan = pendingPlan;
      setPendingPlan(null);
      try {
        await subscribe.mutateAsync({ planId: plan.id });
        setBanner(`You're now on the ${plan.name} plan.`);
      } catch (err) {
        setBanner(err instanceof ApiError ? err.detail : "Card saved, but the plan change failed.");
      }
    }
  };

  const paymentColumns: Column<Payment>[] = [
    { key: "desc", header: "Description", render: (p) => p.description || "Subscription" },
    { key: "date", header: "Date", render: (p) => <span className="lf-cell-meta">{formatDateLong(p.created_at)}</span> },
    {
      key: "method",
      header: "Method",
      hideMobile: true,
      render: (p) => <span className="lf-cell-meta" style={{ textTransform: "capitalize" }}>{p.provider}</span>,
    },
    { key: "status", header: "Status", render: (p) => <Badge tone={PAYMENT_TONE[p.status] ?? "neutral"}>{p.status}</Badge> },
    {
      key: "amount",
      header: "Amount",
      align: "right",
      render: (p) => <Money amountMinor={p.amount_minor} currency={p.currency} neutral />,
    },
  ];

  return (
    <>
      <PageHeader eyebrow={activeWorkspace?.tenant.name} title="Billing & plans" />

      {banner && (
        <Banner tone="success" onDismiss={() => setBanner(null)}>
          {banner}
        </Banner>
      )}

      {/* Current subscription */}
      <Card
        eyebrow="Current plan"
        action={
          subscription ? (
            <Badge tone={STATUS_TONE[subscription.status] ?? "neutral"}>
              {subscription.status.replace(/_/g, " ")}
            </Badge>
          ) : undefined
        }
        style={{ marginBottom: "var(--lf-space-6)" }}
      >
        {subscription ? (
          <>
            <p className="lf-amount lf-amount--hero lf-display" style={{ color: "var(--lf-text-primary)" }}>
              {subscription.plan.name}
            </p>
            {subscription.plan.price_minor > 0 && (
              <Text tone="tertiary" size="sm">
                <Money amountMinor={subscription.plan.price_minor} currency={subscription.plan.currency} neutral /> /{" "}
                {subscription.plan.interval === "yearly" ? "year" : "month"}
              </Text>
            )}
            {subscription.current_period_end && (
              <Text tone="tertiary" size="sm">
                {subscription.cancel_at_period_end ? "Ends" : "Renews"} {formatDateLong(subscription.current_period_end)}
              </Text>
            )}
            {(subscription.status === "past_due" || subscription.status === "incomplete") && (
              <div style={{ marginTop: "var(--lf-space-3)" }}>
                <Banner tone={subscription.status === "past_due" ? "danger" : "warning"}>
                  {subscription.status === "past_due"
                    ? "Your last payment didn't go through. Update your card if needed, then retry to keep your plan active."
                    : "Awaiting payment confirmation. If you paid by M-PESA, approve the prompt on your phone — or retry below."}
                </Banner>
                {canManage && (
                  <Button
                    variant="primary"
                    style={{ marginTop: "var(--lf-space-3)" }}
                    loading={retry.isPending}
                    onClick={async () => {
                      try {
                        await retry.mutateAsync();
                        setBanner("Payment successful — your plan is active again.");
                      } catch (err) {
                        setBanner(err instanceof ApiError ? err.detail : "Couldn't process the payment.");
                      }
                    }}
                  >
                    Retry payment
                  </Button>
                )}
              </div>
            )}
            {canManage && subscription.plan.price_minor > 0 && !subscription.cancel_at_period_end && (
              <Button
                variant="ghost"
                style={{ marginTop: "var(--lf-space-2)" }}
                onClick={async () => {
                  try {
                    await cancel.mutateAsync(true);
                    setBanner("Your plan will not renew. You keep access until the period ends.");
                  } catch (err) {
                    setBanner(err instanceof ApiError ? err.detail : "Couldn't cancel.");
                  }
                }}
              >
                Cancel at period end
              </Button>
            )}
          </>
        ) : (
          <Text tone="secondary">No active plan yet — choose one below.</Text>
        )}
      </Card>

      {subscription && (
        <PlanUsage
          subscription={subscription}
          accountsUsed={accounts?.length ?? 0}
          membersUsed={members?.length ?? 0}
        />
      )}

      {/* Plan chooser */}
      <section style={{ marginBottom: "var(--lf-space-8)" }}>
        <CardHeader>
          <Heading level={2}>Choose a plan</Heading>
          <SegmentedControl
            legend="Billing interval"
            value={interval}
            onChange={setInterval}
            options={[
              { value: "monthly", label: "Monthly" },
              { value: "yearly", label: "Yearly · 2 months free" },
            ]}
          />
        </CardHeader>

        <Grid cols={2} gap={4}>
          {shownPlans.map((plan) => {
            const isCurrent = plan.id === currentPlanId;
            const isDowngrade = currentTier != null && tierRank[plan.tier] < tierRank[currentTier];
            return (
              <Card
                key={plan.id}
                highlight={isCurrent}
                title={plan.name}
                action={isCurrent ? <Badge tone="neutral">Current</Badge> : undefined}
              >
                <p>
                  {plan.price_minor === 0 ? (
                    <span className="lf-amount lf-display">Free</span>
                  ) : (
                    <>
                      <Money amountMinor={plan.price_minor} currency={plan.currency} neutral hero />
                      <span className="lf-hint"> /{plan.interval === "yearly" ? "yr" : "mo"}</span>
                    </>
                  )}
                </p>
                <Text tone="tertiary" size="sm">{plan.description}</Text>
                <ul style={{ listStyle: "none", padding: 0, margin: "var(--lf-space-3) 0" }}>
                  {plan.features.map((f) => (
                    <li key={f} style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
                      <Check size={15} strokeWidth={2.2} style={{ color: "var(--lf-verdant-600)", flexShrink: 0 }} aria-hidden="true" />
                      <span className="lf-text-sm">{f}</span>
                    </li>
                  ))}
                </ul>
                {canManage && !isCurrent && (
                  <Button
                    variant={isDowngrade ? "ghost" : "primary"}
                    disabled={subscribe.isPending}
                    onClick={() => choosePlan(plan)}
                  >
                    {plan.price_minor === 0 ? "Switch to Free" : isDowngrade ? "Downgrade" : "Choose " + plan.name}
                  </Button>
                )}
                {!canManage && !isCurrent && (
                  <Text tone="tertiary" size="sm">Only owners/admins can change the plan.</Text>
                )}
              </Card>
            );
          })}
        </Grid>
      </section>

      {/* Payment methods */}
      <section style={{ marginBottom: "var(--lf-space-8)" }}>
        <CardHeader>
          <Heading level={2}>Payment methods</Heading>
          {canManage && (
            <Inline gap={2}>
              <Button variant="secondary" icon={<CreditCard size={15} />} onClick={() => setShowAddCard(true)}>
                Add card
              </Button>
              <Button variant="secondary" icon={<Smartphone size={15} />} onClick={() => setShowAddMpesa(true)}>
                Add M-PESA
              </Button>
            </Inline>
          )}
        </CardHeader>
        {(!methods || methods.length === 0) && <Text tone="tertiary" size="sm">No payment methods on file.</Text>}
        <Grid cols={3} gap={4}>
          {methods?.map((method) => (
            <Card
              key={method.id}
              title={
                method.kind === "card" ? (
                  <span style={{ textTransform: "capitalize" }}>
                    {method.brand} ****{method.last4}
                  </span>
                ) : (
                  <>M-PESA {method.phone_masked}</>
                )
              }
              action={method.is_default ? <Badge tone="neutral">Default</Badge> : undefined}
            >
              {method.kind === "card" && method.exp_month && (
                <Text tone="tertiary" size="sm">
                  Expires {String(method.exp_month).padStart(2, "0")}/{method.exp_year}
                </Text>
              )}
              {canManage && (
                <Inline gap={2} style={{ marginTop: "var(--lf-space-3)" }}>
                  {/* A method could previously only become the default at the
                      moment it was added; switching back meant deleting and
                      re-adding, which needs a fresh token the user may not have. */}
                  {!method.is_default && (
                    <Button
                      variant="ghost"
                      size="sm"
                      loading={setDefaultMethod.isPending}
                      onClick={() => setDefaultMethod.mutate(method.id)}
                    >
                      Make default
                    </Button>
                  )}
                  <ConfirmAction
                    label="Remove"
                    confirmLabel="Remove"
                    variant="ghost"
                    size="sm"
                    onConfirm={() => removeMethod.mutate(method.id)}
                  />
                </Inline>
              )}
            </Card>
          ))}
        </Grid>
      </section>

      {/* Payment history */}
      {payments && payments.length > 0 && (
        <section>
          <Heading level={2}>Payment history</Heading>
          <div style={{ marginTop: "var(--lf-space-3)" }}>
            <Table columns={paymentColumns} rows={payments} rowKey={(p) => p.id} caption="Payment history" />
          </div>
        </section>
      )}

      {/* Add card modal */}
      <AddCardModal
        open={showAddCard}
        pending={addMethod.isPending}
        error={error}
        onClose={() => {
          setShowAddCard(false);
          setPendingPlan(null);
        }}
        onSubmit={async (token) => {
          setError(null);
          try {
            await addMethod.mutateAsync({ provider: "stripe", token: token || "tok_sandbox_visa", kind: "card" });
            setShowAddCard(false);
            onAddedMethod();
          } catch (err) {
            setError(err instanceof ApiError ? err.detail : "Couldn't add the card.");
          }
        }}
      />

      {/* Add M-PESA modal */}
      <AddMpesaModal
        open={showAddMpesa}
        pending={addMethod.isPending}
        error={error}
        onClose={() => setShowAddMpesa(false)}
        onSubmit={async (phone) => {
          setError(null);
          if (!/^\d{9,15}$/.test(phone.replace(/\D/g, ""))) {
            setError("Enter a valid phone number, e.g. 254712345678.");
            return;
          }
          try {
            await addMethod.mutateAsync({ provider: "mpesa", token: phone.replace(/\D/g, ""), kind: "mpesa" });
            setShowAddMpesa(false);
            onAddedMethod();
          } catch (err) {
            setError(err instanceof ApiError ? err.detail : "Couldn't add M-PESA.");
          }
        }}
      />
    </>
  );
}

// --- module-level modals (defined outside the page so their inputs keep focus) ---

function AddCardModal({
  open,
  pending,
  error,
  onClose,
  onSubmit,
}: {
  open: boolean;
  pending: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (token: string) => void;
}) {
  const [token, setToken] = useState("");
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add a card"
      footer={
        <Button variant="primary" icon={<CreditCard size={15} />} onClick={() => onSubmit(token)} loading={pending}>
          Add card
        </Button>
      }
    >
      <Stack gap={4}>
        <Text tone="tertiary" size="sm">
          In production this uses Stripe Elements, so card details go straight to Stripe and never touch our
          servers. For this sandbox, just click Add.
        </Text>
        <Input
          label="Card token (Stripe.js) — optional in sandbox"
          placeholder="pm_… (leave blank for sandbox)"
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        {error && <Banner tone="danger">{error}</Banner>}
      </Stack>
    </Modal>
  );
}

function AddMpesaModal({
  open,
  pending,
  error,
  onClose,
  onSubmit,
}: {
  open: boolean;
  pending: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (phone: string) => void;
}) {
  const [phone, setPhone] = useState("");
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add M-PESA"
      footer={
        <Button variant="primary" icon={<Smartphone size={15} />} onClick={() => onSubmit(phone)} loading={pending}>
          Add M-PESA
        </Button>
      }
    >
      <Stack gap={4}>
        <Text tone="tertiary" size="sm">
          Paying by M-PESA sends an STK push to this number — you approve the payment on your phone. We store
          only a masked version of the number.
        </Text>
        <Input
          label="Phone number"
          placeholder="254712345678"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          inputMode="numeric"
        />
        {error && <Banner tone="danger">{error}</Banner>}
      </Stack>
    </Modal>
  );
}
