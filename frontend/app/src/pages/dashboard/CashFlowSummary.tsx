import type { CashFlowByCurrency } from "../../api/types";
import { Card, Figure, FigureRow, Meter } from "../../ui";
import { savingsRate } from "./metrics";

/**
 * Income, spending and net for the selected period.
 *
 * Previously three separate `<Card>`s each wrapping a local `StatTile` — three
 * bordered boxes for three numbers that belong to one sentence, and a fourth
 * implementation of the labelled number. One card holding a `<FigureRow>` says
 * the same thing with less furniture, and the figures align by construction.
 */
export function CashFlowSummary({
  cashFlow,
  currency,
}: {
  cashFlow: CashFlowByCurrency | undefined;
  currency: string;
}) {
  const income = cashFlow?.income_minor ?? 0;
  const expense = cashFlow?.expense_minor ?? 0;
  const net = cashFlow?.net_minor ?? 0;
  const rate = savingsRate(income, expense);

  return (
    <Card accent="money">
      <FigureRow>
        {/* `tone` carries the in/out reading; `neutral` keeps Money from
            colouring it a second time and fighting the token. */}
        <Figure label="Income" amountMinor={income} currency={currency} neutral tone="positive" />
        <Figure label="Spending" amountMinor={expense} currency={currency} neutral />
        <Figure label="Net" amountMinor={net} currency={currency} tone={net < 0 ? "critical" : "default"} />
      </FigureRow>

      {rate != null && (
        <div style={{ marginTop: "var(--lf-space-5)" }}>
          <Meter
            value={Math.max(0, rate)}
            over={rate < 0}
            label="Savings rate"
            caption={`${Math.round(rate)}% of income kept`}
          />
        </div>
      )}
    </Card>
  );
}
