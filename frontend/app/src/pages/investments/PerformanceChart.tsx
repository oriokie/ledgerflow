import { Area, AreaChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { PortfolioHistoryPoint } from "../../api/types";
import { formatAmountSigned } from "../../lib/money";
import { Text } from "../../ui";
import { CHART_TICK_FONT_PX } from "../dashboard/chartTheme";

function monthLabel(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", year: "2-digit" });
}

/**
 * Market value against cost basis over time.
 *
 * Plotting both is the point: the *gap* between the lines is the unrealised
 * gain, and seeing cost rise as you invest more explains why market value rose
 * without implying the whole increase was growth. A value-only chart makes
 * contributions look like performance.
 */
export function PerformanceChart({
  points,
  currency,
}: {
  points: PortfolioHistoryPoint[];
  currency: string;
}) {
  // One point is not a trend; a two-point line implies a direction that a
  // single month of data can't support.
  if (points.length < 2) {
    return (
      <Text tone="tertiary" size="sm">
        Record prices over a few months and your performance history will appear here.
      </Text>
    );
  }

  const data = points.map((p) => ({
    label: monthLabel(p.as_of),
    Value: p.market_value_minor / 100,
    Cost: p.cost_basis_minor / 100,
  }));

  return (
    <div className="lf-performance-chart">
      <ResponsiveContainer width="100%" height={220}>
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="lf-portfolio-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--lf-chart-1)" stopOpacity={0.26} />
              <stop offset="100%" stopColor="var(--lf-chart-1)" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="label"
            stroke="var(--lf-text-tertiary)"
            fontSize={CHART_TICK_FONT_PX}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
          />
          <YAxis hide />
          <Tooltip
            formatter={(value) => formatAmountSigned(Math.round(Number(value ?? 0) * 100), currency)}
            contentStyle={{
              background: "var(--lf-bg-surface)",
              border: "1px solid var(--lf-border-card)",
              borderRadius: "var(--lf-radius-md)",
              fontSize: "var(--lf-text-xs)",
            }}
          />
          <Area
            type="monotone"
            dataKey="Value"
            stroke="var(--lf-chart-1)"
            strokeWidth={2}
            fill="url(#lf-portfolio-fill)"
          />
          {/* Dashed, because cost is the reference line rather than the story. */}
          <Line
            type="monotone"
            dataKey="Cost"
            stroke="var(--lf-text-tertiary)"
            strokeWidth={1.5}
            strokeDasharray="4 4"
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
      <Text tone="tertiary" size="xs">
        Solid line is market value; dashed is what you paid. The gap between them is unrealised gain.
      </Text>
    </div>
  );
}
