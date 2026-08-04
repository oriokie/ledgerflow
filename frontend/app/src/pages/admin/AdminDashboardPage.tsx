import { CheckCircle2, Inbox } from "lucide-react";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Link } from "react-router-dom";

import type { RevenueBucket } from "../../api/platform";
import {
  useAnalytics,
  useDashboard,
  useDunningCases,
  useExpiringTrials,
  useHealth,
  usePlatformNotifications,
  useRefunds,
} from "../../hooks/usePlatform";
import { Badge, Card, EmptyState, Eyebrow, Figure, Grid, Inline, LoadingBlock, Stack, Text } from "../../ui";
import { CHART_TICK_FONT_PX } from "../dashboard/chartTheme";
import { AdminPageHeader } from "../../components/admin/AdminPageHeader";
import { money, monthTick, percent } from "./format";


function BreakdownCard({
  title,
  buckets,
  currency,
  emptyLabel,
}: {
  title: string;
  buckets: RevenueBucket[];
  currency: string;
  emptyLabel: string;
}) {
  if (!buckets?.length) {
    return (
      <Card title={title}>
        <Text size="sm" tone="tertiary">
          {emptyLabel}
        </Text>
      </Card>
    );
  }
  const largest = Math.max(...buckets.map((b) => b.mrr_minor), 1);
  return (
    <Card title={title}>
      <ul className="lf-admin-breakdown">
        {buckets.slice(0, 8).map((bucket) => (
          <li key={bucket.key}>
            <div className="lf-admin-breakdown-row">
              <span className="lf-admin-breakdown-key">{bucket.key || "Unknown"}</span>
              <span className="lf-admin-breakdown-value">{money(bucket.mrr_minor, currency)}</span>
            </div>
            <div
              className="lf-admin-breakdown-bar"
              style={{ width: `${Math.round((bucket.mrr_minor / largest) * 100)}%` }}
              aria-hidden
            />
            <Text size="xs" tone="tertiary">
              {bucket.customers} customer{bucket.customers === 1 ? "" : "s"}
            </Text>
          </li>
        ))}
      </ul>
    </Card>
  );
}

/**
 * What needs a human, above everything else.
 *
 * An operations console whose first screen is a grid of KPIs optimises for the
 * calm day. On the day something is wrong, the number that matters is buried
 * among nineteen that are fine. This strip is empty when nothing is wrong —
 * which is itself the most useful possible reading.
 */
function AttentionStrip() {
  const { data: health } = useHealth();
  const { data: dunning } = useDunningCases({ status: "open" });
  const { data: refunds } = useRefunds({ status: "requested" });
  const { data: alerts } = usePlatformNotifications({ open: "true" });

  const items: { tone: "danger" | "warning"; label: string; to: string }[] = [];

  if (health && health.status !== "ok") {
    items.push({
      tone: health.status === "down" ? "danger" : "warning",
      label: `System ${health.status}`,
      to: "/admin/health",
    });
  }
  for (const alert of alerts?.results ?? []) {
    if (alert.severity === "critical") {
      items.push({ tone: "danger", label: alert.title, to: "/admin/health" });
    }
  }
  if (dunning?.count) {
    items.push({
      tone: "warning",
      label: `${dunning.count} account${dunning.count === 1 ? "" : "s"} in payment recovery`,
      to: "/admin/dunning",
    });
  }
  if (refunds?.count) {
    items.push({
      tone: "warning",
      label: `${refunds.count} refund${refunds.count === 1 ? "" : "s"} awaiting a decision`,
      to: "/admin/billing",
    });
  }

  if (items.length === 0) {
    return (
      <Card prominence="quiet">
        <Inline gap={2}>
          <CheckCircle2 size={16} aria-hidden className="lf-admin-attention-ok" />
          <Text size="sm" tone="secondary">
            Nothing needs attention. Systems healthy, no failed payments awaiting recovery, no
            refunds pending.
          </Text>
        </Inline>
      </Card>
    );
  }

  return (
    <Card prominence="primary">
      <Stack gap={2}>
        <Eyebrow>Needs attention</Eyebrow>
        <ul className="lf-admin-attention">
          {items.slice(0, 6).map((item) => (
            <li key={`${item.to}-${item.label}`}>
              <Badge tone={item.tone}>{item.tone === "danger" ? "Critical" : "Action"}</Badge>
              <Link to={item.to}>{item.label}</Link>
            </li>
          ))}
        </ul>
      </Stack>
    </Card>
  );
}

/** A label and a figure on one dense line — the console's unit of supporting
 * detail, as opposed to the customer app's card per number. */
function Fact({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note?: string | null;
  tone?: "warning" | "danger";
}) {
  return (
    <div className="lf-admin-fact" data-tone={tone}>
      <dt>{label}</dt>
      <dd>
        {value}
        {note && <span className="lf-admin-fact-note">{note}</span>}
      </dd>
    </div>
  );
}

