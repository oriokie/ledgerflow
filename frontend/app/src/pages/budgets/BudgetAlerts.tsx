import type { BudgetLineStatus } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { budgetAlerts } from "./budgetMath";

/** Clear, scannable alerts for the categories that need attention. Renders
 * nothing when everything is within budget (the page shows an all-clear note). */
export function BudgetAlerts({ lines, currency }: { lines: BudgetLineStatus[]; currency: string }) {
  const { over, warning } = budgetAlerts(lines);
  if (over.length === 0 && warning.length === 0) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--lf-space-2)", marginBottom: "var(--lf-space-4)" }}>
      {over.length > 0 && (
        <div className="lf-insight lf-insight--attention" role="status">
          <p className="lf-insight-title">
            {over.length} categor{over.length === 1 ? "y is" : "ies are"} over budget
          </p>
          <p className="lf-insight-body">
            {over
              .map((l) => `${l.category_name} (over by ${formatAmount(l.actual_minor - l.effective_limit_minor, currency)})`)
              .join(" · ")}
          </p>
        </div>
      )}
      {warning.length > 0 && (
        <div className="lf-insight lf-insight--soon" role="status">
          <p className="lf-insight-title">
            {warning.length} nearing {warning.length === 1 ? "its" : "their"} limit
          </p>
          <p className="lf-insight-body">
            {warning.map((l) => `${l.category_name} (${Math.round(l.percent_used)}%)`).join(" · ")}
          </p>
        </div>
      )}
    </div>
  );
}
