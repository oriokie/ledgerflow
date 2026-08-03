import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAccounts, useCategoryBreakdown } from "../hooks/useFinance";
import { useSpendingTrend } from "../hooks/useIntelligence";
import { Card, PageHeader, SegmentedControl, SkeletonCard, Text } from "../ui";
import { CashFlowChart, CashflowStatement, CategoryBreakdown, CategoryDrilldown, ComparisonCards } from "./analytics";
import { breakdownWithShare, comparisonFromTrend, rangeForMonths, topN } from "./analytics/analyticsMath";

const RANGES = [
  { value: "3", label: "3M" },
  { value: "6", label: "6M" },
  { value: "12", label: "12M" },
];

/** `embedded` renders this page as a tab panel inside a hub (`/plan`,
 * `/insights`). The hub owns the <h1>, so the page must not render its own
 * PageHeader — two page titles on one route is a broken heading outline. */
export function AnalyticsPage({ embedded }: { embedded?: boolean } = {}) {
  const navigate = useNavigate();
  const [monthsStr, setMonthsStr] = useState("6");
  const [type, setType] = useState<"expense" | "income">("expense");
  const [selected, setSelected] = useState<{ id: string; name: string } | null>(null);
  const months = Number(monthsStr);

  const { data: accounts } = useAccounts();
  const { data: trend, isLoading: trendLoading } = useSpendingTrend(months);
  const { start, end } = useMemo(() => rangeForMonths(months), [months]);
  const { data: breakdown } = useCategoryBreakdown(start, end, type);

  const currency = accounts?.[0]?.currency ?? "USD";
  const comparison = comparisonFromTrend(trend);
  const rows = topN(breakdownWithShare(breakdown), 8);

  return (
    <>
      {!embedded && <PageHeader eyebrow="Trends & comparisons" title="Analytics" />}

      <div className="lf-analytics-toolbar">
        <Text tone="secondary" size="sm">
          Last {months} months
        </Text>
        <SegmentedControl legend="Time range" value={monthsStr} onChange={setMonthsStr} options={RANGES} />
      </div>

      <div className="lf-dash-section" style={{ display: "flex", flexDirection: "column", gap: "var(--lf-space-4)" }}>
        {trendLoading && <SkeletonCard />}

        {comparison ? (
          <Card eyebrow="This month vs last">
            <ComparisonCards comparison={comparison} currency={currency} />
          </Card>
        ) : !trendLoading ? (
          <Card>
            <Text tone="secondary">Not enough history yet to compare months — check back after a few weeks of activity.</Text>
          </Card>
        ) : null}

        {/* Was titled "Cash flow", which is also a top-level destination —
            two different things under one name. The chart is a month-by-month
            comparison of what came in against what went out; /cashflow is a
            forward projection of the balance. Naming this one after what it
            actually plots leaves "Cash flow" meaning exactly one thing. */}
        <Card title="Income vs expenses" eyebrow={`Last ${months} months`}>
          {trend && trend.length > 0 ? (
            <CashFlowChart trend={trend} currency={currency} />
          ) : (
            <div className="lf-drill-empty">No cash-flow data in this range.</div>
          )}
        </Card>

        <div className="lf-analytics-split">
          <Card
            title={type === "expense" ? "Spending by category" : "Income by category"}
            action={
              <SegmentedControl
                legend="Type"
                value={type}
                onChange={(v) => {
                  setType(v);
                  setSelected(null);
                }}
                options={[
                  { value: "expense", label: "Spending" },
                  { value: "income", label: "Income" },
                ]}
              />
            }
          >
            <CategoryBreakdown
              rows={rows}
              selectedId={selected?.id ?? null}
              onSelect={(id, name) => setSelected({ id, name })}
              currency={currency}
            />
          </Card>

          <Card title="Category trend">
            <CategoryDrilldown
              categoryId={selected?.id ?? null}
              categoryName={selected?.name ?? null}
              months={months}
              type={type}
              currency={currency}
              onViewTransactions={(id) => navigate(`/transactions?category=${id}`)}
            />
          </Card>
        </div>
      </div>

      <div style={{ marginTop: "var(--lf-space-4)" }}>
        <CashflowStatement />
      </div>
    </>
  );
}
