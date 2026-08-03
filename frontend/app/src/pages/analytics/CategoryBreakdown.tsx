import { formatAmount } from "../../lib/money";
import type { BreakdownRowWithShare } from "./analyticsMath";

/** A ranked, clickable spending-by-category list. Bars are scaled to the
 * largest category so proportions read at a glance; clicking a row drills in. */
export function CategoryBreakdown({
  rows,
  selectedId,
  onSelect,
  currency,
}: {
  rows: BreakdownRowWithShare[];
  selectedId: string | null;
  onSelect: (categoryId: string, categoryName: string) => void;
  currency: string;
}) {
  if (rows.length === 0) {
    return <div className="lf-drill-empty">No activity in this range.</div>;
  }
  const maxShare = Math.max(...rows.map((r) => r.share), 0.0001);

  return (
    <div className="lf-cat-list">
      {rows.map((r) => (
        <button
          key={r.category_id}
          type="button"
          className="lf-cat-row"
          data-selected={r.category_id === selectedId}
          onClick={() => onSelect(r.category_id, r.category_name)}
        >
          <span className="lf-cat-name">{r.category_name}</span>
          <span className="lf-cat-amount">
            {formatAmount(r.amount_minor, currency)} <span className="lf-cat-share">{(r.share * 100).toFixed(0)}%</span>
          </span>
          <span className="lf-cat-bar">
            <span className="lf-cat-bar-fill" style={{ width: `${(r.share / maxShare) * 100}%` }} />
          </span>
        </button>
      ))}
    </div>
  );
}
