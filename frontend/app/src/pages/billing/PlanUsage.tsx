import type { Subscription } from "../../api/types";
import { Card, Meter, Text } from "../../ui";

/** Proactive visibility of plan limits: shows accounts/members used against the
 * active plan's caps, so people see they're near a limit before an action is
 * blocked. Only meaningful while a metered subscription is active. */
export function PlanUsage({
  subscription,
  accountsUsed,
  membersUsed,
}: {
  subscription: Subscription;
  accountsUsed: number;
  membersUsed: number;
}) {
  const metered = subscription.status === "active" || subscription.status === "trialing";
  if (!metered) return null;

  const { max_accounts, max_members } = subscription.plan;
  return (
    <Card eyebrow="Plan usage" style={{ marginBottom: "var(--lf-space-6)" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--lf-space-4)" }}>
        <UsageRow label="Accounts" used={accountsUsed} limit={max_accounts} />
        <UsageRow label="Members" used={membersUsed} limit={max_members} />
      </div>
    </Card>
  );
}

function UsageRow({ label, used, limit }: { label: string; used: number; limit: number }) {
  const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  const atLimit = used >= limit;
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "var(--lf-space-1)" }}>
        <Text size="sm">{label}</Text>
        <Text size="sm" tone="tertiary" style={atLimit ? { color: "var(--lf-status-danger)" } : undefined}>
          {used} of {limit} used
        </Text>
      </div>
      <Meter value={pct} over={atLimit} aria-label={`${label} usage`} />
    </div>
  );
}
