import { Link } from "react-router-dom";
import { useIncomeSummary } from "../../hooks/useIncome";
import { Card, Figure, FigureRow, Meter, Text } from "../../ui";
import { committedBand } from "../income/incomeCopy";

/**
 * How much of the month is already spoken for — the dashboard's version.
 *
 * Renders **nothing** when no income is recorded. A dashboard card that says
 * "0% committed" to someone who has not told us what they earn is worse than
 * no card: it reads as a clean bill of health derived from an absence.
 *
 * Deliberately three numbers and a bar. The full breakdown lives on the income
 * screen; repeating it here would make the dashboard the second-best version of
 * a page that already exists.
 */
export function CommittedIncomeStrip() {
  const { data: summary } = useIncomeSummary();
  const committed = summary?.committed;
  if (!summary || !committed || committed.committed_pct === null) return null;

  const { tone, note } = committedBand(committed.committed_pct);

  return (
    <Card
      accent="money"
      title="Committed income"
      action={
        <Link className="lf-section-link" to="/income">
          Income
        </Link>
      }
    >
      <Meter
        value={committed.committed_pct}
        over={committed.committed_pct > 100}
        caption={`${committed.committed_pct}%`}
        aria-label="Share of monthly income already committed"
      />

      <FigureRow>
        <Figure
          label="Monthly income"
          amountMinor={summary.monthly_net_minor}
          currency={summary.currency}
          neutral
          certainty="projected"
        />
        <Figure
          label="Committed"
          amountMinor={committed.committed_minor}
          currency={summary.currency}
          neutral
          tone={tone === "positive" ? "default" : tone}
        />
        <Figure
          label="Left to direct"
          amountMinor={committed.free_minor}
          currency={summary.currency}
          neutral
          hint="Before everyday spending"
        />
      </FigureRow>

      <Text size="sm" tone="secondary">
        {note}
      </Text>
    </Card>
  );
}