/** Direction is stated as a word as well as a sign, so the arrow is never the
 * only carrier (WCAG 1.4.1). */
function MrrDelta({ pct }: { pct: number }) {
  const up = pct >= 0;
  return (
    <span className="lf-admin-delta" data-tone={up ? "good" : "bad"}>
      {up ? "+" : ""}
      {pct.toFixed(1)}%
      <span className="lf-admin-fact-note">vs prior full month</span>
      <span className="lf-visually-hidden">
        {" "}
        collected revenue {up ? "up" : "down"}, comparing the last two complete months
      </span>
    </span>
  );
}

export function AdminDashboardPage() {
  const [currency, setCurrency] = useState("USD");
  const { data, isLoading, isError } = useDashboard(currency);
  const { data: trials } = useExpiringTrials(7);
  // Real series, not a decorative squiggle: the same `revenue_series` report
  // the Analytics page charts. Absent rather than flat when it has < 2 points.
  const series = useAnalytics<SeriesPoint[]>("revenue_series", { months: 12, currency });

  if (isLoading) return <LoadingBlock label="Loading platform metrics…" />;
  if (isError || !data) {
    return <EmptyState icon={Inbox} title="Metrics unavailable" body="Could not load platform metrics." />;
  }

  const { revenue, customers, churn, ltv, trials: trialStats, payments } = data;

  const points = series.data?.data ?? [];
  const spark = points.map((p) => ({ month: p.month, net: p.net_minor / 100 }));

  /* The change is computed between the last two *complete* months.
     The series' final point is the month in progress, and comparing a
     month-to-date figure against a finished month is not a comparison — on the
     third of the month it reported **-100%**, which is exactly what this first
     rendered. Same defect the Analytics screen was rebuilt around in Phase 4.8,
     and easy to reintroduce precisely because the arithmetic is right and only
     the basis is wrong. */
  const thisMonth = new Date().toISOString().slice(0, 7);
  const complete = points.filter((p) => !p.month.startsWith(thisMonth));
  const prev = complete.length >= 2 ? complete[complete.length - 2].net_minor : 0;
  const latest = complete.length >= 2 ? complete[complete.length - 1].net_minor : 0;
  // `null` also when the prior month was zero: a percentage change from nothing
  // is an artefact, not a finding.
  const mrrDelta = complete.length >= 2 && prev > 0 ? ((latest - prev) / prev) * 100 : null;

  return (
    <Stack gap={5}>
      <AdminPageHeader
        title="Platform"
        description="The estate at a glance: revenue, customers, and anything that needs a person."
        /* Hour and minute only. The seconds in the old timestamp implied a
           precision the metrics don't have — they are computed on page load,
           not streamed. */
        meta={`Updated ${new Date(data.generated_at).toLocaleTimeString(undefined, {
          hour: "2-digit",
          minute: "2-digit",
        })}`}
        actions={
          <select
            className="lf-select"
            value={currency}
            aria-label="Reporting currency"
            onChange={(event) => setCurrency(event.target.value)}
          >
            {(data.by_currency.length ? data.by_currency.map((b) => b.key) : ["USD"]).map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        }
      />

      <AttentionStrip />

      {/* One hero, then dense supporting lines.
          This was sixteen equal KPI cards in three equal grids, which asks the
          operator to decide what matters every time they open the page. It
          does not vary: MRR is the number the console exists to report, and
          everything else is context for it. Sixteen equal tiles is not a
          dashboard, it is a data dump with rounded corners. */}
      <div className="lf-admin-hero">
        <Card prominence="primary">
          <Figure
            label="Monthly recurring revenue"
            size="hero"
            amountMinor={revenue.mrr_minor}
            currency={revenue.currency}
            neutral
            delta={mrrDelta !== null && <MrrDelta pct={mrrDelta} />}
            hint="Annual plans normalised; complimentary accounts excluded"
          />

          {spark.length >= 2 && (
            /* `inert` as well as `aria-hidden`: recharts renders a focusable
               surface, so hiding the container from the accessibility tree
               without removing it from the tab order leaves a keyboard user
               tabbing through thirteen stops that a screen reader will not
               announce — the WCAG 4.1.2 failure axe reports as
               aria-hidden-focus. The chart restates the MRR figure printed
               directly above it, so there is nothing here to reach. */
            <div className="lf-admin-spark" aria-hidden="true" inert>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={spark} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
                  <Line
                    type="monotone"
                    dataKey="net"
                    stroke="var(--lf-action-primary)"
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          <dl className="lf-admin-facts">
            <Fact label="ARR" value={money(revenue.arr_minor, revenue.currency)} />
            <Fact label="ARPA" value={money(revenue.arpa_minor, revenue.currency)} />
            <Fact
              label="LTV"
              value={ltv.ltv_minor === null ? "—" : money(ltv.ltv_minor, revenue.currency)}
            />
          </dl>

          <dl className="lf-admin-facts">
            <Fact label="Collected today" value={money(revenue.today.net_minor, revenue.currency)} />
            <Fact label="MTD" value={money(revenue.month_to_date.net_minor, revenue.currency)} />
            <Fact label="Lifetime" value={money(revenue.lifetime.net_minor, revenue.currency)} />
            <Fact
              label="Payment success"
              value={percent(payments.success_rate)}
              note={payments.failed ? `${payments.failed} failed / 30d` : undefined}
              tone={
                payments.success_rate !== null && payments.success_rate < 0.9 ? "warning" : undefined
              }
            />
          </dl>
        </Card>

        {/* The estate, as a column of counts. An operator reads these as a
            list, not as eight separate objects. */}
        <Card>
          <Eyebrow>Estate</Eyebrow>
          <dl className="lf-admin-counts">
            <Fact label="Workspaces" value={String(customers.tenants_total ?? 0)} />
            <Fact label="Active" value={String(customers.tenants_active ?? 0)} />
            <Fact label="Trialing" value={String(customers.subscriptions_trialing ?? 0)} />
            <Fact
              label="Suspended"
              value={String(customers.tenants_suspended ?? 0)}
              tone={(customers.tenants_suspended ?? 0) > 0 ? "warning" : undefined}
            />
            <Fact
              label="Past due"
              value={String(customers.subscriptions_past_due ?? 0)}
              tone={(customers.subscriptions_past_due ?? 0) > 0 ? "danger" : undefined}
            />
            <Fact
              label="New (30d)"
              value={String(customers.signups ?? 0)}
              note={percent(customers.growth_rate)}
            />
            <Fact label="Churn (30d)" value={percent(churn.rate)} note={`${churn.churned} cancelled`} />
            <Fact
              label="Trial conversion"
              value={percent(trialStats.conversion_rate)}
              note={`${trialStats.converted}/${trialStats.trials_concluded}`}
            />
          </dl>
        </Card>
      </div>

      <Grid cols={4} gap={3}>
        <BreakdownCard
          title="Revenue by plan"
          buckets={data.by_plan}
          currency={revenue.currency}
          emptyLabel="No paid subscriptions yet."
        />
        <BreakdownCard
          title="Revenue by country"
          buckets={data.by_country}
          currency={revenue.currency}
          emptyLabel="No country data yet."
        />
        <BreakdownCard
          title="Revenue by currency"
          buckets={data.by_currency}
          currency={revenue.currency}
          emptyLabel="No revenue yet."
        />
        <BreakdownCard
          title="Revenue by provider"
          buckets={data.by_provider}
          currency={revenue.currency}
          emptyLabel="No provider data yet."
        />
      </Grid>

      <Card title="Trials ending within 7 days" ruledHeader>
        {trials?.length ? (
          <ul className="lf-admin-trial-list">
            {trials.map((trial) => (
              <li key={trial.tenant_id}>
                <Link className="lf-admin-link" to={`/admin/tenants/${trial.tenant_id}`}>
                  {trial.tenant_name || trial.tenant_id}
                </Link>
                <Badge tone={trial.days_left <= 2 ? "warning" : "neutral"}>
                  {trial.days_left} day{trial.days_left === 1 ? "" : "s"} left
                </Badge>
              </li>
            ))}
          </ul>
        ) : (
          <Text size="sm" tone="tertiary">
            No trials ending this week.
          </Text>
        )}
      </Card>
    </Stack>
  );
}

interface SeriesPoint {
  month: string;
  net_minor: number;
  gross_minor: number;
  refunded_minor: number;
  /** False for the current month, which is only complete on its last day. */
  partial: boolean;
}

/**
 * Split the series so the incomplete final month draws as unsettled.
 *
 * Recharts joins a line across nulls only if `connectNulls` is set, so two keys
 * with a deliberate one-point overlap give a continuous line whose last segment
 * carries a different treatment. The alternative — drawing the partial month
 * like every other point — is the defect this exists to fix: a month with three
 * days in it plotted against eleven full ones looks exactly like revenue
 * collapsing.
 */
function splitAtPartial(points: SeriesPoint[]) {
  const firstPartial = points.findIndex((p) => p.partial);
  if (firstPartial < 1) return { rows: points, hasPartial: false };
  return {
    rows: points.map((point, i) => ({
      ...point,
      settled_minor: i <= firstPartial - 1 ? point.net_minor : null,
      // Starts one point early so the two lines meet rather than leaving a gap.
      partial_minor: i >= firstPartial - 1 ? point.net_minor : null,
    })),
    hasPartial: true,
  };
}
interface CohortRow {
  cohort: string;
  signups: number;
  retained: number;
  retention_rate: number | null;
}

export function AdminAnalyticsPage() {
  const [currency] = useState("USD");
  const series = useAnalytics<SeriesPoint[]>("revenue_series", { months: 12, currency });
  const cohorts = useAnalytics<CohortRow[]>("cohorts", { months: 6 });
  const forecast = useAnalytics<{ month_offset: number; projected_mrr_minor: number; basis: string }[]>(
    "forecast",
    { months: 6, currency },
  );
  const revenue = splitAtPartial(series.data?.data ?? []);

  return (
    <Stack gap={5}>
      <AdminPageHeader
        title="Analytics"
        description="Longer arcs than the dashboard: a year of net revenue, signup cohorts, and where MRR goes if nothing changes."
      />

      <Card title="Net revenue, last 12 months" ruledHeader>
        {series.isLoading ? (
          <LoadingBlock />
        ) : (
          <div style={{ height: 260 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={revenue.rows}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--lf-border-subtle)" />
                {/* Twelve month labels do not fit a console chart at any width, and
                    nothing was stopping recharts from drawing all of them —
                    they only started colliding when the brand face replaced the
                    narrower system one. Thinning ticks is the fix; a smaller
                    font would just move the collision. */}
                <XAxis
                  dataKey="month"
                  tickFormatter={monthTick}
                  tick={{ fontSize: CHART_TICK_FONT_PX }}
                  interval="preserveStartEnd"
                  minTickGap={28}
                  /* The first tick otherwise sits flush against the Y axis and
                     lands on its "0" label. Shortening the text helped and did
                     not fix it — the collision is positional, not textual. */
                  padding={{ left: 18, right: 10 }}
                />
                <YAxis tickFormatter={(v) => String(v / 100)} tick={{ fontSize: CHART_TICK_FONT_PX }} />
                <Tooltip formatter={(value) => money(Number(value), currency)} />
                {revenue.hasPartial ? (
                  <>
                    <Line
                      type="monotone"
                      dataKey="settled_minor"
                      stroke="var(--lf-action-primary)"
                      strokeWidth={2}
                      dot={false}
                      name="Collected"
                    />
                    {/* Dashed, in the product's own colour for a figure that is
                        not settled. Same signal the customer-facing cash-flow
                        chart uses for a projection. */}
                    <Line
                      type="monotone"
                      dataKey="partial_minor"
                      stroke="var(--lf-chart-projected, var(--lf-text-tertiary))"
                      strokeWidth={2}
                      strokeDasharray="5 4"
                      dot={false}
                      name="This month so far"
                    />
                  </>
                ) : (
                  <Line
                    type="monotone"
                    dataKey="net_minor"
                    stroke="var(--lf-action-primary)"
                    strokeWidth={2}
                    dot={false}
                    name="Collected"
                  />
                )}
                <Legend />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
        {revenue.hasPartial && (
          <Text size="sm" tone="secondary">
            The final month is still running, so it is shown as incomplete rather
            than compared against full months.
          </Text>
        )}
      </Card>

      <Card title="Signup cohorts" ruledHeader>
        {cohorts.isLoading ? (
          <LoadingBlock />
        ) : (
          <div style={{ height: 240 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={cohorts.data?.data ?? []}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--lf-border-subtle)" />
                <XAxis
                  dataKey="cohort"
                  tickFormatter={monthTick}
                  tick={{ fontSize: CHART_TICK_FONT_PX }}
                  interval="preserveStartEnd"
                  minTickGap={28}
                  /* The first tick otherwise sits flush against the Y axis and
                     lands on its "0" label. Shortening the text helped and did
                     not fix it — the collision is positional, not textual. */
                  padding={{ left: 18, right: 10 }}
                />
                <YAxis tick={{ fontSize: CHART_TICK_FONT_PX }} allowDecimals={false} />
                <Tooltip />
                {/* Two series told apart by fill alone, with the names reachable
                    only by hovering. The design language requires a label on
                    every series precisely so hue is never load-bearing — see
                    verify_palette.py, which rejected a categorical ramp for the
                    same reason. */}
                <Legend />
                <Bar dataKey="signups" fill="var(--lf-ink-300)" name="Signups" />
                <Bar dataKey="retained" fill="var(--lf-action-primary)" name="Retained" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>

      <Card title="MRR projection" ruledHeader>
        <Text size="sm" tone="secondary">
          {forecast.data?.data?.[0]?.basis ??
            "Straight-line extrapolation of recent net revenue growth."}
        </Text>
        <ul className="lf-admin-forecast">
          {(forecast.data?.data ?? []).map((point) => (
            <li key={point.month_offset}>
              <span>+{point.month_offset}mo</span>
              <strong>{money(point.projected_mrr_minor, currency)}</strong>
            </li>
          ))}
        </ul>
      </Card>
    </Stack>
  );
}
