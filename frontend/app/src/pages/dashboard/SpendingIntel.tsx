import { useState } from "react";
import { Link } from "react-router-dom";
import type { CategoryBreakdownRow, SpendingTrendPoint } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { Illustration } from "../../ui/illustration";
import { percentChange, rankedCategories } from "./metrics";

const PREVIEW = 5;

export function SpendingIntel({
  breakdown,
  trend,
  currency,
}: {
  breakdown: CategoryBreakdownRow[] | undefined;
  trend: SpendingTrendPoint[] | undefined;
  currency: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const ranked = rankedCategories(breakdown);
  const points = trend ?? [];
  const spendDelta =
    points.length >= 2
      ? percentChange(points[points.length - 1].expense_minor, points[points.length - 2].expense_minor)
      : null;

  if (ranked.length === 0) {
    return (
      <section className="lf-cmd-panel" aria-labelledby="lf-spend-title">
        <header className="lf-cmd-panel-head">
          <h2 id="lf-spend-title">Spending intelligence</h2>
        </header>
        <div className="lf-cmd-quiet">
          <Illustration name="no-data" size="spot" />
          <p>Log expenses to see where money concentrates and how behavior shifts.</p>
          <Link className="lf-btn lf-btn--secondary lf-btn--sm" to="/transactions?add=1">
            Log expense
          </Link>
        </div>
      </section>
    );
  }

  const shown = expanded ? ranked : ranked.slice(0, PREVIEW);
  const top = ranked[0];

  return (
    <section className="lf-cmd-panel" aria-labelledby="lf-spend-title">
      <header className="lf-cmd-panel-head">
        <div>
          <h2 id="lf-spend-title">Spending intelligence</h2>
          <p className="lf-cmd-panel-sub">
            {top.category_name} leads at {Math.round(top.pctOfTotal)}%
            {spendDelta != null
              ? ` · total spend ${spendDelta > 0 ? "up" : "down"} ${Math.abs(spendDelta).toFixed(0)}% vs last month`
              : ""}
          </p>
        </div>
        <Link className="lf-section-link" to="/insights?tab=trends">
          Drill down
        </Link>
      </header>

      <div className="lf-catbar-list">
        {shown.map((c) => (
          <div key={c.category_id} className="lf-catbar-row">
            <span className="lf-catbar-name">
              <span
                className="lf-catbar-swatch"
                style={{ background: `var(--lf-chart-${c.colorIndex})` }}
                aria-hidden="true"
              />
              <span>{c.category_name}</span>
            </span>
            <span className="lf-catbar-value">
              {formatAmount(c.amount_minor, currency)}
              <span className="lf-catbar-pct">{Math.round(c.pctOfTotal)}%</span>
            </span>
            <span className="lf-catbar-track">
              <span
                className="lf-catbar-fill"
                style={{
                  width: `${Math.max(3, c.share * 100)}%`,
                  background: `var(--lf-chart-${c.colorIndex})`,
                }}
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
    </section>
  );
}
