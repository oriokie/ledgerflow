import { Link } from "react-router-dom";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CashFlowByCurrency, SpendingTrendPoint } from "../../api/types";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";
import { minorToMajor } from "../../lib/money";
import { Figure, FigureRow, Meter, Text } from "../../ui";
import { ChartTooltip } from "./chart";
import { AXIS_TICK, axisLineProps, compactNumber, gridProps } from "./chartTheme";
import { savingsRate } from "./metrics";

export function CashFlowPanel({
  cashFlow,
  trend,
  currency,
  periodLabel,
}: {
  cashFlow: CashFlowByCurrency | undefined;
  trend: SpendingTrendPoint[] | undefined;
  currency: string;
  periodLabel: string;
}) {
  const animate = !usePrefersReducedMotion();
  const income = cashFlow?.income_minor ?? 0;
  const expense = cashFlow?.expense_minor ?? 0;
  const net = cashFlow?.net_minor ?? 0;
  const rate = savingsRate(income, expense);

  const chartData = (trend ?? []).map((p) => ({
    label: p.period_start,
    income: minorToMajor(p.income_minor),
    expense: minorToMajor(p.expense_minor),
    net: minorToMajor(p.net_minor),
  }));

  return (
    <section className="lf-cmd-panel" aria-labelledby="lf-cf-title">
      <header className="lf-cmd-panel-head">
        <div>
          <h2 id="lf-cf-title">Cash flow</h2>
          <p className="lf-cmd-panel-sub">{periodLabel}</p>
        </div>
        <Link className="lf-section-link" to="/plan?tab=cashflow">
          Full calendar
        </Link>
      </header>

      <FigureRow>
        <Figure label="Income" amountMinor={income} currency={currency} neutral tone="positive" />
        <Figure label="Spending" amountMinor={expense} currency={currency} neutral />
        <Figure
          label="Net"
          amountMinor={net}
          currency={currency}
          tone={net < 0 ? "critical" : "default"}
        />
      </FigureRow>

      {rate != null && (
        <div className="lf-cmd-meter">
          <Meter
            value={Math.max(0, rate)}
            over={rate < 0}
            label="Savings rate"
            caption={`${Math.round(rate)}% of income kept`}
          />
        </div>
      )}

      <div className="lf-cmd-chart">
        {chartData.length >= 2 ? (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid {...gridProps} />
              <XAxis
                dataKey="label"
                tick={AXIS_TICK}
                tickFormatter={(l) =>
                  new Date(l).toLocaleDateString(undefined, { month: "short" })
                }
                {...axisLineProps}
              />
              <YAxis
                tick={AXIS_TICK}
                tickFormatter={compactNumber}
                width={40}
                {...axisLineProps}
              />
              <Tooltip
                content={
                  <ChartTooltip
                    currency={currency}
                    labelFormatter={(l) =>
                      new Date(l).toLocaleDateString(undefined, { month: "short", year: "numeric" })
                    }
                  />
                }
              />
              <Bar
                dataKey="income"
                name="Income"
                fill="var(--lf-money-in)"
                fillOpacity={0.55}
                radius={[3, 3, 0, 0]}
                isAnimationActive={animate}
              />
              <Bar
                dataKey="expense"
                name="Spending"
                fill="var(--lf-ink-500)"
                fillOpacity={0.35}
                radius={[3, 3, 0, 0]}
                isAnimationActive={animate}
              />
              <Line
                type="monotone"
                dataKey="net"
                name="Net"
                stroke="var(--lf-action-primary)"
                strokeWidth={2}
                dot={false}
                isAnimationActive={animate}
              />
            </ComposedChart>
          </ResponsiveContainer>
        ) : (
          <div className="lf-cmd-chart-empty">
            <Text tone="tertiary" size="sm">
              A few months of activity unlock the cash-flow trend.
            </Text>
          </div>
        )}
      </div>
    </section>
  );
}
