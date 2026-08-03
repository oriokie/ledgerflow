import type { IncomeSummary } from "../../api/income";
import { Card, Figure, FigureRow, Meter, Text } from "../../ui";
import { committedBand } from "./incomeCopy";

/**
 * How much of the month is already spoken for.
 *
 * This is the number the product could not compute before there was an income
 * model: it has always known the numerator — bills, debt minimums, recurring
 * expenses — and never had the denominator.
 *
 * Two ratios rather than one. For a salaried household they are identical and
 * the second is noise; for someone on commission or freelance income the gap
 * between them *is* the finding, because the rent is due whether or not the
 * work comes in. Showing only the flattering one would be the more comfortable
 * choice and the wrong one.
 */
export function CommittedIncomeCard({ summary }: { summary: IncomeSummary }) {
  const committed = summary.committed;
  if (!committed || committed.committed_pct === null) return null;

  const { tone, note } = committedBand(committed.committed_pct);
  const fixedPct = committed.committed_against_fixed_pct;
  // Only worth showing when it says something different. "Materially" is a
  // whole percentage point — below that it is rounding, and a second number
  // that restates the first is noise dressed as insight.
  const fixedDiffers = fixedPct !== null && Math.abs(fixedPct - committed.committed_pct) >= 1;

  return (
    <Card title="Committed income" ruledHeader>
      <Meter
        value={committed.committed_pct}
        over={committed.committed_pct > 100}
        label="Committed before any choice"
        caption={`${committed.committed_pct}%`}
        aria-label="Share of monthly income already committed"
      />
      <Text size="sm" tone="secondary">
        {note}
      </Text>

      <FigureRow>
        <Figure
          label="Committed"
          amountMinor={committed.committed_minor}
          currency={summary.currency}
          tone={tone === "positive" ? "default" : tone}
          neutral
        />
        <Figure
          label="Left to direct"
          amountMinor={committed.free_minor}
          currency={summary.currency}
          neutral
          hint="Before everyday spending"
        />
      </FigureRow>

      {fixedDiffers && (
        <Text size="sm" tone="secondary">
          Against income that is actually promised, {fixedPct}% is committed — your commitments
          do not vary with your earnings.
        </Text>
      )}

      {/* What the figure is made of. A ratio nobody can take apart is a ratio
          nobody should be asked to act on. */}
      <FigureRow>
        <Figure
          label="Bills"
          amountMinor={committed.bills_minor}
          currency={summary.currency}
          size="inline"
          neutral
        />
        <Figure
          label="Debt minimums"
          amountMinor={committed.debt_minimums_minor}
          currency={summary.currency}
          size="inline"
          neutral
        />
        <Figure
          label="Recurring"
          amountMinor={committed.recurring_expenses_minor}
          currency={summary.currency}
          size="inline"
          neutral
        />
      </FigureRow>

      <Text size="xs" tone="tertiary">
        Counts only what repeats: recurring bills, debt minimums and standing expenses. One-off
        bills are real obligations but not commitments, so they are left out — otherwise this
        figure would swing on the timing of a single vet visit.
      </Text>
    </Card>
  );
}
