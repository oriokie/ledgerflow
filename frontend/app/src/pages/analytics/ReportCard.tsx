import { AlertCircle, Download } from "lucide-react";

import { downloadFile } from "../../lib/download";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ReportMeta, ReportResult } from "../../api/types";
import { formatAmountSigned } from "../../lib/money";
import { Card, Money, Text } from "../../ui";
import { CHART_TICK_FONT_PX } from "../dashboard/chartTheme";
import {
  CHART_COLORS,
  caveatsOf,
  formatTimeLabel,
  humanizeKey,
  isMoneyKey,
  numericKeys,
  timeKeyOf,
} from "./reportRenderers";

const TOOLTIP_STYLE = {
  background: "var(--lf-bg-surface)",
  border: "1px solid var(--lf-border-card)",
  borderRadius: "var(--lf-radius-md)",
  fontSize: "var(--lf-text-xs)",
};

function axisProps() {
  return {
    stroke: "var(--lf-text-tertiary)",
    fontSize: CHART_TICK_FONT_PX,
    tickLine: false,
    axisLine: false,
  } as const;
}

/**
 * One report, drawn from its metadata.
 *
 * Seven chart types cover fourteen dashboards, and the series/rows/totals shape
 * is identical across all of them — so this is written once rather than
 * fourteen times, and a new report needs no frontend change at all.
 *
 * Money is formatted with `formatAmountSigned` throughout: these are standalone
 * strings in tooltips and cells, and `formatAmount` returns a magnitude, which
 * would render a −£450 deficit as a comfortable "£450".
 */
