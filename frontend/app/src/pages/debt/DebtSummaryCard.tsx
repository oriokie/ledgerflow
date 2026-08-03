import { AlertTriangle, Info, TrendingDown } from "lucide-react";
import type { DebtSummary } from "../../api/types";
import { plural } from "../../lib/plural";
import { Button, Figure, FigureRow, Money, Text } from "../../ui";

const ALERT_ICONS = { critical: AlertTriangle, warning: TrendingDown, info: Info } as const;

/**
 * Headline debt figures and anything that needs saying.
 *
 * The annual interest figure leads because it's the one that persuades.
 * "£47 a month" is easy to absorb; "£564 a year, before any of it reduces what
 * you owe" is the same fact stated so it registers.
 *
 * Every derived figure here is gated on whether its input was ever recorded.
 * A debt with no terms carries an APR of 0 and a minimum of 0, so the card used
 * to render "Average rate 0% · Monthly minimums 0.00" over a real balance — a
 * measurement nobody made, in the same type as the ledger totals beside it.
 * Missing is not zero, and the two must not look alike.
 */
export function DebtSummaryCard({
  summary,
  onAddTerms,
}: {
  summary: DebtSummary;
  /** Opens the terms editor on a debt that has none. Omitted when all do. */
  onAddTerms?: () => void;
}) {
  const { currency, debt_count: debtCount, priced_count: priced } = summary;

  const ratesKnown = priced > 0;
  const minimumsKnown = summary.unplannable_count < debtCount;
  // Some terms recorded, but not all: the figures are real, and they describe
  // less than the whole balance. Saying which is cheaper than either
  // suppressing them or letting them pass as complete.
  const partial = ratesKnown && priced < debtCount;

  // With nothing priced, the card already explains the gap in full — leaving
  // the backend's "N debts missing terms" alert in place said the same thing
  // twice, 60px apart. It still earns its place when only *some* terms are
  // missing, because there the card's note is a one-line aside and the alert
  // is what names the consequence for the payoff plan.
  const alerts = ratesKnown
    ? summary.alerts
    : summary.alerts.filter((a) => !/missing terms/i.test(a.title));

  return (
    <section className="lf-debt-summary" aria-label="Debt summary">
      <Figure
        label="Total owed"
        size="hero"
        amountMinor={summary.total_balance_minor}
        currency={currency}
        neutral
        hint={
          ratesKnown ? (
            <>
              Interest is costing about{" "}
              <strong>
                <Money amountMinor={summary.annual_interest_minor} currency={currency} neutral /> a
                year
              </strong>{" "}
              at these balances{partial ? ", on the debts with terms recorded" : ""}.
            </>
          ) : undefined
        }
      />

      {/* Nothing derived can be shown, so the card says why and offers the fix
          rather than filling the grid with zeroes. */}
      {!ratesKnown && !minimumsKnown ? (
        <div className="lf-debt-unpriced">
          <Text tone="secondary" size="sm">
            No interest rates or minimum payments are recorded, so there's nothing yet to work out
            what this debt costs or how long it will take to clear.
          </Text>
          {onAddTerms && (
            <Button variant="secondary" size="sm" onClick={onAddTerms}>
              Add terms
            </Button>
          )}
        </div>
      ) : (
        <>
          <FigureRow className="lf-debt-metrics">
            {minimumsKnown && (
              <Figure
                label="Monthly minimums"
                amountMinor={summary.total_minimum_minor}
                currency={currency}
                neutral
              />
            )}
            {/* Weighted by balance — a plain average would let a tiny expensive
                card out-shout a large cheap loan. Averaged over the priced
                debts only, so it describes what it was computed from. */}
            {ratesKnown && <Figure label="Average rate" value={`${summary.weighted_apr}%`} />}
            {summary.highest_apr !== null && (
              <Figure
                label="Most expensive"
                size="inline"
                value={`${summary.highest_apr_name} · ${summary.highest_apr}%`}
              />
            )}
          </FigureRow>

          {(partial || !minimumsKnown) && (
            <p className="lf-debt-partial">
              <Info size={13} strokeWidth={2} aria-hidden="true" />
              {partial
                ? `Terms recorded for ${priced} of ${plural(debtCount, "debt")} — these figures cover those only.`
                : "No minimum payments recorded, so there's no monthly commitment to total up."}
              {onAddTerms && (
                <Button variant="ghost" size="sm" onClick={onAddTerms}>
                  Add terms
                </Button>
              )}
            </p>
          )}
        </>
      )}

      {alerts.length > 0 && (
        <ul className="lf-debt-alerts">
          {alerts.map((alert, i) => {
            const Icon = ALERT_ICONS[alert.severity];
            return (
              <li key={i} data-severity={alert.severity}>
                <Icon size={15} strokeWidth={2} aria-hidden="true" />
                <div>
                  <p className="lf-debt-alert-title">{alert.title}</p>
                  <p className="lf-debt-alert-body">{alert.body}</p>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {summary.recommendation && (
        <div className="lf-debt-recommendation">
          <p className="lf-debt-rec-title">{summary.recommendation.title}</p>
          <p className="lf-debt-rec-why">{summary.recommendation.rationale}</p>
        </div>
      )}
    </section>
  );
}
