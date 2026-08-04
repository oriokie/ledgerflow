import { format } from "date-fns";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Projection, ProjectionPoint } from "../../api/projections";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";
import { formatAmount, formatAmountSigned, minorToMajor } from "../../lib/money";
import { AXIS_TICK, axisLineProps, compactNumber, gridProps } from "../dashboard/chartTheme";
import { thin } from "./thin";

const axisLabel = (iso: string) => format(new Date(`${iso}T00:00:00`), "MMM ''yy");
const tooltipLabel = (iso: string) => format(new Date(`${iso}T00:00:00`), "MMMM yyyy");

interface ChartProps {
  projection: Projection;
  /** When present, drawn as a dashed comparison line: the same position with
   * the scenario's events removed. */
  baseline?: Projection;
  currency: string;
}

const tooltipStyle = {
  borderRadius: 8,
  border: "1px solid var(--lf-border-subtle)",
  fontSize: "var(--lf-text-xs)",
  background: "var(--lf-bg-surface)",
};

/** Net worth over the window, with the baseline behind it when comparing. */
export function NetWorthChart({ projection, baseline, currency }: ChartProps) {
  const animate = !usePrefersReducedMotion();
  const baselineByMonth = new Map(baseline?.points.map((p) => [p.month, p.net_worth_minor]));
  const data = thin(projection.points).map((p) => ({
    label: axisLabel(p.on),
    on: p.on,
    Scenario: minorToMajor(p.net_worth_minor),
    Baseline: baseline ? minorToMajor(baselineByMonth.get(p.month) ?? 0) : undefined,
  }));

  return (
    <div className="lf-chart-container" data-testid="net-worth-chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="label" tick={AXIS_TICK} {...axisLineProps} minTickGap={40} />
          <YAxis tick={AXIS_TICK} {...axisLineProps} tickFormatter={compactNumber} width={52} />
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={(_, payload) =>
              payload?.[0] ? tooltipLabel(String(payload[0].payload.on)) : ""
            }
            formatter={(v) => formatAmountSigned(Math.round(Number(v) * 100), currency)}
          />
          {baseline ? <Legend iconType="circle" wrapperStyle={{ fontSize: "var(--lf-text-xs)" }} /> : null}
          <ReferenceLine y={0} stroke="var(--lf-border-strong)" />
          {baseline ? (
            <Line
              dataKey="Baseline"
              stroke="var(--lf-text-tertiary)"
              strokeWidth={1.5}
              strokeDasharray="4 4"
              dot={false}
              isAnimationActive={animate}
            />
          ) : null}
          <Line
            dataKey="Scenario"
            name={baseline ? "Scenario" : "Net worth"}
            stroke="var(--lf-chart-1)"
            strokeWidth={2}
            dot={false}
            isAnimationActive={animate}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Liquid balance, with the trough marked — the number that costs money. */
export function CashFlowProjectionChart({ projection, currency }: ChartProps) {
  const animate = !usePrefersReducedMotion();
  const data = thin(projection.points).map((p) => ({
    label: axisLabel(p.on),
    on: p.on,
    Balance: minorToMajor(p.liquid_minor),
  }));
  const trough = projection.points[projection.summary.lowest_liquid_month - 1];

  return (
    <div className="lf-chart-container" data-testid="cashflow-chart">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="lf-projection-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--lf-chart-2)" stopOpacity={0.35} />
              <stop offset="100%" stopColor="var(--lf-chart-2)" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="label" tick={AXIS_TICK} {...axisLineProps} minTickGap={40} />
          <YAxis tick={AXIS_TICK} {...axisLineProps} tickFormatter={compactNumber} width={52} />
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={(_, payload) =>
              payload?.[0] ? tooltipLabel(String(payload[0].payload.on)) : ""
            }
            formatter={(v) => formatAmountSigned(Math.round(Number(v) * 100), currency)}
          />
          <ReferenceLine y={0} stroke="var(--lf-status-danger)" strokeDasharray="3 3" />
          {trough ? (
            <ReferenceLine
              x={axisLabel(trough.on)}
              stroke="var(--lf-text-tertiary)"
              strokeDasharray="2 2"
              label={{
                value: "lowest",
                fontSize: AXIS_TICK.fontSize,
                fill: "var(--lf-text-tertiary)",
                position: "top",
              }}
            />
          ) : null}
          <Area
            dataKey="Balance"
            stroke="var(--lf-chart-2)"
            strokeWidth={2}
            fill="url(#lf-projection-fill)"
            isAnimationActive={animate}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/** What is owed, falling to zero — the debt reduction timeline. */
export function DebtTimelineChart({ projection, currency }: ChartProps) {
  const animate = !usePrefersReducedMotion();
  const data = thin(projection.points).map((p) => ({
    label: axisLabel(p.on),
    on: p.on,
    Owed: minorToMajor(p.debt_balance_minor),
  }));

  return (
    <div className="lf-chart-container" data-testid="debt-chart">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="label" tick={AXIS_TICK} {...axisLineProps} minTickGap={40} />
          <YAxis tick={AXIS_TICK} {...axisLineProps} tickFormatter={compactNumber} width={52} />
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={(_, payload) =>
              payload?.[0] ? tooltipLabel(String(payload[0].payload.on)) : ""
            }
            formatter={(v) => formatAmount(Math.round(Number(v) * 100), currency)}
          />
          <Area
            dataKey="Owed"
            stroke="var(--lf-chart-expense)"
            strokeWidth={2}
            fill="var(--lf-chart-expense)"
            fillOpacity={0.12}
            isAnimationActive={animate}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Where the money sits: cash, investments, property — stacked. */
export function AssetMixChart({ projection, currency }: ChartProps) {
  const animate = !usePrefersReducedMotion();
  const data = thin(projection.points).map((p: ProjectionPoint) => ({
    label: axisLabel(p.on),
    on: p.on,
    Cash: minorToMajor(Math.max(0, p.liquid_minor)),
    Investments: minorToMajor(p.investment_minor),
    Property: minorToMajor(p.other_assets_minor),
  }));

  return (
    <div className="lf-chart-container" data-testid="asset-mix-chart">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="label" tick={AXIS_TICK} {...axisLineProps} minTickGap={40} />
          <YAxis tick={AXIS_TICK} {...axisLineProps} tickFormatter={compactNumber} width={52} />
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={(_, payload) =>
              payload?.[0] ? tooltipLabel(String(payload[0].payload.on)) : ""
            }
            formatter={(v) => formatAmount(Math.round(Number(v) * 100), currency)}
          />
          <Legend iconType="circle" wrapperStyle={{ fontSize: "var(--lf-text-xs)" }} />
          <Area
            dataKey="Cash"
            stackId="assets"
            stroke="var(--lf-chart-2)"
            fill="var(--lf-chart-2)"
            fillOpacity={0.5}
            isAnimationActive={animate}
          />
          <Area
            dataKey="Investments"
            stackId="assets"
            stroke="var(--lf-chart-3)"
            fill="var(--lf-chart-3)"
            fillOpacity={0.5}
            isAnimationActive={animate}
          />
          <Area
            dataKey="Property"
            stackId="assets"
            stroke="var(--lf-chart-4)"
            fill="var(--lf-chart-4)"
            fillOpacity={0.5}
            isAnimationActive={animate}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
