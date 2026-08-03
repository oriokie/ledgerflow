import { Check } from "lucide-react";
import type { SavingsGoal } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { milestones } from "./goalMath";

/** The four checkpoints laid out as a track — each lights up as it's reached,
 * with the final one showing the target amount. */
export function MilestoneTrack({ goal, currency }: { goal: SavingsGoal; currency: string }) {
  const marks = milestones(goal);
  return (
    <div className="lf-goal-milestones" aria-hidden="true">
      <div className="lf-goal-ms-line" />
      {marks.map((m) => (
        <div key={m.pct} className="lf-goal-ms" data-reached={m.reached} data-final={m.pct === 100}>
          <span className="lf-goal-ms-dot">{m.reached && <Check size={10} strokeWidth={3} />}</span>
          <span className="lf-goal-ms-label">{m.pct === 100 ? formatAmount(m.amountMinor, currency) : `${m.pct}%`}</span>
        </div>
      ))}
    </div>
  );
}
