import { PiggyBank, Target } from "lucide-react";
import { Link } from "react-router-dom";
import type { Budget, BudgetStatus, SavingsGoal } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { Badge, Card, EmptyState, Meter } from "../../ui";

export function BudgetProgress({
  budget,
  status,
  currency,
}: {
  budget: Budget | undefined;
  status: BudgetStatus | undefined;
  currency: string;
}) {
  const lines = (status?.lines ?? [])
    .slice()
    .sort((a, b) => b.percent_used - a.percent_used)
    .slice(0, 4);

  return (
    <Card
      title="Budget"
      action={
        <Link to="/budgets" className="lf-section-link">
          Manage
        </Link>
      }
    >
      {!budget || lines.length === 0 ? (
        <EmptyState
          icon={PiggyBank}
          title="No budget yet"
          body="Set category limits to track spending against a plan."
          action={
            <Link to="/budgets" className="lf-btn lf-btn--secondary lf-btn--sm">
              Create a budget
            </Link>
          }
        />
      ) : (
        <div className="lf-disclosure-panel" style={{ marginTop: 0 }}>
          {lines.map((l) => (
            <Meter
              key={l.line_id}
              value={l.percent_used}
              over={l.over_budget}
              label={l.category_name}
              caption={`${formatAmount(l.actual_minor, budget.currency || currency)} of ${formatAmount(
                l.effective_limit_minor,
                budget.currency || currency,
              )}`}
            />
          ))}
        </div>
      )}
    </Card>
  );
}

export function GoalsProgress({ goals, currency }: { goals: SavingsGoal[] | undefined; currency: string }) {
  const active = (goals ?? []).filter((g) => g.status !== "archived").slice(0, 4);

  return (
    <Card
      title="Savings goals"
      action={
        <Link to="/goals" className="lf-section-link">
          All goals
        </Link>
      }
    >
      {active.length === 0 ? (
        <EmptyState
          icon={Target}
          title="No goals yet"
          body="Set a target and watch your progress build."
          action={
            <Link to="/goals" className="lf-btn lf-btn--secondary lf-btn--sm">
              Create a goal
            </Link>
          }
        />
      ) : (
        <div className="lf-disclosure-panel" style={{ marginTop: 0 }}>
          {active.map((g) => (
            <Meter
              key={g.id}
              value={g.percent}
              aria-label={`${g.name} progress`}
              label={
                <span style={{ display: "inline-flex", alignItems: "center", gap: "var(--lf-space-2)" }}>
                  {g.name}
                  {g.is_met && <Badge tone="success">Met</Badge>}
                </span>
              }
              caption={`${formatAmount(g.saved_minor, g.currency || currency)} of ${formatAmount(
                g.target_minor,
                g.currency || currency,
              )}`}
            />
          ))}
        </div>
      )}
    </Card>
  );
}
