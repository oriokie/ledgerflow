import type { LineState } from "./budgetMath";

/**
 * A budget consumption bar. The fill colour reflects the state (under/near/over)
 * and an optional pace marker shows how far through the period we are — so the
 * user can see at a glance whether spending is outrunning the clock.
 */
export function BudgetProgressBar({
  percentUsed,
  state,
  pacePercent,
  size = "md",
  ariaLabel,
}: {
  percentUsed: number;
  state: LineState;
  pacePercent?: number;
  size?: "md" | "lg";
  ariaLabel?: string;
}) {
  const pct = Math.max(0, Math.min(100, percentUsed));
  const showPace = pacePercent !== undefined && pacePercent > 0 && pacePercent < 100;
  return (
    <div
      className={`lf-budget-track${size === "lg" ? " lf-budget-track--lg" : ""}`}
      role="progressbar"
      aria-valuenow={Math.round(percentUsed)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={ariaLabel}
    >
      <div className="lf-budget-fill" data-state={state} style={{ width: `${pct}%` }} />
      {showPace && (
        <div
          className="lf-budget-pace"
          style={{ left: `${Math.min(100, Math.max(0, pacePercent))}%` }}
          title={`Period ${Math.round(pacePercent)}% elapsed`}
        />
      )}
    </div>
  );
}
