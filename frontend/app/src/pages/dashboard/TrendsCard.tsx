import { useState } from "react";
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Forecast, NetWorthHistoryPoint, SpendingTrendPoint } from "../../api/types";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";
import { minorToMajor } from "../../lib/money";
import { Card, Tabs, Text } from "../../ui";
import type { TabItem } from "../../ui";
import { ChartTooltip } from "./chart";
import { AXIS_TICK, axisLineProps, compactNumber, gridProps } from "./chartTheme";

type TrendTab = "cashflow" | "networth" | "forecast";

const TABS: TabItem<TrendTab>[] = [
  { value: "cashflow", label: "Cash flow" },
  { value: "networth", label: "Net worth" },
  { value: "forecast", label: "Forecast" },
];

function shortMonth(label: string | number): string {
  const d = new Date(label);
  return Number.isNaN(d.getTime()) ? String(label) : d.toLocaleDateString(undefined, { month: "short" });
}
function longMonth(label: string | number): string {
  const d = new Date(label);
  return Number.isNaN(d.getTime()) ? String(label) : d.toLocaleDateString(undefined, { month: "short", year: "numeric" });
}

function Empty({ msg }: { msg: string }) {
  return (
    <div style={{ display: "grid", placeItems: "center", height: "100%" }}>
      <Text tone="tertiary" size="sm">{msg}</Text>
    </div>
  );
}

export function TrendsCard({
  trend,
  history,
  forecast,
  currency,
}: {
  trend: SpendingTrendPoint[] | undefined;
  history: NetWorthHistoryPoint[] | undefined;
  forecast: Forecast | undefined;
  currency: string;
}) {
  const [tab, setTab] = useState<TrendTab>("cashflow");

  const cashflowData = (trend ?? []).map((p) => ({
    label: p.period_start,
    income: minorToMajor(p.income_minor),
    expense: minorToMajor(p.expense_minor),
    net: minorToMajor(p.net_minor),
  }));
  const networthData = (history ?? []).map((p) => ({
    label: p.as_of,
    net: minorToMajor(p.net_minor),
  }));
  const animate = !usePrefersReducedMotion();
  const forecastData = (forecast?.points ?? []).map((p) => ({
    label: p.period_start,
    projected: minorToMajor(p.projected_expense_minor),
    low: minorToMajor(p.low_minor),
    high: minorToMajor(p.high_minor),
  }));

  return (
    <Card
      title="Trends"
      action={<Tabs<TrendTab> label="Trend view" value={tab} onChange={setTab} tabs={TABS} />}
    >
      <div className="lf-chart-tall" style={{ marginTop: "var(--lf-space-3)" }}>
        <ResponsiveContainer width="100%" height="100%">
          {tab === "cashflow" ? (
            cashflowData.length === 0 ? (
              <Empty msg="No cash-flow history yet." />
            ) : (
              <ComposedChart data={cashflowData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="label" tickFormatter={shortMonth} tick={AXIS_TICK} {...axisLineProps} />
                <YAxis tickFormatter={compactNumber} tick={AXIS_TICK} {...axisLineProps} width={44} />
                <Tooltip
                  content={<ChartTooltip currency={currency} labelFormatter={longMonth} />}
                  cursor={{ fill: "var(--lf-bg-sunken)" }}
                />
                <Bar dataKey="income" name="Income" fill="var(--lf-chart-income)" radius={[3, 3, 0, 0]} maxBarSize={22} isAnimationActive={animate} />
                <Bar dataKey="expense" name="Spending" fill="var(--lf-chart-expense)" radius={[3, 3, 0, 0]} maxBarSize={22} isAnimationActive={animate} />
                <Line type="monotone" dataKey="net" name="Net" stroke="var(--lf-iris-600)" strokeWidth={2} dot={false} isAnimationActive={animate} />
              </ComposedChart>
            )
          ) : tab === "networth" ? (
            networthData.length < 2 ? (
              <Empty msg="Net worth history builds over time." />
            ) : (
              <ComposedChart data={networthData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="nwArea" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--lf-iris-600)" stopOpacity={0.24} />
                    <stop offset="100%" stopColor="var(--lf-iris-600)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="label" tickFormatter={shortMonth} tick={AXIS_TICK} {...axisLineProps} />
                <YAxis tickFormatter={compactNumber} tick={AXIS_TICK} {...axisLineProps} width={44} />
                <Tooltip content={<ChartTooltip currency={currency} labelFormatter={longMonth} />} />
                <Area
                  type="monotone"
                  dataKey="net"
                  name="Net worth"
                  stroke="var(--lf-iris-600)"
                  strokeWidth={2}
                  fill="url(#nwArea)"
                />
              </ComposedChart>
            )
          ) : forecastData.length === 0 ? (
            <Empty msg="Forecast needs a few months of data." />
          ) : (
            <ComposedChart data={forecastData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="fcArea" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--lf-chart-expense)" stopOpacity={0.18} />
                  <stop offset="100%" stopColor="var(--lf-chart-expense)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="label" tickFormatter={shortMonth} tick={AXIS_TICK} {...axisLineProps} />
              <YAxis tickFormatter={compactNumber} tick={AXIS_TICK} {...axisLineProps} width={44} />
              <Tooltip content={<ChartTooltip currency={currency} labelFormatter={longMonth} />} />
              <Line dataKey="high" name="High" stroke="var(--lf-border-strong)" strokeWidth={1} strokeDasharray="4 4" dot={false} isAnimationActive={animate} />
              <Line dataKey="low" name="Low" stroke="var(--lf-border-strong)" strokeWidth={1} strokeDasharray="4 4" dot={false} isAnimationActive={animate} />
              <Area
                type="monotone"
                dataKey="projected"
                name="Projected spend"
                stroke="var(--lf-chart-expense)"
                strokeWidth={2}
                fill="url(#fcArea)"
              />
            </ComposedChart>
          )}
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
