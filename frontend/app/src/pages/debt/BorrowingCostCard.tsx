import { Info } from "lucide-react";
import type { BorrowingCost } from "../../api/types";
import { plural } from "../../lib/plural";
import { Button, Figure, FigureRow, Text } from "../../ui";

/**
 * What debt costs over a year, split into interest and fees.
 *
 * Separated deliberately: interest falls as the balance does, a fee doesn't. A
 * combined figure would hide a card whose real cost is mostly an annual fee
 * that paying it down will never reduce.
 *
 * With no terms recorded there is no cost to report — every input to this card
 * is contract metadata, none of it derivable from the ledger. It used to render
 * a confident "Cost of borrowing this year: 0.00", which is the most misleading
 * thing on the page: it tells someone carrying a balance that it is free.
 */
export function BorrowingCostCard({
  cost,
  onAddTerms,
}: {
  cost: BorrowingCost;
  /** Opens the terms editor on a debt that has none. Omitted when all do. */
  onAddTerms?: () => void;
}) {
  const { currency, priced_count: priced, debt_count: debtCount } = cost;
  const partial = priced > 0 && priced < debtCount;

  if (priced === 0) {
    return (
      <section className="lf-borrowing-cost" aria-label="Annual borrowing cost">
        <Text as="span" tone="tertiary" size="xs">
          Cost of borrowing this year
        </Text>
        <Text tone="secondary" size="sm">
          Not yet known. Interest and fees come from each debt's terms, not from your transactions,
          so they have to be recorded before this can be worked out.
        </Text>
        {onAddTerms && (
          <div>
            <Button variant="secondary" size="sm" onClick={onAddTerms}>
              Add terms
            </Button>
          </div>
        )}
      </section>
    );
  }

  const feeHeavy = cost.fee_share >= 25;

  return (
    <section className="lf-borrowing-cost" aria-label="Annual borrowing cost">
      <Figure
        label="Cost of borrowing this year"
        size="primary"
        amountMinor={cost.annual_total_minor}
        currency={currency}
        neutral
      />

      <FigureRow className="lf-borrowing-split">
        <Figure
          label="Interest"
          amountMinor={cost.annual_interest_minor}
          currency={currency}
          neutral
        />
        <Figure label="Fees" amountMinor={cost.annual_fees_minor} currency={currency} neutral />
      </FigureRow>

      {/* A total over some of the debts is a floor, not the figure. */}
      {partial && (
        <p className="lf-debt-partial">
          <Info size={13} strokeWidth={2} aria-hidden="true" />
          At least this much — terms recorded for {priced} of {plural(debtCount, "debt")}.
          {onAddTerms && (
            <Button variant="ghost" size="sm" onClick={onAddTerms}>
              Add terms
            </Button>
          )}
        </p>
      )}

      {/* Worth naming: paying the balance down won't touch this part. */}
      {feeHeavy && (
        <p className="lf-borrowing-note">
          {cost.fee_share}% of what you pay is fees rather than interest — paying the balance down
          won't reduce that portion.
        </p>
      )}
    </section>
  );
}
