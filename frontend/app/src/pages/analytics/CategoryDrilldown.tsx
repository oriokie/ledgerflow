import { format } from "date-fns";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useCategoryTrend } from "../../hooks/useFinance";
import { formatAmount, minorToMajor } from "../../lib/money";
import { Button, Skeleton, Text } from "../../ui";
import { CHART_TICK_FONT_PX } from "../dashboard/chartTheme";

const monthLabel = (iso: string) => format(new Date(`${iso}T00:00:00`), "MMM");

/** The drill-down: a chosen category's month-by-month trend, plus its average
 * and a jump into the underlying transactions. */
export function CategoryDrilldown({
  categoryId,
  categoryName,
  months,
  type,
  currency,
  onViewTransactions,
}: {
  categoryId: string | null;
  categoryName: string | null;
  months: number;
  type: "income" | "expense";
  currency: string;
  onViewTransactions: (categoryId: string) => void;
}) {
  const { data, isLoading } = useCategoryTrend(categoryId ?? undefined, months, type);

  if (!categoryId) {
    return <div className="lf-drill-empty">Select a category to see how it's trended over time.</div>;
  }
  if (isLoading) return <Skeleton width="70%" />;

  const points = data ?? [];
  const total = points.reduce((s, p) => s + p.amount_minor, 0);
  const avg = points.length ? Math.round(total / points.length) : 0;
  const chart = points.map((p) => ({ label: monthLabel(p.period_start), amount: minorToMajor(p.amount_minor) }));

  return (
    <div>
      <div className="lf-drill-head">
        <div>
          <div style={{ fontWeight: "var(--lf-weight-semibold)", color: "var(--lf-text-primary)" }}>{categoryName}</div>
          <Text tone="tertiary" size="sm">
            Averaging {formatAmount(avg, currency)}/mo over {months} months
          </Text>
        </div>
        <Button variant="ghost" size="sm" onClick={() => onViewTransactions(categoryId)}>
          View transactions
        </Button>
      </div>
      <div className="lf-chart-container">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chart} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="lf-drill-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--lf-chart-1)" stopOpacity={0.25} />
                <stop offset="100%" stopColor="var(--lf-chart-1)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke="var(--lf-border-subtle)" />
            <XAxis dataKey="label" stroke="var(--lf-text-tertiary)" fontSize={CHART_TICK_FONT_PX} tickLine={false} axisLine={false} />
            <YAxis hide />
            <Tooltip
              formatter={(v) => formatAmount(Math.round(Number(v) * 100), currency)}
              contentStyle={{ borderRadius: 8, border: "1px solid var(--lf-border-subtle)", fontSize: "var(--lf-text-xs)" }}
            />
            <Area dataKey="amount" name={categoryName ?? ""} stroke="var(--lf-chart-1)" strokeWidth={2} fill="url(#lf-drill-fill)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
