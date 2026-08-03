import { Check } from "lucide-react";
import type { PayoffStrategy, StrategyComparison as Comparison } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { Text } from "../../ui";

const LABELS: Record<PayoffStrategy, string> = {
  avalanche: "Highest rate first",
  snowball: "Smallest balance first",
  custom: "Your own order",
};

const BLURB: Record<PayoffStrategy, string> = {
  avalanche: "Costs the least in interest.",
  snowball: "Clears individual debts sooner.",
  custom: "Whatever order you've set.",
};

function months(n: number | null): string {
  if (n === null) return "—";
  if (n < 12) return `${n} mo`;
  const years = Math.floor(n / 12);
  const rest = n % 12;
  return rest ? `${years}y ${rest}m` : `${years}y`;
}

/**
 * The three strategies side by side.
 *
 * Deliberately a comparison rather than a single recommendation. Avalanche
 * always wins on total interest and snowball often clears a first debt sooner,
 * and which matters more is a judgement about the person, not the arithmetic —
 * a plan abandoned in month four saves nothing at all.
 *
 * The selected strategy is marked rather than the "best" one, because there
 * isn't a best one.
 */
export function StrategyComparison({
  comparisons,
  selected,
  currency,
  onSelect,
}: {
  comparisons: Comparison[];
  selected: PayoffStrategy;
  currency: string;
  onSelect: (strategy: PayoffStrategy) => void;
}) {
  if (comparisons.length === 0) return null;

  return (
    <div className="lf-strategy-grid" role="radiogroup" aria-label="Payoff strategy">
      {comparisons.map((c) => {
        const active = c.strategy === selected;
        return (
          <button
            key={c.strategy}
            type="button"
            role="radio"
            aria-checked={active}
            className="lf-strategy-card"
            data-active={active || undefined}
            onClick={() => onSelect(c.strategy)}
          >
            <span className="lf-strategy-head">
              <span className="lf-strategy-name">{LABELS[c.strategy]}</span>
              {active && <Check size={15} strokeWidth={2.4} aria-hidden="true" />}
            </span>
            <Text as="span" tone="tertiary" size="xs">
              {BLURB[c.strategy]}
            </Text>

            <dl className="lf-strategy-figures">
              <div>
                <dt>Debt free in</dt>
                <dd>{months(c.months_to_debt_free)}</dd>
              </div>
              <div>
                <dt>Interest</dt>
                <dd>{formatAmount(c.total_interest_minor, currency)}</dd>
              </div>
            </dl>

            {/* The trade-off each method is actually making, stated. */}
            {c.first_cleared_name && (
              <Text as="span" tone="tertiary" size="xs">
                First clears {c.first_cleared_name} in {months(c.first_cleared_months)}
              </Text>
            )}
          </button>
        );
      })}
    </div>
  );
}
