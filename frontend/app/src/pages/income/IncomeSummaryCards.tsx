import type { IncomeSummary } from "../../api/income";
import { Card, Figure, FigureRow, Text } from "../../ui";

/**
 * The household's income position.
 *
 * Every figure here can legitimately be *unknown*, and each one says so rather
 * than falling back to a zero. A take-home rate of 100% for someone who is
 * taxed is the single most misleading number this feature could produce, and
 * it is exactly what a `?? 0` would render.
 */
export function IncomeSummaryCards({ summary }: { summary: IncomeSummary }) {
  const { currency } = summary;
  const incomplete = summary.ad_hoc_count > 0;

  return (
    <>
      <Card title="Monthly income" ruledHeader>
        <FigureRow lead>
          <Figure
            label="Take home"
            size="hero"
            amountMinor={summary.monthly_net_minor}
            currency={currency}
            neutral
            certainty="projected"
            hint={
              incomplete
                ? `Excludes ${summary.ad_hoc_count} source${summary.ad_hoc_count > 1 ? "s" : ""} with no set schedule`
                : "Averaged across your pay cadences"
            }
          />
          {summary.monthly_gross_minor !== null ? (
            <Figure
              label="Before deductions"
              amountMinor={summary.monthly_gross_minor}
              currency={currency}
              neutral
              certainty="projected"
            />
          ) : (
            <Figure
              label="Before deductions"
              value="—"
              hint="Add a gross amount to see this"
            />
          )}
          {summary.take_home_rate !== null ? (
            <Figure
              label="You keep"
              value={`${summary.take_home_rate}%`}
              hint="Of what you earn"
            />
          ) : (
            <Figure label="You keep" value="—" hint="Needs gross and deductions" />
          )}
        </FigureRow>

        {incomplete && (
          <Text size="sm" tone="secondary">
            Income that arrives on no schedule cannot be averaged into a month without inventing a
            cadence you never agreed to, so it is counted as a source and left out of the total.
          </Text>
        )}
      </Card>

      <Card title="How steady it is" ruledHeader>
        <FigureRow>
          <Figure
            label="Promised"
            amountMinor={summary.monthly_fixed_minor}
            currency={currency}
            neutral
            hint="Fixed amount, fixed date"
          />
          <Figure
            label="Varies"
            amountMinor={summary.monthly_variable_minor}
            currency={currency}
            neutral
            hint="Moves month to month"
          />
          {summary.concentration_pct !== null && (
            <Figure
              label="Largest source"
              value={`${summary.concentration_pct}%`}
              hint="Of monthly income"
              // Not coloured as a warning. Concentration is a fact about a
              // household's position, not a mistake it made — a single-income
              // family is the norm, not an error state.
            />
          )}
        </FigureRow>

        {summary.concentration_pct !== null && summary.concentration_pct >= 80 && (
          <Text size="sm" tone="secondary">
            Most of what comes in depends on one arrangement. That is not a problem in itself —
            it is the thing worth knowing before deciding how much cushion to keep.
          </Text>
        )}
      </Card>
    </>
  );
}
