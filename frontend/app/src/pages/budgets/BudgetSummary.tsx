import { CalendarClock, TrendingUp } from "lucide-react";
import type { BudgetStatus } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { Card, Figure, FigureRow } from "../../ui";
import { BudgetProgressBar } from "./BudgetProgressBar";
import {
  budgetTotals,
  MIN_DAYS_FOR_PACE,
  overPace,
  paceIsMeaningful,
  periodProgress,
  projectedSpendMinor,
  WARNING_THRESHOLD,
} from "./budgetMath";

/** Top-of-page overview: budgeted vs spent vs remaining, one big bar with the
 * pace marker, and a plain-language verdict on whether spending is on pace. */
export function BudgetSummary({ status, currency }: { status: BudgetStatus; currency: string }) {
  const totals = budgetTotals(status.lines);
  const pace = periodProgress(status);

  const overallState =
    totals.remaining_minor < 0 ? "over" : totals.percent >= WARNING_THRESHOLD ? "warning" : "under";
  const judgeable = paceIsMeaningful(pace);
  const ahead = overPace(totals.percent, pace.elapsedPercent);
  const projected = projectedSpendMinor(totals.spent_minor, pace.elapsedFraction);
  const projectedOver = projected !== null && projected > totals.budgeted_minor;

  return (
    <Card>
      <FigureRow lead>
        <Figure
          label="Spent"
          size="hero"
          amountMinor={totals.spent_minor}
          currency={currency}
          neutral
        />
        <Figure label="Budgeted" amountMinor={totals.budgeted_minor} currency={currency} neutral />
        <Figure
          label={totals.remaining_minor < 0 ? "Over by" : "Remaining"}
          amountMinor={Math.abs(totals.remaining_minor)}
          currency={currency}
          neutral
          tone={totals.remaining_minor < 0 ? "critical" : "default"}
        />
      </FigureRow>

      <BudgetProgressBar
        percentUsed={totals.percent}
        state={overallState}
        pacePercent={pace.elapsedPercent}
        size="lg"
        ariaLabel="Overall budget used"
      />

      <div className="lf-budget-pace-note" data-tone={ahead && judgeable ? "over" : undefined}>
        <CalendarClock size={15} strokeWidth={1.8} aria-hidden="true" />
        <span>
          Day {pace.daysElapsed} of {pace.daysTotal} · {pace.daysLeft} left
        </span>
        <span aria-hidden="true">·</span>
        {/* Early in a period almost every budget is trivially "on track", and
            saying so in the same words used on day 20 trains the reader to
            ignore the verdict when it finally means something. */}
        {!judgeable ? (
          <span>Too early to tell — pace shows from day {MIN_DAYS_FOR_PACE + 1}</span>
        ) : ahead ? (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <TrendingUp size={15} strokeWidth={1.8} aria-hidden="true" />
            Ahead of pace
            {projectedOver && projected !== null
              ? ` — on track to spend ${formatAmount(projected, currency)}`
              : ""}
          </span>
        ) : (
          <span>On track for this period</span>
        )}
      </div>
    </Card>
  );
}
