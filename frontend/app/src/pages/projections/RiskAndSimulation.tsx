import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ApiError } from "../../api/client";
import type { RiskProfile, SensitivityResult, SimulationResult } from "../../api/projections";
import { advisorApi } from "../../api/projections";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";
import { formatAmount, formatAmountSigned, minorToMajor } from "../../lib/money";
import { Banner, Card, Figure, Grid, Meter, Stack, Text } from "../../ui";
import { AXIS_TICK, axisLineProps, compactNumber, gridProps } from "../dashboard/chartTheme";

const tooltipStyle = {
  borderRadius: 8,
  border: "1px solid var(--lf-border-subtle)",
  fontSize: "var(--lf-text-xs)",
  background: "var(--lf-bg-surface)",
};

/**
 * The fan: a band rather than a line.
 *
 * Drawn as stacked areas because recharts has no native band mark — the p10
 * layer is transparent and each higher percentile is stacked on the difference,
 * which paints the interval without inventing a series that means anything on
 * its own. The median is drawn on top, because it is the only line here anyone
 * should read as a number.
 */
export function SimulationFan({ result }: { result: SimulationResult }) {
  const animate = !usePrefersReducedMotion();
  const data = result.bands.map((b) => ({
    month: b.month,
    base: minorToMajor(b.p10),
    lower: minorToMajor(b.p25 - b.p10),
    middle: minorToMajor(b.p75 - b.p25),
    upper: minorToMajor(b.p90 - b.p75),
    median: minorToMajor(b.p50),
  }));

  // The bands are sampled every few months, so rounding each to the nearest
  // year produces duplicate labels ("1y 1y 2y 3y 3y"). Pick one sampled point
  // per year instead and let recharts drop any that still crowd.
  const yearTicks = Array.from(
    new Map(data.map((d) => [Math.floor((d.month - 1) / 12), d.month])).values(),
  );

  return (
    <div className="lf-chart-container" data-testid="simulation-fan">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid {...gridProps} />
          <XAxis
            dataKey="month"
            tick={AXIS_TICK}
            {...axisLineProps}
            minTickGap={32}
            padding={{ left: 22, right: 14 }}
            ticks={yearTicks}
            tickFormatter={(m) => `${Math.floor((Number(m) - 1) / 12) + 1}y`}
          />
          <YAxis tick={AXIS_TICK} {...axisLineProps} tickFormatter={compactNumber} width={52} />
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={(m) => `Month ${m}`}
            formatter={(v, name) =>
              name === "median"
                ? [formatAmountSigned(Math.round(Number(v) * 100), result.currency), "Middle outcome"]
                : []
            }
          />
          <ReferenceLine y={0} stroke="var(--lf-status-danger)" strokeDasharray="3 3" />
          <Area dataKey="base" stackId="fan" stroke="none" fill="transparent" isAnimationActive={animate} />
          <Area
            dataKey="lower"
            stackId="fan"
            stroke="none"
            fill="var(--lf-chart-1)"
            fillOpacity={0.14}
            isAnimationActive={animate}
          />
          <Area
            dataKey="middle"
            stackId="fan"
            stroke="none"
            fill="var(--lf-chart-1)"
            fillOpacity={0.26}
            isAnimationActive={animate}
          />
          <Area
            dataKey="upper"
            stackId="fan"
            stroke="none"
            fill="var(--lf-chart-1)"
            fillOpacity={0.14}
            isAnimationActive={animate}
          />
          <Area
            dataKey="median"
            stroke="var(--lf-chart-1)"
            strokeWidth={2}
            fill="none"
            isAnimationActive={animate}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/** The tornado: which assumption moves the answer most. */
export function Tornado({ result }: { result: SensitivityResult }) {
  const animate = !usePrefersReducedMotion();
  const data = result.swings.map((s) => ({
    label: s.label,
    spread: minorToMajor(s.spread_minor),
    direction: s.direction,
  }));

  return (
    <div className="lf-chart-container" data-testid="tornado">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
          <CartesianGrid {...gridProps} horizontal={false} />
          <XAxis type="number" tick={AXIS_TICK} {...axisLineProps} tickFormatter={compactNumber} />
          <YAxis
            type="category"
            dataKey="label"
            tick={AXIS_TICK}
            {...axisLineProps}
            width={150}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(v) => [
              formatAmount(Math.round(Number(v) * 100), result.currency),
              "Swing in final net worth",
            ]}
          />
          <Bar dataKey="spread" radius={[0, 4, 4, 0]} maxBarSize={22} isAnimationActive={animate}>
            {data.map((row) => (
              <Cell
                key={row.label}
                fill={
                  row.direction === "higher is worse"
                    ? "var(--lf-chart-expense)"
                    : "var(--lf-chart-1)"
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function RiskPanel({ profile }: { profile: RiskProfile }) {
  return (
    <Card title="What would bite first">
      <Stack gap={4}>
        <Text size="md" weight="semibold">
          {profile.headline}
        </Text>
        <Meter
          value={profile.resilience}
          caption={`Resilience ${profile.resilience} of 100 — the weakest exposure, not the average`}
          aria-label="Financial resilience"
        />
        <ul className="lf-finding-list">
          {profile.factors.map((f) => (
            <li key={f.key}>
              <div className="lf-risk-row">
                <Text size="sm" weight="medium">
                  {f.label}
                </Text>
                <Text size="sm" tone={f.score < 40 ? "primary" : "secondary"}>
                  {f.score}/100
                </Text>
              </div>
              <Text size="sm" tone="secondary">
                {f.detail}
              </Text>
              {f.remedy && (
                <Text size="sm" tone="secondary">
                  → {f.remedy}
                </Text>
              )}
            </li>
          ))}
        </ul>
        {profile.notes.map((n) => (
          <Text key={n} size="xs" tone="tertiary">
            {n}
          </Text>
        ))}
      </Stack>
    </Card>
  );
}

/** The whole "how sure are we" surface: simulation, tornado and risk. */
export function RiskAndSimulation({ months }: { months: number }) {
  const [simulation, setSimulation] = useState<SimulationResult | null>(null);
  const [sensitivity, setSensitivity] = useState<SensitivityResult | null>(null);
  const [profile, setProfile] = useState<RiskProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      advisorApi.simulate({ months, trials: 400 }),
      advisorApi.sensitivity(months),
      advisorApi.risk(),
    ])
      .then(([sim, sens, risk]) => {
        if (cancelled) return;
        setSimulation(sim);
        setSensitivity(sens);
        setProfile(risk);
        setError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.detail : "Couldn't run the analysis.");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [months]);

  if (loading) return <Text size="sm" tone="secondary">Running the simulation…</Text>;
  if (error) return <Banner tone="warning">{error}</Banner>;

  return (
    <Stack gap={5}>
      {simulation && (
        <Card title="A thousand versions of the next few years">
          <Grid cols={3}>
            <Figure
              label="Chance you never run out"
              value={`${Math.round(simulation.success_probability * 100)}%`}
              tone={simulation.success_probability < 0.8 ? "warning" : "default"}
              certainty="projected"
            />
            <Figure
              label="Middle outcome"
              value={formatAmountSigned(simulation.closing_net_worth.p50, simulation.currency)}
              certainty="projected"
            />
            <Figure
              label="Unlucky outcome (1 in 10)"
              value={formatAmountSigned(simulation.closing_net_worth.p10, simulation.currency)}
              hint="Worse than this in a tenth of runs"
              certainty="projected"
            />
          </Grid>
          <SimulationFan result={simulation} />
          <ul className="lf-assumption-list">
            {simulation.assumptions.map((a) => (
              <li key={a}>
                <Text size="sm" tone="secondary">
                  {a}
                </Text>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {sensitivity && (
        <Card title="What the answer actually rests on">
          <Tornado result={sensitivity} />
          {sensitivity.notes.map((n) => (
            <Text key={n} size="xs" tone="tertiary">
              {n}
            </Text>
          ))}
        </Card>
      )}

      {profile && <RiskPanel profile={profile} />}
    </Stack>
  );
}
