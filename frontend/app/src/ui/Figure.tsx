import clsx from "clsx";
import type { ReactNode } from "react";
import { Money } from "../components/Money";

/**
 * How much the product actually knows about this number.
 *
 * This is the one piece of information a finance UI most often drops, and
 * dropping it is how a dashboard ends up presenting a forecast and a bank
 * balance in identical type. See `docs/redesign/03-design-system.md` §2.5.
 */
export type Certainty = "settled" | "pending" | "projected" | "speculative";

export type FigureSize = "hero" | "primary" | "secondary" | "inline";

/** Reserved for meaning, never decoration — see tokens.css. */
export type FigureTone = "default" | "positive" | "warning" | "critical";

interface FigureBase {
  /** What the number is. Always rendered; a bare number is not a figure. */
  label: ReactNode;
  size?: FigureSize;
  tone?: FigureTone;
  /** A short qualifier under the value — "on Aug 2", "day 2 of 31". */
  hint?: ReactNode;
  /** Change indicator, rendered beside the value. */
  delta?: ReactNode;
  className?: string;
}

/** Money renders through `Money` so the ledger treatment stays in one place. */
interface FigureMoney {
  amountMinor: number;
  currency: string;
  /** Suppress in/out colouring for neutral totals. Sign is never suppressed. */
  neutral?: boolean;
  value?: never;
}

/** Everything that isn't money: "0 of 2", "55%", "1". */
interface FigureValue {
  value: ReactNode;
  amountMinor?: never;
  currency?: never;
  neutral?: never;
}

/**
 * `speculative` requires its caveat, at the type level.
 *
 * The Debt page shipped a confident "100 / Excellent" computed from 45% of the
 * usual inputs, with the caveat 200px away in tertiary grey. Making the
 * confidence statement a required prop is what stops that being expressible:
 * you cannot render a speculative figure without saying why it is speculative.
 */
type FigureCertainty =
  | { certainty?: "settled" | "pending" | "projected"; confidence?: never }
  | { certainty: "speculative"; confidence: string };

export type FigureProps = FigureBase & (FigureMoney | FigureValue) & FigureCertainty;

/**
 * A labelled number.
 *
 * Before this existed, 71 selectors across 13 feature stylesheets implemented
 * this one idea — `.lf-cashflow-stat`, `.lf-goal-summary-stat`,
 * `.lf-debt-metrics`, `.lf-admin-kpi-value`, `.lf-hero-figure` — each with its
 * own type sizes, label casing and alignment. That is why a row of three
 * figures on the Goals page sat on three different baselines.
 *
 * Alignment is structural rather than incidental: label and value rows have
 * fixed line heights per size, so sibling figures line up without the parent
 * needing `subgrid` or every caller remembering to match.
 */
export function Figure(props: FigureProps) {
  const {
    label,
    size = "secondary",
    tone = "default",
    hint,
    delta,
    className,
    certainty = "settled",
  } = props;
  const confidence = "confidence" in props ? props.confidence : undefined;
  const speculative = certainty === "speculative";

  const value =
    "amountMinor" in props && props.amountMinor !== undefined ? (
      <Money
        amountMinor={props.amountMinor}
        currency={props.currency}
        neutral={props.neutral ?? tone === "default"}
        hero={size === "hero"}
      />
    ) : (
      (props as FigureValue).value
    );

  return (
    <div
      className={clsx("lf-figure", className)}
      data-size={size}
      data-tone={tone}
      data-certainty={certainty}
    >
      <span className="lf-figure-label">{label}</span>

      <span className="lf-figure-value">
        {/* Survives a screenshot, a glance, and being quoted out of context. */}
        {speculative && <span aria-hidden="true">~</span>}
        {value}
        {delta && <span className="lf-figure-delta">{delta}</span>}
      </span>

      {speculative && <span className="lf-figure-flag">Provisional</span>}
      {confidence && <span className="lf-figure-confidence">{confidence}</span>}
      {hint && <span className="lf-figure-hint">{hint}</span>}
    </div>
  );
}

/**
 * A row of figures that stay on one grid.
 *
 * Equal columns by default so the labels align left-to-right; `lead` gives the
 * first figure the room a hero number needs while the rest share what's left.
 */
export function FigureRow({
  children,
  lead,
  className,
}: {
  children: ReactNode;
  lead?: boolean;
  className?: string;
}) {
  return (
    <div className={clsx("lf-figure-row", className)} data-lead={lead ? "true" : undefined}>
      {children}
    </div>
  );
}
