import type { SavingsGoal } from "../../api/types";
import { Card, Figure, FigureRow, Meter } from "../../ui";
import { goalTotals } from "./goalMath";

/** A motivating overview across all live goals: how much saved toward how much,
 * and how many are already achieved. */
export function GoalsSummary({ goals }: { goals: SavingsGoal[] }) {
  const totals = goalTotals(goals);
  if (totals.activeCount === 0) return null;

  return (
    <Card>
      {/* Three figures, three different treatments: a hero `Money`, a default
          `Money`, and a hand-styled <span> carrying its size, weight and colour
          inline — which is why they sat on three different baselines. */}
      <FigureRow lead>
        <Figure
          label="Saved across goals"
          size="hero"
          amountMinor={totals.saved_minor}
          currency={totals.currency}
          neutral
        />
        <Figure label="Target" amountMinor={totals.target_minor} currency={totals.currency} neutral />
        <Figure label="Achieved" value={`${totals.achievedCount} of ${totals.activeCount}`} />
      </FigureRow>
      <div style={{ marginTop: "var(--lf-space-5)" }}>
        {/* The percentage rides the meter it describes. It used to float at the
            far right of the card, ~1,100px from the label it qualifies. */}
        <Meter
          value={Math.min(100, totals.percent)}
          label="Overall progress"
          caption={`${Math.round(totals.percent)}%`}
        />
      </div>
    </Card>
  );
}
