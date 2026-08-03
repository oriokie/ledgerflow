import { format } from "date-fns";
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { SpendingTrendPoint } from "../../api/types";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";
import { formatAmountSigned, minorToMajor } from "../../lib/money";
import { CHART_TICK_FONT_PX } from "../dashboard/chartTheme";

const monthLabel = (iso: string) => format(new Date(`${iso}T00:00:00`), "MMM");

/** Income vs expenses as bars with a net line — the headline trend. */
export function CashFlowChart({ trend, currency }: { trend: SpendingTrendPoint[]; currency: string }) {
  const animate = !usePrefersReducedMotion();
  const data = trend.map((p) => ({
    label: monthLabel(p.period_start),
    Income: minorToMajor(p.income_minor),
    Expenses: minorToMajor(p.expense_minor),
    Net: minorToMajor(p.net_minor),
  }));

  return (
    <div className="lf-chart-container">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--lf-border-subtle)" />
          <XAxis dataKey="label" stroke="var(--lf-text-tertiary)" fontSize={CHART_TICK_FONT_PX} tickLine={false} axisLine={false} />
          <YAxis hide />
          <Tooltip
            // Signed: the Net series goes negative in a deficit month, and dropping
            // the sign would render a shortfall as a surplus.
            formatter={(v) => formatAmountSigned(Math.round(Number(v) * 100), currency)}
            contentStyle={{ borderRadius: 8, border: "1px solid var(--lf-border-subtle)", fontSize: "var(--lf-text-xs)" }}
          />
          <Legend iconType="circle" wrapperStyle={{ fontSize: "var(--lf-text-xs)" }} />
          <Bar
            dataKey="Income"
            fill="var(--lf-chart-income)"
            radius={[4, 4, 0, 0]}
            maxBarSize={26}
            isAnimationActive={animate}
          />
          <Bar
            dataKey="Expenses"
            fill="var(--lf-chart-expense)"
            radius={[4, 4, 0, 0]}
            maxBarSize={26}
            isAnimationActive={animate}
          />
          <Line dataKey="Net" stroke="var(--lf-chart-1)" strokeWidth={2} dot={false} isAnimationActive={animate} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