export function ReportCard({
  meta,
  result,
  exportPath,
  onDrillDown,
}: {
  meta: ReportMeta;
  result: ReportResult | null | undefined;
  exportPath: string;
  onDrillDown?: (row: Record<string, unknown>) => void;
}) {
  if (!result) {
    return (
      <Card title={meta.title}>
        <Text tone="tertiary" size="sm">
          Nothing to show for this period yet.
        </Text>
      </Card>
    );
  }

  const { currency } = result;
  const money = (value: unknown) =>
    formatAmountSigned(Math.round(Number(value ?? 0)), currency);
  const caveats = caveatsOf(result);

  const timeKey = timeKeyOf(result.series);
  const seriesKeys = numericKeys(result.series, {
    exclude: timeKey ? [timeKey] : [],
  }).filter((key) => !key.endsWith("_pct"));

  const chartData = result.series.map((row) => ({
    ...row,
    __label: timeKey ? formatTimeLabel(row[timeKey]) : "",
  }));

  return (
    <Card
      title={meta.title}
      action={
        <button
          type="button"
          className="lf-report-export"
          aria-label={`Export ${meta.title}`}
          onClick={() => downloadFile(exportPath, `${meta.slug}.csv`)}
        >
          <Download size={14} strokeWidth={2} aria-hidden="true" />
        </button>
      }
    >
      <div className="lf-report">
        {Object.keys(result.totals).length > 0 && (
          <dl className="lf-report-totals">
            {Object.entries(result.totals)
              // A score chart already shows `score` as its headline; repeating
              // it in the totals grid says the same number twice.
              .filter(([key]) => !(meta.chart === "score" && key === "score"))
              .slice(0, 4)
              .map(([key, value]) => (
                <div key={key}>
                  <dt>{humanizeKey(key)}</dt>
                  <dd>
                    {isMoneyKey(key) ? (
                      <Money amountMinor={Number(value ?? 0)} currency={currency} neutral />
                    ) : (
                      String(value ?? "—")
                    )}
                  </dd>
                </div>
              ))}
          </dl>
        )}

        {/* Caveats sit above the chart: a partial month read as a collapse in
            spending is the most common way these get misread. */}
        {caveats.map((caveat) => (
          <p className="lf-report-caveat" key={caveat}>
            <AlertCircle size={13} strokeWidth={2} aria-hidden="true" />
            {caveat}
          </p>
        ))}

        {meta.chart === "score" && typeof result.totals.score === "number" && (
          <div className="lf-report-score">
            <span className="lf-report-score-value">{result.totals.score}</span>
            <Text as="span" tone="tertiary" size="xs">
              out of 100
            </Text>
          </div>
        )}

        {(meta.chart === "area" || meta.chart === "line") && chartData.length > 1 && (
          <ResponsiveContainer width="100%" height={200}>
            {meta.chart === "area" ? (
              <AreaChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id={`fill-${meta.slug}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--lf-chart-1)" stopOpacity={0.26} />
                    <stop offset="100%" stopColor="var(--lf-chart-1)" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="__label" {...axisProps()} interval="preserveStartEnd" />
                <YAxis hide />
                <Tooltip formatter={money} contentStyle={TOOLTIP_STYLE} />
                {seriesKeys.slice(0, 1).map((key) => (
                  <Area
                    key={key}
                    type="monotone"
                    dataKey={key}
                    name={humanizeKey(key)}
                    stroke="var(--lf-chart-1)"
                    strokeWidth={2}
                    fill={`url(#fill-${meta.slug})`}
                  />
                ))}
              </AreaChart>
            ) : (
              <LineChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <XAxis dataKey="__label" {...axisProps()} interval="preserveStartEnd" />
                <YAxis hide />
                <Tooltip formatter={money} contentStyle={TOOLTIP_STYLE} />
                {seriesKeys.slice(0, 3).map((key, i) => (
                  <Line
                    key={key}
                    type="monotone"
                    dataKey={key}
                    name={humanizeKey(key)}
                    stroke={CHART_COLORS[i % CHART_COLORS.length]}
                    strokeWidth={2}
                    dot={false}
                  />
                ))}
              </LineChart>
            )}
          </ResponsiveContainer>
        )}

        {(meta.chart === "bar" || meta.chart === "composed") && chartData.length > 0 && (
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <XAxis dataKey="__label" {...axisProps()} interval="preserveStartEnd" />
              <YAxis hide />
              <Tooltip formatter={money} contentStyle={TOOLTIP_STYLE} />
              <Legend iconSize={9} wrapperStyle={{ fontSize: "var(--lf-text-xs)" }} />
              {seriesKeys.slice(0, 3).map((key, i) => (
                <Bar
                  key={key}
                  dataKey={key}
                  name={humanizeKey(key)}
                  fill={CHART_COLORS[i % CHART_COLORS.length]}
                  radius={[3, 3, 0, 0]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        )}

        {meta.chart === "donut" && result.rows.length > 0 && (
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie
                data={result.rows.slice(0, 6)}
                dataKey="amount_minor"
                nameKey="label"
                innerRadius={48}
                outerRadius={76}
                paddingAngle={2}
              >
                {result.rows.slice(0, 6).map((_, i) => (
                  <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip formatter={money} contentStyle={TOOLTIP_STYLE} />
              <Legend iconSize={9} wrapperStyle={{ fontSize: "var(--lf-text-xs)" }} />
            </PieChart>
          </ResponsiveContainer>
        )}

        {result.rows.length > 0 && (
          <div className="lf-table-wrap">
            <table className="lf-table lf-report-table">
              <caption className="lf-visually-hidden">{meta.title}</caption>
              <thead>
                <tr>
                  {Object.keys(result.rows[0])
                    .filter((key) => !key.endsWith("_id"))
                    .map((key) => (
                      <th
                        key={key}
                        scope="col"
                        className={typeof result.rows[0][key] === "number" ? "lf-col-amount" : undefined}
                      >
                        {humanizeKey(key)}
                      </th>
                    ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.slice(0, 10).map((row, i) => (
                  <tr
                    key={i}
                    // Drill-down: a row is a filter someone wants to apply.
                    onClick={onDrillDown ? () => onDrillDown(row) : undefined}
                    data-clickable={onDrillDown ? true : undefined}
                  >
                    {Object.entries(row)
                      .filter(([key]) => !key.endsWith("_id"))
                      .map(([key, value]) => (
                        <td key={key} className={typeof value === "number" ? "lf-col-amount" : undefined}>
                          {isMoneyKey(key) ? (
                            <Money amountMinor={Number(value ?? 0)} currency={currency} neutral />
                          ) : (
                            String(value ?? "—")
                          )}
                        </td>
                      ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Card>
  );
}
