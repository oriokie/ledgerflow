import { Link } from "react-router-dom";
import { useCashflowCalendar } from "../../hooks/useFinance";
import { formatAmount, formatAmountSigned } from "../../lib/money";
import { Card, Text } from "../../ui";

/**
 * The one number that answers "can I buy this?".
 *
 * It is the cash-flow projection's trough, floored at zero — not today's
 * balance, which is exactly the number that gets people overdrawn, because
 * rent has not happened yet. When spending history exists the figure already
 * assumes normal everyday spending continues, so it reads "beyond your usual
 * habits"; with no history it can only account for scheduled bills, and the
 * caption says so instead of pretending.
 *
 * Renders nothing without a calendar (no liquid accounts): a safe-to-spend of
 * zero derived from an absence would read as an emergency rather than an
 * unknown.
 */
export function SafeToSpend() {
  const { data: calendar } = useCashflowCalendar({ days: 35 });
  if (!calendar) return null;

  const amount = calendar.safe_to_spend_minor;
  const horizon = new Date(calendar.end).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
  });
  const caption =
    calendar.safe_to_spend_basis === "everyday"
      ? `beyond your usual spending, with every bill through ${horizon} still covered`
      : `with every scheduled bill through ${horizon} still covered`;

  return (
    <Card
      title="Safe to spend"
      action={
        <Link className="lf-section-link" to="/cashflow">
          How it's projected
        </Link>
      }
    >
      <p className="lf-safe-amount" data-zero={amount === 0 || undefined}>
        {formatAmount(amount, calendar.currency)}
      </p>
      {amount > 0 ? (
        <Text tone="secondary" size="sm">
          {caption}.
        </Text>
      ) : (
        <Text tone="secondary" size="sm">
          Nothing extra is safe right now — your balance is projected to dip to{" "}
          {formatAmountSigned(calendar.lowest_balance_minor, calendar.currency)}
          {calendar.lowest_balance_on
            ? ` around ${new Date(calendar.lowest_balance_on).toLocaleDateString(undefined, { day: "numeric", month: "short" })}`
            : ""}
          . The calendar shows which bills drive that.
        </Text>
      )}
    </Card>
  );
}
