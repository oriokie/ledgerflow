import { PartyPopper } from "lucide-react";
import type { PayoffCalendarMonth } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { Text } from "../../ui";

function monthLabel(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

/**
 * The month-by-month payment schedule.
 *
 * Grouped by month rather than by debt, because that's how the money actually
 * leaves: someone wants to know what March costs, not what the car loan costs
 * across three years.
 *
 * Each row splits payment into interest and principal. That split is the whole
 * story of a debt — seeing that £180 of a £200 payment went to interest
 * explains a balance that has barely moved far better than any summary figure.
 */
export function PayoffCalendar({
  months,
  currency,
}: {
  months: PayoffCalendarMonth[];
  currency: string;
}) {
  if (months.length === 0) {
    return (
      <Text tone="tertiary" size="sm">
        Add an interest rate and minimum payment to a debt to see its schedule.
      </Text>
    );
  }

  return (
    <ol className="lf-payoff-calendar">
      {months.map((month) => (
        <li key={month.as_of} className="lf-payoff-month">
          <div className="lf-payoff-month-head">
            <span className="lf-payoff-month-name">{monthLabel(month.as_of)}</span>
            <span className="lf-payoff-month-total">
              {formatAmount(month.total_paid_minor, currency)}
            </span>
          </div>

          <ul className="lf-payoff-payments">
            {month.payments.map((p) => (
              <li key={p.debt_id} data-clears={p.clears_here || undefined}>
                <span className="lf-payoff-debt">
                  {p.name}
                  {p.clears_here && (
                    <span className="lf-payoff-cleared">
                      <PartyPopper size={12} strokeWidth={2} aria-hidden="true" />
                      paid off
                    </span>
                  )}
                </span>
                <span className="lf-payoff-split">
                  {/* Interest first, because that's the part people don't see. */}
                  <span className="lf-payoff-interest">
                    {formatAmount(p.interest_minor, currency)} interest
                  </span>
                  <span className="lf-payoff-principal">
                    {formatAmount(p.principal_minor, currency)} off the balance
                  </span>
                </span>
                <span className="lf-payoff-amount">{formatAmount(p.payment_minor, currency)}</span>
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ol>
  );
}
