import { AlertTriangle } from "lucide-react";
import { useMemo } from "react";
import {
  Area,
  AreaChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CashflowCalendar as Calendar } from "../../api/types";
import { formatAmount, formatAmountSigned } from "../../lib/money";
import { Banner, Money, Table, Text, type Column } from "../../ui";
import { parseDay, toMonthlyRollups, type MonthlyRollup } from "./calendarUtils";
import { CHART_TICK_FONT_PX } from "../dashboard/chartTheme";

function shortDate(iso: string, locale?: string): string {
  return parseDay(iso).toLocaleDateString(locale, { day: "numeric", month: "short" });
}

/**
 * The long-horizon view of a projection.
 *
 * Past about a quarter the day grid stops answering questions and starts
 * listing numbers, so six and twelve month windows get this instead: the
 * balance line for shape, and a month-by-month table for the figures. Both
 * lead with the trough rather than the closing balance — a year that ends
 * comfortably can still have three months where rent doesn't clear, and the
 * closing figure alone would hide that entirely.
 */
export function CashflowOutlook({ calendar }: { calendar: Calendar }) {
  const currency = calendar.currency;

  const rollups = useMemo(() => toMonthlyRollups(calendar.days), [calendar.days]);

  /* Recharts stacks an area on the one below it, so a *range* is drawn as a
     transparent base at the lower bound plus a band of the difference. */
  const data = useMemo(
    () =>
      calendar.days.map((d) => ({
        label: shortDate(d.day),
        Balance: d.closing_minor / 100,
        base: d.expected_low_minor === null ? null : d.expected_low_minor / 100,
        span:
          d.expected_low_minor === null || d.expected_high_minor === null
            ? null
            : (d.expected_high_minor - d.expected_low_minor) / 100,
        Likely: d.expected_minor === null ? null : d.expected_minor / 100,
      })),
    [calendar.days],
  );

  const everyday = calendar.everyday;

  const goesNegative = calendar.negative_day_count > 0;

  /* Five money columns do not fit a 375px phone, and the mobile table reflow
     pins every `.lf-col-amount` into one grid slot — so without `hideMobile`
     they stacked on top of each other. The two that survive are the two that
     answer the page's question: the trough, and where the month ends. */
  const columns: Column<MonthlyRollup>[] = [
    { key: "label", header: "Month", render: (r: MonthlyRollup) => r.label },
    {
      key: "in",
      hideMobile: true,
      header: "In",
      align: "right",
      render: (r) => <Money amountMinor={r.inflowMinor} currency={currency} />,
    },
    {
      key: "out",
      hideMobile: true,
      header: "Out",
      align: "right",
      render: (r) => <Money amountMinor={-r.outflowMinor} currency={currency} />,
    },
    {
      key: "net",
      hideMobile: true,
      header: "Net",
      align: "right",
      render: (r) => <Money amountMinor={r.netMinor} currency={currency} />,
    },
    {
      key: "low",
      header: "Lowest",
      align: "right",
      // The month's worst moment, not its result. A month can end fine and
      // still have been unsurvivable in the middle.
      render: (r) => (
        <span className={r.lowestMinor < 0 ? "lf-outlook-danger" : undefined}>
          {formatAmount(r.lowestMinor, currency)}
          {r.negativeDays > 0 && (
            <span className="lf-outlook-negdays">
              {" "}
              · {r.negativeDays} day{r.negativeDays === 1 ? "" : "s"} under
            </span>
          )}
        </span>
      ),
    },
    {
      key: "end",
      header: "Ends at",
      align: "right",
      render: (r) => <Money amountMinor={r.endBalanceMinor} currency={currency} neutral />,
    },
  ];

  return (
    <div className="lf-outlook">
      {goesNegative && calendar.first_negative_on && (
        <Banner tone="danger">
          <AlertTriangle size={16} aria-hidden="true" style={{ verticalAlign: "-3px", marginRight: 6 }} />
          Projected to go below zero on {shortDate(calendar.first_negative_on)}, and to stay under
          on {calendar.negative_day_count} day{calendar.negative_day_count === 1 ? "" : "s"} in this
          window.
        </Banner>
      )}

      <div className="lf-outlook-chart">
        <ResponsiveContainer width="100%" height={240}>
          <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="lf-outlook-fill" x1="0" y1="0" x2="0" y2="1">
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
              minTickGap={40}
            />
            <YAxis hide />
            {/* Zero is the only line on this chart that means anything, so it
                is the only one drawn. */}
            <ReferenceLine y={0} stroke="var(--lf-status-danger)" strokeDasharray="3 3" />
            <Tooltip
              contentStyle={{
                background: "var(--lf-bg-surface)",
                border: "1px solid var(--lf-border-default)",
                borderRadius: "var(--lf-radius-md)",
                fontSize: "var(--lf-text-sm)",
              }}
              formatter={(value) => formatAmountSigned(Math.round(Number(value ?? 0) * 100), currency)}
            />
            {/* The band goes down first so the committed line draws over it. */}
            {everyday && (
              <>
                <Area
                  type="monotone"
                  dataKey="base"
                  stackId="band"
                  stroke="none"
                  fill="none"
                  isAnimationActive={false}
                  legendType="none"
                  tooltipType="none"
                />
                <Area
                  type="monotone"
                  dataKey="span"
                  stackId="band"
                  stroke="none"
                  fill="var(--lf-certainty-projected)"
                  fillOpacity={0.16}
                  isAnimationActive={false}
                  legendType="none"
                  tooltipType="none"
                />
                <Area
                  type="monotone"
                  dataKey="Likely"
                  stroke="var(--lf-certainty-projected)"
                  strokeWidth={1.5}
                  strokeDasharray="4 3"
                  fill="none"
                />
              </>
            )}
            <Area
              type="monotone"
              dataKey="Balance"
              stroke="var(--lf-chart-1)"
              strokeWidth={2}
              fill="url(#lf-outlook-fill)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* A shaded region with no stated basis is decoration pretending to be
          rigour. Say what was measured, over how long, and what the band means. */}
      {everyday ? (
        <Text tone="tertiary" size="xs">
          The solid line is money you have already committed — bills and recurring items only. The
          shaded band adds ordinary day-to-day spending, measured from{" "}
          {everyday.observed_days} days of your history: you spent something on{" "}
          {everyday.active_days} of them, averaging{" "}
          <Money amountMinor={everyday.mean_minor} currency={currency} neutral /> a day. The band is
          the range that total usually lands in, and it widens further out because a month of
          guessing is less certain than a week of it.
        </Text>
      ) : (
        <Text tone="tertiary" size="xs">
          This line counts bills and recurring items only — not day-to-day spending, which needs a
          few weeks of history before it can be estimated. Treat it as the best case.
        </Text>
      )}

      {rollups.length > 0 ? (
        <Table<MonthlyRollup>
          columns={columns}
          rows={rollups}
          rowKey={(r) => r.month}
          caption="Projected month by month"
        />
      ) : (
        <Text tone="tertiary" size="sm">
          Nothing scheduled in this window yet.
        </Text>
      )}
    </div>
  );
}
