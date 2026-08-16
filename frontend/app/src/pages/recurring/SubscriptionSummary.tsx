import { Sparkles } from "lucide-react";
import type { Category, RecurringTransaction } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { Card, Money } from "../../ui";
import { isPeriodical, recognizedMinor, recurringLabel, recurringTotals, sortByMonthlyCost } from "./recurringMath";

/** Monthly and annual recurring spend at a glance. */
export function SubscriptionSummary({ recurring }: { recurring: RecurringTransaction[] }) {
  const totals = recurringTotals(recurring);
  if (totals.expenseCount === 0) return null;

  return (
    <Card>
      <div className="lf-stat-band">
        <div className="lf-stat-band-item">
          <span className="lf-stat-label">Recurring monthly</span>
          <Money amountMinor={totals.monthlyExpense} currency={totals.currency} neutral hero />
        </div>
        <div className="lf-stat-band-divider" />
        <div className="lf-stat-band-item">
          <span className="lf-stat-label">Per year</span>
          <Money amountMinor={totals.annualExpense} currency={totals.currency} neutral />
        </div>
        <div className="lf-stat-band-divider" />
        <div className="lf-stat-band-item">
          <span className="lf-stat-label">Subscriptions</span>
          <span style={{ fontSize: "var(--lf-text-lg)", fontWeight: "var(--lf-weight-semibold)", color: "var(--lf-text-primary)" }}>
            {totals.expenseCount}
          </span>
        </div>
        {totals.monthlyIncome > 0 && (
          <>
            <div className="lf-stat-band-divider" />
            <div className="lf-stat-band-item">
              <span className="lf-stat-label">Recurring income</span>
              <Money amountMinor={totals.monthlyIncome} currency={totals.currency} neutral />
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

/** A gentle "here's where the money goes" nudge — the annual cost of recurring
 * spend and the priciest few, so the biggest savings are the easiest to see. */
export function SubscriptionInsight({
  recurring,
  categories,
}: {
  recurring: RecurringTransaction[];
  categories: Category[] | undefined;
}) {
  const totals = recurringTotals(recurring);
  if (totals.expenseCount === 0) return null;

  const top = sortByMonthlyCost(recurring.filter((r) => r.txn_type === "expense" && r.currency === totals.currency)).slice(0, 3);

  return (
    <div className="lf-insight lf-insight--soon" role="status">
      <p className="lf-insight-title" style={{ display: "flex", alignItems: "center", gap: "var(--lf-space-2)" }}>
        <Sparkles size={15} strokeWidth={1.8} aria-hidden="true" />
        {totals.expenseCount} subscription{totals.expenseCount === 1 ? "" : "s"} costing about {formatAmount(totals.annualExpense, totals.currency)}/year
      </p>
      <p className="lf-insight-body">
        Biggest: {top.map((r) => `${recurringLabel(r, categories)} (${formatAmount(recognizedMinor(r), r.currency)}${isPeriodical(r) ? "" : "/mo"})`).join(" · ")}.
        Pausing or cancelling what you don't use is the fastest way to cut spending.
      </p>
    </div>
  );
}
