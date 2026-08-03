import { AlertCircle } from "lucide-react";
import type { PortfolioSummary } from "../../api/types";
import { formatAmountSigned, formatDateLong } from "../../lib/money";
import { plural } from "../../lib/plural";
import { Figure, FigureRow, Text } from "../../ui";

/**
 * Headline portfolio figures.
 *
 * The four numbers mean genuinely different things, and blurring them is how
 * people come to believe they have money they haven't made:
 *
 *   market value      what it's worth *at the last price anyone entered*
 *   unrealised gain   paper only, not yours until you sell
 *   realised gain     booked on disposal — real, in the ledger
 *   dividends         income received — real, in the ledger
 *
 * That distinction used to live only in this comment. Every one of the four
 * rendered in the same weight, in the same grid, with nothing to separate a
 * ledger fact from an estimate. `Figure`'s certainty axis is what states it on
 * screen: cost basis, realised gains and dividends are `settled`; market value
 * and the unrealised gain derived from it are `projected`, because the price
 * behind them was typed in by hand on some date that may not be today.
 */
export function PortfolioSummaryCard({ summary }: { summary: PortfolioSummary }) {
  const { currency } = summary;

  // Not "is it more than N days old" — any threshold there would be invented.
  // Either the prices are today's or they aren't, and if they aren't, the date
  // is stated and the reader judges. The product's job is to not hide it.
  const asOf = summary.priced_as_of;
  const stale = summary.stale_count > 0 && asOf !== null;

  return (
    <section className="lf-portfolio-summary" aria-label="Portfolio summary">
      <Figure
        label="Market value"
        size="hero"
        amountMinor={summary.market_value_minor}
        currency={currency}
        neutral
        certainty="projected"
        delta={
          <span className="lf-portfolio-change" data-up={summary.unrealized_gain_minor >= 0 || undefined}>
            {formatAmountSigned(summary.unrealized_gain_minor, currency)} (
            {summary.unrealized_gain_pct >= 0 ? "+" : ""}
            {summary.unrealized_gain_pct}%) unrealised
          </span>
        }
        hint={
          asOf
            ? stale
              ? `At prices last updated ${formatDateLong(asOf)} — not today's market.`
              : "At today's prices."
            : undefined
        }
      />

      <FigureRow className="lf-portfolio-metrics">
        <Figure
          label="Cost basis"
          amountMinor={summary.cost_basis_minor}
          currency={currency}
          neutral
        />
        {/* Booked on disposal and posted to the ledger — settled, unlike the
            paper gain above. Same for dividends: money that arrived. */}
        <Figure
          label="Realised gains"
          value={formatAmountSigned(summary.realized_gain_minor, currency)}
          tone={summary.realized_gain_minor < 0 ? "critical" : "default"}
        />
        <Figure
          label="Dividends"
          amountMinor={summary.dividend_income_minor}
          currency={currency}
          neutral
        />
        {/* Mixes settled and projected components, so it inherits the weaker
            of the two. A total return quoted as fact when most of it is an
            unrealised paper gain is the specific overstatement this page
            exists to avoid. */}
        <Figure
          label="Total return"
          value={formatAmountSigned(summary.total_return_minor, currency)}
          certainty="projected"
          tone={summary.total_return_minor < 0 ? "critical" : "default"}
        />
      </FigureRow>

      {/* An incomplete total presented as complete is a lie of omission. */}
      {summary.unpriced_count > 0 && (
        <p className="lf-portfolio-caveat">
          <AlertCircle size={14} strokeWidth={2} aria-hidden="true" />
          <span>
            {summary.unpriced_count} of {plural(summary.holding_count, "holding")} have no price
            yet, so this total is partial.
          </span>
        </p>
      )}

      {stale && (
        <Text tone="tertiary" size="xs">
          Prices are entered by hand, so a valuation is only as current as the last update.
        </Text>
      )}
    </section>
  );
}
