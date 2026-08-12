import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import { useAuth } from "../lib/AuthContext";
import { Badge, Banner, Card, Figure, FigureRow, Grid, Money, PageHeader, Select, Skeleton, Text } from "../ui";

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
    subscriptions: {
      count: number;
      annual_total_minor: number;
      top: { name: string; annual_minor: number; amount_minor: number; frequency: string }[];
      price_rises: {
        payee: string;
        previous_minor: number;
        current_minor: number;
        delta_pct: number;
      }[];
    } | null;
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

  return (
    <>
      <PageHeader
        eyebrow="Meaning"
        title={data?.period.label ?? "Financial review"}
        description="Where you stand, what changed, and what to do next — the sit-down an advisor would run, from your own ledger."
        illustration="insight"
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
        <Banner>
          {error instanceof ApiError && typeof error.detail === "string"
            ? error.detail
            : "Couldn't put the review together."}
        </Banner>
      )}

      {data && (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--lf-space-4)" }}>
          <Grid cols={2} gap={4}>
            <Card title="Net worth">
              <Figure
                label="Change over the period"
                amountMinor={data.sections.net_worth.delta_minor}
                currency={data.currency}
                neutral
                size="primary"
              />
              <Text tone="secondary" size="sm">
                <Money amountMinor={data.sections.net_worth.opening_minor} currency={data.currency} neutral />{" "}
                →{" "}
                <Money amountMinor={data.sections.net_worth.closing_minor} currency={data.currency} neutral />
                {data.sections.net_worth.approximate && " (history reconstructed from flows)"}
              </Text>
            </Card>

            <Card title="Cash flow">
              <Figure
                label="Savings rate"
                value={
                  data.sections.cashflow.savings_rate_pct === null
                    ? "No income recorded"
                    : `${data.sections.cashflow.savings_rate_pct}% saved`
                }
                size="primary"
                delta={
                  data.sections.cashflow.previous_savings_rate_pct !== null &&
                  data.sections.cashflow.savings_rate_pct !== null
                    ? `was ${data.sections.cashflow.previous_savings_rate_pct}%`
                    : undefined
                }
              />
              <Text tone="secondary" size="sm">
                In <Money amountMinor={data.sections.cashflow.inflow_minor} currency={data.currency} neutral /> ·
                out <Money amountMinor={data.sections.cashflow.outflow_minor} currency={data.currency} neutral /> ·
                kept <Money amountMinor={data.sections.cashflow.saved_minor} currency={data.currency} neutral />
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
                      <span>
                        +<Money amountMinor={mover.delta_minor} currency={data.currency} neutral />
                      </span>
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
                      <span>
                        <Money amountMinor={mover.delta_minor} currency={data.currency} neutral />
                      </span>
                    </p>
                  ))}
                </div>
              </Grid>
            )}
          </Card>

          {data.sections.subscriptions && (
            <Card title="Subscriptions & fees">
              <Figure
                label="Annual total"
                amountMinor={data.sections.subscriptions.annual_total_minor}
                currency={data.currency}
                neutral
                size="primary"
                hint={`across ${data.sections.subscriptions.count} standing order${
                  data.sections.subscriptions.count === 1 ? "" : "s"
                }`}
              />
              {data.sections.subscriptions.top.map((sub) => (
                <p key={sub.name} className="lf-review-mover">
                  {sub.name}{" "}
                  <span>
                    <Money amountMinor={sub.annual_minor} currency={data.currency} neutral />/yr
                  </span>
                </p>
              ))}
              {data.sections.subscriptions.price_rises.length > 0 && (
                <>
                  <Text tone="tertiary" size="xs" style={{ marginTop: "var(--lf-space-3)" }}>
                    PRICES THAT MOVED ON YOU
                  </Text>
                  {data.sections.subscriptions.price_rises.map((rise) => (
                    <p key={rise.payee} className="lf-review-mover">
                      {rise.payee}{" "}
                      <span>
                        <Money amountMinor={rise.previous_minor} currency={data.currency} neutral /> →{" "}
                        <Money amountMinor={rise.current_minor} currency={data.currency} neutral /> (+
                        {Math.round(rise.delta_pct * 100)}%)
                      </span>
                    </p>
                  ))}
                </>
              )}
            </Card>
          )}

          <Grid cols={2} gap={4}>
            {data.sections.debt && (
              <Card title="Debt">
                <Figure
                  label="Total balance"
                  amountMinor={data.sections.debt.total_balance_minor}
                  currency={data.currency}
                  neutral
                  size="primary"
                  hint={
                    <>
                      across {data.sections.debt.count} debt{data.sections.debt.count === 1 ? "" : "s"} ·{" "}
                      <Money
                        amountMinor={data.sections.debt.total_minimums_minor}
                        currency={data.currency}
                        neutral
                      />
                      /mo in minimums
                    </>
                  }
                />
              </Card>
            )}

            {data.sections.fi && (
              <Card title="Financial independence">
                {data.sections.fi.never_at_current_pace ? (
                  <Figure
                    label="Time to FI"
                    value="Not on the current path"
                    size="primary"
                    certainty="projected"
                  />
                ) : (
                  <Figure
                    label="Time to FI"
                    value={`${data.sections.fi.years} years`}
                    size="primary"
                    certainty="projected"
                    hint={
                      data.sections.fi.around_year ? `around ${data.sections.fi.around_year}` : undefined
                    }
                  />
                )}
                <Text tone="secondary" size="sm">
                  {data.sections.fi.progress_pct}% of your{" "}
                  <Money amountMinor={data.sections.fi.fi_number_minor} currency={data.currency} neutral />{" "}
                  number
                  {data.sections.fi.never_at_current_pace &&
                    data.sections.fi.required_monthly_for_horizon_minor !== null && (
                      <>
                        {" "}
                        —{" "}
                        <Money
                          amountMinor={data.sections.fi.required_monthly_for_horizon_minor}
                          currency={data.currency}
                          neutral
                        />
                        /mo would change that
                      </>
                    )}
                </Text>
              </Card>
            )}
          </Grid>

          {data.sections.goals.length > 0 && (
            <Card title="Goals">
              <div style={{ display: "flex", flexDirection: "column", gap: "var(--lf-space-4)" }}>
                {data.sections.goals.map((goal) => (
                  <div key={goal.name}>
                    <Text as="span" style={{ display: "block", marginBottom: "var(--lf-space-1)" }}>
                      {goal.name}
                    </Text>
                    <FigureRow>
                      <Figure label="Saved" value={`${goal.percent}%`} size="inline" />
                      {goal.success_probability !== null && (
                        <Figure
                          label="Likely on current pace"
                          value={`${Math.round(goal.success_probability * 100)}%`}
                          size="inline"
                          certainty="speculative"
                          confidence="A simulation from your current pace and time remaining, not a guarantee."
                        />
                      )}
                    </FigureRow>
                  </div>
                ))}
              </div>
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
