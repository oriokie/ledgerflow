import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import { useAuth } from "../lib/AuthContext";
import { formatAmount, formatAmountSigned } from "../lib/money";
import { Badge, Banner, Card, Grid, PageHeader, Select, Skeleton, Text } from "../ui";

/** Mirrors apps.intelligence.review.compose — every figure traceable to the
 * selector that produced it, no arithmetic re-done client-side. */
interface ReviewDocument {
  period: { label: string; start: string; end: string };
  currency: string;
  sections: {
    net_worth: {
      opening_minor: number;
      closing_minor: number;
      delta_minor: number;
      approximate: boolean;
    };
    cashflow: {
      inflow_minor: number;
      outflow_minor: number;
      saved_minor: number;
      savings_rate_pct: number | null;
      previous_savings_rate_pct: number | null;
    };
    movers: {
      increases: { category_name: string; delta_minor: number; current_minor: number }[];
      decreases: { category_name: string; delta_minor: number; current_minor: number }[];
    };
    debt: { count: number; total_balance_minor: number; total_minimums_minor: number } | null;
    goals: {
      name: string;
      percent: number;
      success_probability: number | null;
      saved_minor: number;
      target_minor: number;
      currency: string;
    }[];
    fi: {
      fi_number_minor: number;
      progress_pct: number;
      years: number | null;
      around_year: number | null;
      never_at_current_pace: boolean;
      required_monthly_for_horizon_minor: number | null;
    } | null;
    actions: { title: string; body: string; severity: string }[];
  };
}

/** The last six completed months and four completed quarters, newest first. */
function periodOptions(now = new Date()): { value: string; label: string }[] {
  const options: { value: string; label: string }[] = [];
  for (let i = 1; i <= 6; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    options.push({ value, label: d.toLocaleDateString(undefined, { month: "long", year: "numeric" }) });
  }
  const currentQuarter = Math.floor(now.getMonth() / 3) + 1;
  let quarter = currentQuarter - 1 || 4;
  let year = currentQuarter === 1 ? now.getFullYear() - 1 : now.getFullYear();
  for (let i = 0; i < 4; i++) {
    options.push({ value: `${year}-Q${quarter}`, label: `Q${quarter} ${year}` });
    quarter -= 1;
    if (quarter === 0) {
      quarter = 4;
      year -= 1;
    }
  }
  return options;
}

/**
 * The advisor's periodic sit-down, as a page: where you stand, what changed,
 * what to do next. Every figure arrives composed from the same selectors the
 * rest of the product uses — this page renders a document, it does not do
 * arithmetic.
 */
