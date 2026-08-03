import clsx from "clsx";
import type { ReactNode } from "react";

interface MeterProps {
  /** 0–100. Values above 100 clamp visually but flag `over`. */
  value: number;
  /** Renders the over-budget (carmine) treatment. */
  over?: boolean;
  /** Optional label row above the track. */
  label?: ReactNode;
  /** Optional trailing value (e.g. "72%") shown in the label row. */
  caption?: ReactNode;
  /**
   * Accessible name for the progressbar.
   *
   * Falls back to `label` when that's a plain string, which covers most call
   * sites. Required explicitly when `label` is a ReactNode (or absent),
   * because a `role="progressbar"` with no accessible name is a serious WCAG
   * failure — a screen reader announces "40%" with no indication of 40% of
   * what.
   */
  "aria-label"?: string;
  className?: string;
}

/**
 * A progress/usage bar built on `.lf-meter-track` / `.lf-meter-fill`. Used for
 * budget consumption, plan-limit usage, health-score components. `over` flips
 * the fill to the over-budget color.
 */
export function Meter({
  value,
  over,
  label,
  caption,
  "aria-label": ariaLabel,
  className,
}: MeterProps) {
  const pct = Math.max(0, Math.min(100, value));
  // A string label is already the visible name, so reuse it rather than
  // making every call site repeat itself.
  const accessibleName = ariaLabel ?? (typeof label === "string" ? label : undefined);
  return (
    <div className={className}>
      {(label || caption) && (
        <div className="lf-meter-row">
          {label && <span>{label}</span>}
          {caption && <span className="lf-cell-meta">{caption}</span>}
        </div>
      )}
      <div
        className={clsx("lf-meter-track")}
        role="progressbar"
        aria-label={accessibleName}
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        // Announces "72% used" rather than a bare number where a caption
        // gives the figure meaning.
        aria-valuetext={typeof caption === "string" ? caption : undefined}
      >
        <div className={clsx("lf-meter-fill", over && "lf-meter--over")} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
