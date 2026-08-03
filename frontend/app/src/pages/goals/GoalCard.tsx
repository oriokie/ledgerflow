import { Trophy } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ApiError } from "../../api/client";
import type { GoalForecast, SavingsGoal } from "../../api/types";
import { useContributeToGoal } from "../../hooks/useGoals";
import { formatAmount, majorToMinor } from "../../lib/money";
import { Badge, Banner, Button, Card, Chip, ConfirmAction, Input, Money, Text } from "../../ui";
import { AddFundsModal } from "./AddFundsModal";
import { ContributionHistory } from "./ContributionHistory";
import { GoalForecastPanel } from "./GoalForecastPanel";
import { GOAL_KIND_ICONS, GOAL_KIND_LABELS, GOAL_PRIORITY_LABELS } from "./kinds";
import { GoalProgressRing } from "./GoalProgressRing";
import { MilestoneTrack } from "./MilestoneTrack";
import { amountToNextMilestone, nextMilestone } from "./goalMath";

const QUICK_ADDS_MINOR = [2500, 5000, 10000];

export function GoalCard({
  goal,
  forecast,
  onArchive,
}: {
  goal: SavingsGoal;
  /** Forecast for this goal. Optional so the card paints progress immediately
   * while the forecast (which reads contribution history) resolves. */
  forecast?: GoalForecast;
  onArchive: (goalId: string) => void;
}) {
  const contribute = useContributeToGoal();
  const currency = goal.currency;
  const KindIcon = GOAL_KIND_ICONS[goal.kind] ?? GOAL_KIND_ICONS.custom;
  const next = nextMilestone(goal);
  const toNext = amountToNextMilestone(goal);
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [showFunds, setShowFunds] = useState(false);

  const add = async (amountMinor: number) => {
    setError(null);
    try {
      await contribute.mutateAsync({ goalId: goal.id, amountMinor });
      return true;
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't add that contribution.");
      return false;
    }
  };

  const onCustom = async (e: FormEvent) => {
    e.preventDefault();
    const value = Number(amount);
    if (!value || value <= 0) {
      setError("Enter an amount greater than zero.");
      return;
    }
    if (await add(majorToMinor(value))) setAmount("");
  };

  return (
    <Card>
      <div className="lf-goal-head">
        <GoalProgressRing percent={goal.percent} met={goal.is_met} savedMinor={goal.saved_minor} currency={currency} />
        <div className="lf-goal-head-main">
          <h3 className="lf-goal-name" style={{ display: "inline-flex", alignItems: "center", gap: "var(--lf-space-2)" }}>
            {goal.name}
            {goal.is_met && <Badge tone="success">Achieved</Badge>}
            {goal.auto_contribute_enabled && (
              <Badge tone="neutral">Auto {formatAmount(goal.auto_contribute_minor ?? 0, currency)}/mo</Badge>
            )}
          </h3>
          {/* Kind and priority orient the user before any numbers do. */}
          <div className="lf-goal-kindline">
            <KindIcon size={13} strokeWidth={1.8} aria-hidden="true" />
            <span>{GOAL_KIND_LABELS[goal.kind] ?? "Goal"}</span>
            {goal.priority <= 2 && (
              <span className="lf-goal-priority">{GOAL_PRIORITY_LABELS[goal.priority]}</span>
            )}
          </div>
          <div className="lf-goal-figures">
            <Money amountMinor={goal.saved_minor} currency={currency} neutral /> of {formatAmount(goal.target_minor, currency)}
          </div>
          {!goal.is_met && next && toNext > 0 && (
            <div className="lf-goal-nudge">
              {formatAmount(toNext, currency)} to {next.pct === 100 ? "reach your goal" : `${next.pct}%`}
            </div>
          )}
          {!forecast && goal.required_monthly_minor != null && !goal.is_met && (
            <Text tone="tertiary" size="sm" style={{ marginTop: "var(--lf-space-1)" }}>
              Set aside {formatAmount(goal.required_monthly_minor, currency)}/month to hit your date.
            </Text>
          )}
        </div>
      </div>

      <MilestoneTrack goal={goal} currency={currency} />

      {forecast && <GoalForecastPanel forecast={forecast} />}

      {goal.is_met ? (
        <div className="lf-goal-celebrate">
          <Trophy size={22} strokeWidth={1.8} aria-hidden="true" />
          <div>
            <div className="lf-goal-celebrate-title">Goal reached!</div>
            <div style={{ fontSize: "var(--lf-text-sm)" }}>You saved {formatAmount(goal.saved_minor, currency)}.</div>
          </div>
        </div>
      ) : goal.tracking === "manual" ? (
        <div className="lf-goal-quickadd">
          {QUICK_ADDS_MINOR.map((m) => (
            <Chip key={m} onClick={() => add(m)}>
              +{formatAmount(m, currency)}
            </Chip>
          ))}
          <form className="lf-goal-quickadd-form" onSubmit={onCustom}>
            <Input
              amount
              type="number"
              step="0.01"
              min="0.01"
              placeholder="Custom"
              aria-label={`Contribute to ${goal.name}`}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
            <Button type="submit" variant="secondary" size="sm" loading={contribute.isPending}>
              Add
            </Button>
          </form>
          {/* The chips and inline field record money already set aside. This
              opens the full choice, including moving it out of an account. */}
          <Button variant="ghost" size="sm" onClick={() => setShowFunds(true)}>
            Add funds…
          </Button>
        </div>
      ) : (
        <Text tone="tertiary" size="sm">
          Tracks the linked account balance automatically.
        </Text>
      )}

      {error && (
        <div style={{ marginTop: "var(--lf-space-2)" }}>
          <Banner tone="danger">{error}</Banner>
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "var(--lf-space-3)" }}>
        <Button variant="ghost" size="sm" onClick={() => setShowHistory((v) => !v)}>
          {showHistory ? "Hide history" : "History"}
        </Button>
        {!goal.is_met && (
          <ConfirmAction
            label="Archive"
            confirmLabel="Archive goal"
            cancelLabel="Keep"
            variant="secondary"
            onConfirm={() => onArchive(goal.id)}
          />
        )}
      </div>

      {showHistory && <ContributionHistory goalId={goal.id} currency={currency} />}

      {/* Mounted only while open. A goals page renders one card per goal, and
          an always-mounted modal would have each of them subscribing to the
          accounts query for a dialog nobody has asked for yet. */}
      {showFunds && (
        <AddFundsModal open onClose={() => setShowFunds(false)} goal={goal} />
      )}
    </Card>
  );
}
