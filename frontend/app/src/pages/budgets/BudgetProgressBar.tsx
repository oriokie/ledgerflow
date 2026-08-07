import clsx from "clsx";
import { Meter } from "../../ui";
import type { LineState } from "./budgetMath";

/**
 * A budget consumption bar built on the shared `Meter` primitive. The fill
 * colour reflects the state (under/near/over) via a `.lf-budget-meter--*`
 * modifier class — the traffic-light palette is specific to budgets, so it's
 * layered on in budgets.css rather than added to Meter's own API — and
 * Meter's `marker` prop draws the "how far through the period are we" pace
 * tick, so the user can see at a glance whether spending is outrunning the
 * clock.
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
  const showPace = pacePercent !== undefined && pacePercent > 0 && pacePercent < 100;
  return (
    <Meter
      value={percentUsed}
      marker={showPace ? pacePercent : undefined}
      aria-label={ariaLabel}
      className={clsx("lf-budget-meter", `lf-budget-meter--${state}`, size === "lg" && "lf-budget-meter--lg")}
    />
  );
}
