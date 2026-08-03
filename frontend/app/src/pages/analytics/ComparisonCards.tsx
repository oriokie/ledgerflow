import { Figure, FigureRow } from "../../ui";
import { DeltaBadge } from "./DeltaBadge";
import type { Delta, TrendComparison } from "./analyticsMath";

/**
 * This period against the last, across the headline metrics.
 *
 * The deltas used to sit *below* each value in a flex column, which stretched
 * an `inline-flex` pill to the card's full width — so a change indicator read
 * as a progress bar. `Figure` puts it beside the value, where a delta belongs
 * and where it cannot stretch.
 */
function CompareFigure({
  label,
  valueMinor,
  currency,
  delta,
  goodWhen,
  signed,
  provisional,
}: {
  label: string;
  valueMinor: number;
  currency: string;
  delta: Delta;
  goodWhen: "up" | "down";
  signed?: boolean;
  provisional?: boolean;
}) {
  return (
    <Figure
      label={label}
      amountMinor={valueMinor}
      currency={currency}
      neutral={!signed}
      delta={<DeltaBadge delta={delta} goodWhen={goodWhen} provisional={provisional} />}
    />
  );
}

export function ComparisonCards({ comparison, currency }: { comparison: TrendComparison; currency: string }) {
  const c = comparison;
  const savingsPts = (c.savingsRateNow - c.savingsRatePrev) * 100;
  const savingsDelta: Delta = {
    abs: savingsPts,
    pct: savingsPts,
    direction: savingsPts > 0 ? "up" : savingsPts < 0 ? "down" : "flat",
  };
  const partial = c.progress.partial;

  return (
    <>
      <FigureRow>
        <CompareFigure
          label="Income"
          valueMinor={c.current.income_minor}
          currency={currency}
          delta={c.income}
          goodWhen="up"
          provisional={partial}
        />
        <CompareFigure
          label="Expenses"
          valueMinor={c.current.expense_minor}
          currency={currency}
          delta={c.expense}
          goodWhen="down"
          provisional={partial}
        />
        <CompareFigure
          label="Net"
          valueMinor={c.current.net_minor}
          currency={currency}
          delta={c.net}
          goodWhen="up"
          signed
          provisional={partial}
        />
        <Figure
          label="Savings rate"
          value={`${Math.round(c.savingsRateNow * 100)}%`}
          delta={<DeltaBadge delta={savingsDelta} goodWhen="up" provisional={partial} />}
        />
      </FigureRow>

      {/* Say what is being compared. Without this the reader assumes two
          equivalent months, which is only true on the last day of one. */}
      {partial && (
        <p className="lf-compare-basis">
          {c.progress.elapsed} of {c.progress.total} days so far this month, compared against all of last
          month — so these changes are not yet like-for-like.
        </p>
      )}
    </>
  );
}