export function ReviewPage() {
  const { activeWorkspace } = useAuth();
  const options = useMemo(() => periodOptions(), []);
  const [period, setPeriod] = useState(options[0]?.value ?? "");

  const { data, error, isLoading } = useQuery({
    queryKey: ["financial-review", activeWorkspace?.tenant.id, period],
    queryFn: () => api.get<ReviewDocument>(`/intelligence/review/?period=${period}`),
    enabled: !!activeWorkspace && !!period,
    staleTime: 5 * 60_000,
    retry: false,
  });

  const money = (minor: number) => formatAmount(minor, data?.currency ?? "USD");

  return (
    <>
      <PageHeader
        eyebrow="Financial review"
        title={data?.period.label ?? "Financial review"}
        description="Where you stand, what changed, and what to do next — the sit-down an advisor would run, from your own ledger."
        actions={
          <Select
            aria-label="Review period"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            options={options}
          />
        }
      />

      {isLoading && <Skeleton width="50%" />}

      {error && (
        <Banner tone="info">
          {error instanceof ApiError && typeof error.detail === "string"
            ? error.detail
            : "Couldn't put the review together."}
        </Banner>
      )}

      {data && (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--lf-space-4)" }}>
          <Grid cols={2} gap={4}>
            <Card title="Net worth">
              <p className="lf-review-figure">
                {formatAmountSigned(data.sections.net_worth.delta_minor, data.currency)}
                <Text tone="tertiary" size="sm" as="span">
                  {" "}
                  over the period
                </Text>
              </p>
              <Text tone="secondary" size="sm">
                {money(data.sections.net_worth.opening_minor)} →{" "}
                {money(data.sections.net_worth.closing_minor)}
                {data.sections.net_worth.approximate && " (history reconstructed from flows)"}
              </Text>
            </Card>

            <Card title="Cash flow">
              <p className="lf-review-figure">
                {data.sections.cashflow.savings_rate_pct === null
                  ? "No income recorded"
                  : `${data.sections.cashflow.savings_rate_pct}% saved`}
                {data.sections.cashflow.previous_savings_rate_pct !== null &&
                  data.sections.cashflow.savings_rate_pct !== null && (
                    <Text tone="tertiary" size="sm" as="span">
                      {" "}
                      (was {data.sections.cashflow.previous_savings_rate_pct}%)
                    </Text>
                  )}
              </p>
              <Text tone="secondary" size="sm">
                In {money(data.sections.cashflow.inflow_minor)} · out{" "}
                {money(data.sections.cashflow.outflow_minor)} · kept{" "}
                {formatAmountSigned(data.sections.cashflow.saved_minor, data.currency)}
              </Text>
            </Card>
          </Grid>

          <Card title="What changed">
            {data.sections.movers.increases.length === 0 &&
            data.sections.movers.decreases.length === 0 ? (
              <Text tone="secondary" size="sm">
                Spending held steady against the previous period — a finding in itself.
              </Text>
            ) : (
              <Grid cols={2} gap={4}>
                <div>
                  <Text tone="tertiary" size="xs">
                    SPENT MORE ON
                  </Text>
                  {data.sections.movers.increases.map((mover) => (
                    <p key={mover.category_name} className="lf-review-mover">
                      {mover.category_name}{" "}
                      <span>+{money(mover.delta_minor)}</span>
                    </p>
                  ))}
                </div>
                <div>
                  <Text tone="tertiary" size="xs">
                    SPENT LESS ON
                  </Text>
                  {data.sections.movers.decreases.map((mover) => (
                    <p key={mover.category_name} className="lf-review-mover">
                      {mover.category_name}{" "}
                      <span>{formatAmountSigned(mover.delta_minor, data.currency)}</span>
                    </p>
                  ))}
                </div>
              </Grid>
            )}
          </Card>

          <Grid cols={2} gap={4}>
            {data.sections.debt && (
              <Card title="Debt">
                <p className="lf-review-figure">{money(data.sections.debt.total_balance_minor)}</p>
                <Text tone="secondary" size="sm">
                  across {data.sections.debt.count} debt
                  {data.sections.debt.count === 1 ? "" : "s"} ·{" "}
                  {money(data.sections.debt.total_minimums_minor)}/mo in minimums
                </Text>
              </Card>
            )}

            {data.sections.fi && (
              <Card title="Financial independence">
                <p className="lf-review-figure">
                  {data.sections.fi.never_at_current_pace
                    ? "Not on the current path"
                    : `~${data.sections.fi.years} years${
                        data.sections.fi.around_year ? ` (${data.sections.fi.around_year})` : ""
                      }`}
                </p>
                <Text tone="secondary" size="sm">
                  {data.sections.fi.progress_pct}% of your{" "}
                  {money(data.sections.fi.fi_number_minor)} number
                  {data.sections.fi.never_at_current_pace &&
                    data.sections.fi.required_monthly_for_horizon_minor !== null &&
                    ` — ${money(data.sections.fi.required_monthly_for_horizon_minor)}/mo would change that`}
                </Text>
              </Card>
            )}
          </Grid>

          {data.sections.goals.length > 0 && (
            <Card title="Goals">
              {data.sections.goals.map((goal) => (
                <p key={goal.name} className="lf-review-mover">
                  {goal.name} <span>{goal.percent}%</span>
                  {goal.success_probability !== null && (
                    <Text tone="tertiary" size="xs" as="span">
                      {" "}
                      · {Math.round(goal.success_probability * 100)}% likely on current pace
                    </Text>
                  )}
                </p>
              ))}
            </Card>
          )}

          <Card title="Three things to do next">
            {data.sections.actions.length === 0 ? (
              <Text tone="secondary" size="sm">
                Nothing urgent — the coach has no open findings right now.
              </Text>
            ) : (
              data.sections.actions.map((action) => (
                <div key={action.title} className="lf-review-action">
                  <Badge tone={action.severity === "critical" ? "danger" : action.severity === "warning" ? "warning" : "neutral"}>
                    {action.severity}
                  </Badge>
                  <div>
                    <Text as="span">{action.title}</Text>
                    <Text tone="secondary" size="sm" style={{ display: "block" }}>
                      {action.body}
                    </Text>
                  </div>
                </div>
              ))
            )}
          </Card>
        </div>
      )}
    </>
  );
}
