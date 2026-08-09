import { Area, AreaChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { GoalForecast } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { Figure, FigureRow, Text } from "../../ui";
import type { FigureTone } from "../../ui";

/** Short month label for the projection axis, e.g. "Mar 27". */
function monthLabel(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
}

function fullDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

/**
 * How confident the forecast is, in words.
 *
 * Deliberately banded rather than shown as "73%". A heuristic rendered to the
 * percentage point implies a precision the model does not have, and in a
 * financial product that false precision is the thing users would rely on.
 * The numeric value stays available in the API for anyone who wants it.
 */
function confidenceBand(p: number): { label: string; tone: "success" | "warning" | "danger" } {
  if (p >= 0.7) return { label: "On track to make it", tone: "success" };
  if (p >= 0.4) return { label: "Could go either way", tone: "warning" };
  return { label: "Unlikely at this pace", tone: "danger" };
}

/** confidenceBand's tone vocabulary onto Figure's. */
const FIGURE_TONE_BY_BAND: Record<"success" | "warning" | "danger", FigureTone> = {
  success: "positive",
  warning: "warning",
  danger: "critical",
};

/**
 * The forecast half of a goal card: pace, projection, and what to change.
 *
 * Three monthly figures are shown separately because they answer different
 * questions — what you need, what you planned, what you're actually doing.
 * Collapsing them into one number is what makes most goal trackers useless
 * once a user falls behind.
 *
 * Every derived figure degrades honestly: where the engine returns null (no
 * deadline, too little history), this renders an explanation rather than a
 * zero. A fabricated forecast is worse than an absent one.
 */
export function GoalForecastPanel({ forecast }: { forecast: GoalForecast }) {
  const {
    currency,
    required_monthly_minor: required,
    planned_monthly_minor: planned,
    observed_monthly_minor: observed,
    monthly_shortfall_minor: shortfall,
    projected_completion: projected,
    target_date: targetDate,
    on_track: onTrack,
    success_probability: probability,
    consistency,
    projection = [],
  } = forecast;

  const band = probability === null ? null : confidenceBand(probability);

  const chartData = projection.map((p) => ({
    month: monthLabel(p.month),
    projected: p.projected_minor / 100,
    target: p.target_minor / 100,
  }));

  return (
    <div className="lf-goal-forecast">
      {/* --- the three monthly figures ---
          All three are model outputs — required and observed pace are derived
          from the projection, planned is what's scheduled against it — so all
          three carry certainty="projected", same as DebtAnalytics. */}
      <FigureRow>
        {required === null ? (
          <Figure
            label="Needed monthly"
            value={
              <Text tone="tertiary" size="sm">
                {targetDate ? "Target reached" : "No target date"}
              </Text>
            }
            certainty="projected"
          />
        ) : (
          <Figure
            label="Needed monthly"
            amountMinor={required}
            currency={currency}
            neutral
            certainty="projected"
          />
        )}
        {observed === null ? (
          <Figure
            label="Your pace"
            value={
              <Text tone="tertiary" size="sm">
                Not enough history
              </Text>
            }
            certainty="projected"
          />
        ) : (
          <Figure
            label="Your pace"
            amountMinor={observed}
            currency={currency}
            neutral
            certainty="projected"
          />
        )}
        {planned === null ? (
          <Figure
            label="Planned"
            value={
              <Text tone="tertiary" size="sm">
                Not set
              </Text>
            }
            certainty="projected"
          />
        ) : (
          <Figure
            label="Planned"
            amountMinor={planned}
            currency={currency}
            neutral
            certainty="projected"
          />
        )}
      </FigureRow>

      {/* The single most actionable number on the card: the gap. */}
      {shortfall !== null && shortfall > 0 && (
        <p className="lf-goal-shortfall">
          Add <strong>{formatAmount(shortfall, currency)}</strong> a month to reach this on time.
        </p>
      )}

      {/* --- completion --- */}
      <Figure
        label="Estimated completion"
        certainty="projected"
        value={
          projected ? (
            fullDate(projected)
          ) : (
            <Text tone="tertiary" size="sm">
              Not on a trajectory yet
            </Text>
          )
        }
        delta={
          onTrack !== null && (
            <span className={`lf-badge lf-badge--${onTrack ? "success" : "warning"}`}>
              {onTrack ? "On track" : "Behind"}
            </span>
          )
        }
      />

      {/* --- confidence, banded not numeric --- */}
      {band ? (
        <Figure
          label="Confidence"
          value={band.label}
          tone={FIGURE_TONE_BY_BAND[band.tone]}
          certainty="projected"
          hint={`based on ${Math.round(consistency * 100)}% of recent months funded`}
        />
      ) : (
        <Figure
          label="Confidence"
          value={
            <Text tone="tertiary" size="sm">
              Keep contributing for a few months and we'll estimate your chances.
            </Text>
          }
          certainty="projected"
        />
      )}

      {/* --- projection chart --- */}
      {chartData.length > 1 && (
        <div className="lf-goal-chart" aria-hidden="true">
          <ResponsiveContainer width="100%" height={140}>
            <AreaChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="goalProjection" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--lf-action-primary)" stopOpacity={0.28} />
                  <stop offset="100%" stopColor="var(--lf-action-primary)" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="month"
                tick={{ fontSize: 11, fill: "var(--lf-text-tertiary)" }}
                tickLine={false}
                axisLine={false}
                interval="preserveStartEnd"
              />
              <YAxis hide domain={[0, (d: number) => Math.max(d, forecast.target_minor / 100)]} />
              <Tooltip
                formatter={(value) => formatAmount(Math.round(Number(value ?? 0) * 100), currency)}
                contentStyle={{
                  background: "var(--lf-bg-surface)",
                  border: "1px solid var(--lf-border-card)",
                  borderRadius: "var(--lf-radius-md)",
                  fontSize: "var(--lf-text-xs)",
                }}
              />
              {/* The target line makes the chart answer "when do I cross it?" */}
              <ReferenceLine
                y={forecast.target_minor / 100}
                stroke="var(--lf-text-tertiary)"
                strokeDasharray="4 4"
              />
              <Area
                type="monotone"
                dataKey="projected"
                stroke="var(--lf-action-primary)"
                strokeWidth={2}
                fill="url(#goalProjection)"
              />
            </AreaChart>
          </ResponsiveContainer>
          <p className="lf-goal-chart-caption">
            <Text as="span" tone="tertiary" size="xs">
              Projected at your current pace. Dashed line is the target.
            </Text>
          </p>
        </div>
      )}
    </div>
  );
}
