import { useGoalContributions } from "../../hooks/useGoals";
import { formatDate } from "../../lib/money";
import { Money, Skeleton, Text } from "../../ui";

/** The momentum timeline — a goal's recent contributions, most recent first. */
export function ContributionHistory({ goalId, currency }: { goalId: string; currency: string }) {
  const { data, isLoading } = useGoalContributions(goalId);

  if (isLoading) return <Skeleton width="60%" />;
  if (!data || data.length === 0) {
    return (
      <Text tone="tertiary" size="sm">
        No contributions logged yet.
      </Text>
    );
  }

  return (
    <div style={{ marginTop: "var(--lf-space-2)" }}>
      {data.map((c) => (
        <div key={c.id} className="lf-goal-history-item">
          <span className="lf-cell-meta">
            {formatDate(c.occurred_on)}
            {c.memo ? ` · ${c.memo}` : ""}
          </span>
          <Money amountMinor={c.amount_minor} currency={currency} neutral />
        </div>
      ))}
    </div>
  );
}
