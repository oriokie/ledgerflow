import type { HoldingValuation } from "../../api/types";
import { formatAmountSigned, formatDate } from "../../lib/money";
import { Money, Text } from "../../ui";

/** Today as `YYYY-MM-DD` in the viewer's own zone. `toISOString()` would give
 * UTC, which is a different day for a good part of the world. */
function todayISO(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Trims trailing zeros from a decimal quantity — "10" reads better than
 * "10.00000000", and crypto still shows the precision it needs. */
function formatQuantity(value: string): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  return n.toLocaleString(undefined, { maximumFractionDigits: 8 });
}

/**
 * The positions table.
 *
 * Cost basis and market value sit side by side deliberately: the gap between
 * them *is* the unrealised gain, and showing both lets a user verify the
 * derived column rather than trust it.
 *
 * An unpriced holding shows an explicit dash rather than a zero. A zero in a
 * market-value column reads as a total loss.
 *
 * A priced-but-not-today holding is dated in place. The summary card says the
 * portfolio total is stale; without this the reader is told that and given no
 * way to find which position caused it.
 */
export function HoldingsTable({ holdings }: { holdings: HoldingValuation[] }) {
  const today = todayISO();
  return (
    <div className="lf-table-wrap">
      <table className="lf-table lf-holdings-table">
        <caption className="lf-visually-hidden">Investment holdings</caption>
        <thead>
          <tr>
            <th scope="col">Holding</th>
            <th scope="col" className="lf-col-amount">Units</th>
            <th scope="col" className="lf-col-amount lf-col-hide-mobile">Cost</th>
            <th scope="col" className="lf-col-amount">Value</th>
            <th scope="col" className="lf-col-amount">Gain</th>
          </tr>
        </thead>
        <tbody>
          {holdings.map((h) => (
            <tr key={h.holding_id}>
              <td>
                <span className="lf-cell-primary">{h.symbol}</span>
                <br />
                <span className="lf-cell-meta">
                  {h.security_name} · {h.account_name}
                </span>
              </td>
              <td className="lf-col-amount">{formatQuantity(h.quantity)}</td>
              <td className="lf-col-amount lf-col-hide-mobile">
                <Money amountMinor={h.cost_basis_minor} currency={h.currency} neutral />
              </td>
              <td className="lf-col-amount">
                {h.market_value_minor === null ? (
                  <Text as="span" tone="tertiary" size="sm">
                    Not priced
                  </Text>
                ) : (
                  <>
                    <Money amountMinor={h.market_value_minor} currency={h.currency} neutral />
                    {h.priced_as_of !== null && h.priced_as_of < today && (
                      <span className="lf-holding-stale">
                        at {formatDate(h.priced_as_of)} price
                      </span>
                    )}
                  </>
                )}
              </td>
              <td className="lf-col-amount">
                {h.unrealized_gain_minor === null ? (
                  <Text as="span" tone="tertiary" size="sm">
                    —
                  </Text>
                ) : (
                  <span
                    className="lf-holding-gain"
                    data-up={h.unrealized_gain_minor >= 0 || undefined}
                  >
                    {formatAmountSigned(h.unrealized_gain_minor, h.currency)}
                    {h.unrealized_gain_pct !== null && (
                      <span className="lf-holding-gain-pct">
                        {h.unrealized_gain_pct >= 0 ? "+" : ""}
                        {h.unrealized_gain_pct}%
                      </span>
                    )}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
