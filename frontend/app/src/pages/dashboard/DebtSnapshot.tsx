import { Link } from "react-router-dom";
import type { DebtSummary, DebtView } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { Meter, Text } from "../../ui";

export function DebtSnapshot({
  summary,
  debts,
}: {
  summary: DebtSummary | undefined;
  debts: DebtView[] | undefined;
}) {
  const count = summary?.debt_count ?? debts?.length ?? 0;
  if (count === 0) return null;

  const currency = summary?.currency ?? debts?.[0]?.currency ?? "USD";
  const withProgress = (debts ?? [])
    .filter((d) => d.percent_repaid != null && d.balance_minor > 0)
    .slice(0, 3);

  return (
    <section className="lf-cmd-panel lf-cmd-panel--rail" aria-labelledby="lf-debt-title">
      <header className="lf-cmd-panel-head">
        <h2 id="lf-debt-title">Debt progress</h2>
        <Link className="lf-section-link" to="/debt">
          Payoff plan
        </Link>
      </header>

      {summary ? (
        <>
          <p className="lf-inv-figure lf-amount">
            {formatAmount(summary.total_balance_minor, currency)}
          </p>
          <p className="lf-cmd-panel-sub">
            {summary.debt_count} debt{summary.debt_count === 1 ? "" : "s"}
            {summary.priced_count > 0
              ? ` · ~${formatAmount(summary.total_monthly_interest_minor, currency)}/mo interest`
              : " · add terms to see interest cost"}
          </p>
        </>
      ) : (
        <Text tone="secondary" size="sm">
          {count} tracked liabilit{count === 1 ? "y" : "ies"}.
        </Text>
      )}

      {withProgress.length > 0 && (
        <div className="lf-disclosure-panel">
          {withProgress.map((d) => (
            <Meter
              key={d.account_id}
              value={d.percent_repaid ?? 0}
              label={d.name}
              caption={`${Math.round(d.percent_repaid ?? 0)}% repaid`}
            />
          ))}
        </div>
      )}
    </section>
  );
}
