import { Link } from "react-router-dom";
import type { GoalForecast, SavingsGoal } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { Illustration } from "../../ui/illustration";
import { Badge, Meter } from "../../ui";

export function GoalsPulse({
  goals,
  forecasts,
  currency,
}: {
  goals: SavingsGoal[] | undefined;
  forecasts: GoalForecast[] | undefined;
  currency: string;
}) {
  const active = (goals ?? []).filter((g) => g.status !== "archived").slice(0, 4);
  const forecastById = new Map((forecasts ?? []).map((f) => [f.goal_id, f]));

  return (
    <section className="lf-cmd-panel lf-cmd-panel--rail" aria-labelledby="lf-goals-title">
      <header className="lf-cmd-panel-head">
        <h2 id="lf-goals-title">Goals</h2>
        <Link className="lf-section-link" to="/goals">
          All goals
        </Link>
      </header>

      {active.length === 0 ? (
        <div className="lf-cmd-quiet lf-cmd-quiet--compact">
          <Illustration name="growth" size="spot" />
          <p>Set a target and watch progress — projected completion appears once contributions land.</p>
          <Link className="lf-btn lf-btn--secondary lf-btn--sm" to="/goals">
            Create a goal
          </Link>
        </div>
      ) : (
        <ul className="lf-goal-pulse-list">
          {active.map((g) => {
            const fc = forecastById.get(g.id);
            const projected = fc?.projected_completion;
            const onTrack = fc?.on_track;
            return (
              <li key={g.id} className="lf-goal-pulse-item">
                <Meter
                  value={g.percent}
                  aria-label={`${g.name} progress`}
                  label={
                    <span className="lf-budget-line-label">
                      {g.name}
                      {g.is_met && <Badge tone="success">Met</Badge>}
                      {onTrack === true && !g.is_met && <Badge tone="success">On track</Badge>}
                      {onTrack === false && !g.is_met && <Badge tone="warning">Behind</Badge>}
                    </span>
                  }
                  caption={`${formatAmount(g.saved_minor, g.currency || currency)} of ${formatAmount(
                    g.target_minor,
                    g.currency || currency,
                  )}`}
                />
                {projected && !g.is_met && (
                  <p className="lf-goal-pulse-eta">
                    Projected{" "}
                    {new Date(projected).toLocaleDateString(undefined, {
                      month: "short",
                      year: "numeric",
                    })}
                    {fc?.success_probability != null
                      ? ` · ${Math.round(fc.success_probability * 100)}% confidence`
                      : ""}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
