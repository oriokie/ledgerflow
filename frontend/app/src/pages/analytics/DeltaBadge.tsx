import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import type { Delta } from "./analyticsMath";

/** A small change indicator. `goodWhen` says which direction is favourable for
 * this metric (income up = good; expenses up = bad), which sets the colour.
 *
 * `provisional` drops the colour entirely. A part-month compared against a
 * whole one is not a like-for-like change, and colouring it green or red
 * asserts a judgement the numbers do not support — on the 2nd of the month
 * every expense figure would read as a triumph. The magnitude still shows;
 * only the verdict is withheld.
 */
export function DeltaBadge({
  delta,
  goodWhen = "up",
  provisional = false,
}: {
  delta: Delta;
  goodWhen?: "up" | "down";
  provisional?: boolean;
}) {
  const tone =
    provisional || delta.direction === "flat" ? undefined : delta.direction === goodWhen ? "good" : "bad";
  const Icon = delta.direction === "up" ? ArrowUpRight : delta.direction === "down" ? ArrowDownRight : Minus;
  const pct = Math.abs(delta.pct);
  const pctText = pct >= 1000 ? ">999%" : `${pct.toFixed(0)}%`;
  const context = provisional ? "so far this month vs all of last month" : "vs last month";
  return (
    <span className="lf-delta" data-tone={tone} aria-label={`${delta.direction} ${pctText} ${context}`}>
      <Icon size={13} strokeWidth={2} aria-hidden="true" />
      {pctText}
    </span>
  );
}
