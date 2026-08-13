import { Link } from "react-router-dom";
import type { PortfolioSummary } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { Text } from "../../ui";

export function InvestmentsSnapshot({ portfolio }: { portfolio: PortfolioSummary | undefined }) {
  if (!portfolio || portfolio.holding_count === 0) return null;

  const gain = portfolio.unrealized_gain_minor;
  const gainTone = gain > 0 ? "good" : gain < 0 ? "bad" : undefined;

  return (
    <section className="lf-cmd-panel lf-cmd-panel--rail" aria-labelledby="lf-inv-title">
      <header className="lf-cmd-panel-head">
        <h2 id="lf-inv-title">Investments</h2>
        <Link className="lf-section-link" to="/investments">
          Portfolio
        </Link>
      </header>
      <p className="lf-inv-figure lf-amount">{formatAmount(portfolio.market_value_minor, portfolio.currency)}</p>
      <p className="lf-inv-meta">
        <span className="lf-delta" data-tone={gainTone}>
          {gain >= 0 ? "+" : "−"}
          {formatAmount(Math.abs(gain), portfolio.currency)}
          {portfolio.unrealized_gain_pct != null
            ? ` (${portfolio.unrealized_gain_pct > 0 ? "+" : ""}${portfolio.unrealized_gain_pct.toFixed(1)}%)`
            : ""}
        </span>
        <span className="lf-inv-holdings">
          {portfolio.holding_count} holding{portfolio.holding_count === 1 ? "" : "s"}
        </span>
      </p>
      {portfolio.unpriced_count > 0 && (
        <Text tone="tertiary" size="sm">
          {portfolio.unpriced_count} position{portfolio.unpriced_count === 1 ? "" : "s"} unpriced —
          total may be partial.
        </Text>
      )}
    </section>
  );
}
