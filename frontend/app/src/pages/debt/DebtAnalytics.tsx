import { useState } from "react";

import { downloadFile } from "../../lib/download";
import { Download } from "lucide-react";
import { Area, AreaChart, Bar, BarChart, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DebtAnalytics as Analytics } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { Figure, FigureRow, Text } from "../../ui";
import { CHART_TICK_FONT_PX } from "../dashboard/chartTheme";

function monthLabel(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", year: "2-digit" });
}

const TOOLTIP_STYLE = {
  background: "var(--lf-bg-surface)",
  border: "1px solid var(--lf-border-card)",
  borderRadius: "var(--lf-radius-md)",
  fontSize: "var(--lf-text-xs)",
};

/**
 * Where the money actually goes, month by month.
 *
 * The stacked split of interest, fees and principal is the point. A single
 * "payment" bar hides the thing people most need to see — that early payments
 * are mostly interest — and watching the principal band grow as the plan
 * progresses explains the rollover far better than any figure.
 */
export function DebtAnalytics({
  analytics,
  exportPath,
}: {
  analytics: Analytics;
  exportPath: string;
}) {
  const { currency } = analytics;
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const split = analytics.series.map((point) => ({
    label: monthLabel(point.as_of),
    Principal: point.principal_minor / 100,
    Interest: point.interest_minor / 100,
    Fees: point.fees_minor / 100,
  }));

  const balance = analytics.series.map((point) => ({
    label: monthLabel(point.as_of),
    Balance: point.remaining_balance_minor / 100,
    "Interest paid": point.cumulative_interest_minor / 100,
  }));

  return (
    <div className="lf-debt-analytics">
      <div className="lf-debt-analytics-head">
        <FigureRow className="lf-debt-analytics-metrics">
          {/* Projected, not measured: every figure in this card comes out of
              the payoff simulation, so all three carry the treatment. Marking
              only the multi-year ones would imply the first month's figure was
              observed, and it wasn't — it's month one of the same run. */}
          <Figure
            label="Coming off the balance"
            amountMinor={analytics.monthly_velocity_minor}
            currency={currency}
            neutral
            certainty="projected"
            hint="per month"
          />
          <Figure
            label="Interest over the plan"
            amountMinor={analytics.total_interest_minor}
            currency={currency}
            neutral
            certainty="projected"
          />
          {analytics.total_fees_minor > 0 && (
            <Figure
              label="Fees over the plan"
              amountMinor={analytics.total_fees_minor}
              currency={currency}
              neutral
              certainty="projected"
            />
          )}
        </FigureRow>

        {/* A button, not a link: the endpoint is tenant-scoped and needs auth
            headers a bare anchor cannot send. */}
        <button
          type="button"
          className="lf-btn lf-btn--secondary lf-btn--sm"
          disabled={exporting}
          onClick={async () => {
            setExporting(true);
            try {
              await downloadFile(exportPath, "payoff-schedule.csv");
            } catch {
              setExportError("Could not export the schedule. Please try again.");
            } finally {
              setExporting(false);
            }
          }}
        >
          <Download size={14} strokeWidth={2} aria-hidden="true" />
          {exporting ? "Preparing…" : "Export schedule"}
        </button>
        {exportError && (
          <p className="lf-text-xs lf-text-tertiary" role="alert">
            {exportError}
          </p>
        )}
      </div>

      <div className="lf-debt-chart">
        <h3 className="lf-debt-chart-title">Where each payment goes</h3>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={split} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
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
              formatter={(value) => formatAmount(Math.round(Number(value ?? 0) * 100), currency)}
              contentStyle={TOOLTIP_STYLE}
            />
            <Legend
              verticalAlign="bottom"
              height={24}
              wrapperStyle={{ fontSize: "var(--lf-text-xs)" }}
            />
            {/* Principal first so it reads from the baseline up — the part
                that's actually reducing what you owe. The order is load-bearing
                now, not just aesthetic: it's what identifies the bands without
                relying on colour. */}
            <Bar dataKey="Principal" stackId="p" fill="var(--lf-status-success)" />
            <Bar dataKey="Interest" stackId="p" fill="var(--lf-status-danger)" />
            <Bar dataKey="Fees" stackId="p" fill="var(--lf-status-warning)" />
          </BarChart>
        </ResponsiveContainer>
        {/* Was "Green reduces what you owe. Red and amber don't." — which names
            the bands by colour and nothing else, so a deuteranopic reader has
            no way to tell which is which (WCAG 1.4.1). Stacking order is a
            redundant, colour-free encoding, and the legend names each band. */}
        <Text tone="tertiary" size="xs">
          Each bar stacks principal at the bottom, then interest, then fees. Only the principal
          reduces what you owe.
        </Text>
      </div>

      <div className="lf-debt-chart">
        <h3 className="lf-debt-chart-title">Balance against interest paid</h3>
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={balance} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="lf-debt-balance" x1="0" y1="0" x2="0" y2="1">
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
              formatter={(value) => formatAmount(Math.round(Number(value ?? 0) * 100), currency)}
              contentStyle={TOOLTIP_STYLE}
            />
            {/* Solid-filled area against a dashed line is already a
                colour-free distinction; the legend is what says which is
                which. Without it the chart was two unnamed curves. */}
            <Legend
              verticalAlign="bottom"
              height={24}
              wrapperStyle={{ fontSize: "var(--lf-text-xs)" }}
            />
            <Area
              type="monotone"
              dataKey="Balance"
              stroke="var(--lf-chart-1)"
              strokeWidth={2}
              fill="url(#lf-debt-balance)"
            />
            {/* The crossing point, where interest paid overtakes what's left,
                is the single most sobering thing on this page. */}
            <Area
              type="monotone"
              dataKey="Interest paid"
              stroke="var(--lf-status-danger)"
              strokeWidth={1.5}
              fill="none"
              strokeDasharray="4 4"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
