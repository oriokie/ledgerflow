import { Link } from "react-router-dom";
import type { Budget, BudgetStatus } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { Illustration } from "../../ui/illustration";
import { Badge, Meter } from "../../ui";

export function BudgetPulse({
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
    .sort((a, b) => {
      if (a.over_budget !== b.over_budget) return a.over_budget ? -1 : 1;
      return b.percent_used - a.percent_used;
    });

  const exceptions = lines.filter((l) => l.over_budget || l.percent_used >= 85);
  const shown = (exceptions.length > 0 ? exceptions : lines).slice(0, 5);

  return (
    <section className="lf-cmd-panel lf-cmd-panel--rail" aria-labelledby="lf-budget-title">
      <header className="lf-cmd-panel-head">
        <h2 id="lf-budget-title">Budget pulse</h2>
        <Link className="lf-section-link" to="/plan?tab=budgets">
          Manage
        </Link>
      </header>

      {!budget || lines.length === 0 ? (
        <div className="lf-cmd-quiet lf-cmd-quiet--compact">
          <Illustration name="envelope" size="spot" />
          <p>No budget yet. Category limits turn spending into decisions.</p>
          <Link className="lf-btn lf-btn--secondary lf-btn--sm" to="/plan?tab=budgets">
            Create a budget
          </Link>
        </div>
      ) : (
        <>
          {exceptions.length > 0 && (
            <p className="lf-cmd-panel-sub">
              {exceptions.length} categor{exceptions.length === 1 ? "y" : "ies"} need a look first.
            </p>
          )}
          <div className="lf-disclosure-panel" style={{ marginTop: 0 }}>
            {shown.map((l) => (
              <div key={l.line_id} className="lf-budget-line">
                <Meter
                  value={l.percent_used}
                  over={l.over_budget}
                  label={
                    <span className="lf-budget-line-label">
                      {l.category_name}
                      {l.over_budget && <Badge tone="danger">Over</Badge>}
                      {!l.over_budget && l.percent_used >= 90 && (
                        <Badge tone="warning">Tight</Badge>
                      )}
                    </span>
                  }
                  caption={`${formatAmount(l.actual_minor, budget.currency || currency)} of ${formatAmount(
                    l.effective_limit_minor,
                    budget.currency || currency,
                  )}`}
                />
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
