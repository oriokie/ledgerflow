import { useCashflowStatement } from "../../hooks/useFinance";
import { Card, EmptyState, Money, SkeletonCard } from "../../ui";
import { Droplets } from "lucide-react";
import { formatAmount } from "../../lib/money";

const monthLabel = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: "short", year: "2-digit" });

/**
 * The liquidity view: for each month, money in, money out, net, and the ending
 * liquid balance (checking + savings + cash). Answers "can I cover what's
 * coming?" at a glance, and is the same series the cash-runway forecast reads.
 */
export function CashflowStatement() {
  const { data, isLoading } = useCashflowStatement(6);

  if (isLoading) return <SkeletonCard />;
  if (!data || !data.currency || data.rows.length === 0) {
    return (
      <Card eyebrow="Cash flow statement">
        <EmptyState
          icon={Droplets}
          title="No cash activity yet"
          body="Add accounts and transactions and your monthly liquidity statement builds itself. Salary recorded on Income appears on Cash flow on payday, and in this month's money-in once the month is under way."
        />
      </Card>
    );
  }

  const { currency, rows, liquid_balance_minor } = data;
  const activeMonths = rows.filter((r) => r.inflow_minor || r.outflow_minor);
  const avgNet =
    activeMonths.length > 0
      ? Math.round(activeMonths.reduce((sum, r) => sum + r.net_minor, 0) / activeMonths.length)
      : 0;

  return (
    <Card eyebrow="Cash flow statement">
      <p className="lf-text-sm lf-text-secondary" style={{ marginBottom: "var(--lf-space-4)" }}>
        Liquid today: <strong>{formatAmount(liquid_balance_minor, currency)}</strong>
        {activeMonths.length > 1 && (
          <>
            {" "}
            · Avg monthly net: <Money amountMinor={avgNet} currency={currency} />
          </>
        )}
      </p>
      <div className="lf-table-wrap">
        <table className="lf-table lf-cashflow-table">
          <thead>
            <tr>
              <th scope="col">Month</th>
              <th scope="col">Money in</th>
              <th scope="col">Money out</th>
              <th scope="col">Net</th>
              <th scope="col">Ending balance</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.period_start}>
                <th scope="row">{monthLabel(r.period_start)}</th>
                <td>{formatAmount(r.inflow_minor, currency)}</td>
                <td>{formatAmount(r.outflow_minor, currency)}</td>
                <td>
                  <Money amountMinor={r.net_minor} currency={currency} />
                </td>
                <td>{r.ending_balance_minor < 0 ? "-" : ""}{formatAmount(r.ending_balance_minor, currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
