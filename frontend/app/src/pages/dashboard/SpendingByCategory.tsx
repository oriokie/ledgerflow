import { PieChart } from "lucide-react";
import { useState } from "react";
import type { CategoryBreakdownRow } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { Card, EmptyState } from "../../ui";
import { rankedCategories } from "./metrics";

const PREVIEW = 6;

export function SpendingByCategory({
  breakdown,
  currency,
}: {
  breakdown: CategoryBreakdownRow[] | undefined;
  currency: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const ranked = rankedCategories(breakdown);

  if (ranked.length === 0) {
    return (
      <Card accent="spend" title="Where money goes">
        <EmptyState
          icon={PieChart}
          title="No spending yet"
          body="Once you log expenses, your top categories appear here."
        />
      </Card>
    );
  }

  const shown = expanded ? ranked : ranked.slice(0, PREVIEW);

  return (
    <Card accent="spend" title="Where money goes">
      <div className="lf-catbar-list" style={{ marginTop: "var(--lf-space-2)" }}>
        {shown.map((c) => (
          <div key={c.category_id} className="lf-catbar-row">
            <span className="lf-catbar-name">
              <span className="lf-catbar-swatch" style={{ background: `var(--lf-chart-${c.colorIndex})` }} aria-hidden="true" />
              <span>{c.category_name}</span>
            </span>
            <span className="lf-catbar-value">
              {formatAmount(c.amount_minor, currency)}
              <span className="lf-catbar-pct">{Math.round(c.pctOfTotal)}%</span>
            </span>
            <span className="lf-catbar-track">
              <span
                className="lf-catbar-fill"
                style={{ width: `${Math.max(3, c.share * 100)}%`, background: `var(--lf-chart-${c.colorIndex})` }}
              />
            </span>
          </div>
        ))}
      </div>

      {ranked.length > PREVIEW && (
        <button type="button" className="lf-disclosure-toggle" onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Show less" : `Show all ${ranked.length}`}
        </button>
      )}
    </Card>
  );
}
