import clsx from "clsx";
import type { CSSProperties, ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  /** Optional header rendered above children via CardHeader. */
  title?: ReactNode;
  eyebrow?: ReactNode;
  /** Right-side header slot (badge, menu, action). */
  action?: ReactNode;
  /** Emphasize the card (e.g. current plan) with a colored border. */
  highlight?: boolean;
  /**
   * Visual weight. `primary` is the one card a page leads with — more padding
   * and a fractionally deeper shadow. `quiet` drops elevation for supporting
   * content. Hierarchy through material, never through color.
   */
  prominence?: "default" | "primary" | "quiet";
  /** Lifts on hover and takes a focus ring. Only for cards that DO something. */
  interactive?: boolean;
  /** Separate the header from the body with a rule (use for lists/tables). */
  ruledHeader?: boolean;
  onClick?: () => void;
  className?: string;
  style?: CSSProperties;
}

/**
 * The surface primitive. Pass `title`/`eyebrow`/`action` for the standard
 * header, or omit them and compose freely. Replaces hand-written `.lf-card` +
 * `.lf-card-header` blocks.
 *
 * An `interactive` card that also gets `onClick` renders as a real <button>
 * so keyboard activation and screen-reader semantics come for free.
 */
export function Card({
  children,
  title,
  eyebrow,
  action,
  highlight,
  prominence = "default",
  interactive,
  ruledHeader,
  onClick,
  className,
  style,
}: CardProps) {
  const hasHeader = title || eyebrow || action;
  const clickable = Boolean(onClick);

  const classes = clsx(
    "lf-card",
    prominence === "primary" && "lf-card--primary",
    prominence === "quiet" && "lf-card--quiet",
    (interactive || clickable) && "lf-card--interactive",
    className,
  );

  const inlineStyle: CSSProperties = {
    ...(highlight ? { borderColor: "var(--lf-action-primary)", borderWidth: 2 } : {}),
    ...style,
  };

  const body = (
    <>
      {hasHeader && (
        <CardHeader className={ruledHeader ? "lf-card-header--ruled" : undefined}>
          <div>
            {eyebrow && <p className="lf-eyebrow">{eyebrow}</p>}
            {title && <p className="lf-card-title">{title}</p>}
          </div>
          {action}
        </CardHeader>
      )}
      {children}
    </>
  );

  if (clickable) {
    return (
      <button
        type="button"
        className={classes}
        style={{ ...inlineStyle, textAlign: "start", font: "inherit", width: "100%" }}
        onClick={onClick}
      >
        {body}
      </button>
    );
  }

  return (
    <div className={classes} style={inlineStyle}>
      {body}
    </div>
  );
}

/** Header row inside a card — baseline-aligned title left, action right. */
export function CardHeader({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("lf-card-header", className)}>{children}</div>;
}

type BadgeTone = "success" | "warning" | "danger" | "neutral";

interface BadgeProps {
  children: ReactNode;
  tone?: BadgeTone;
  className?: string;
}

/** Status pill. Tone maps to the semantic status colors. */
export function Badge({ children, tone = "neutral", className }: BadgeProps) {
  return <span className={clsx("lf-badge", `lf-badge--${tone}`, className)}>{children}</span>;
}

interface ChipProps {
  children: ReactNode;
  active?: boolean;
  onClick?: () => void;
  className?: string;
}

/** A compact tag/filter chip. Becomes a button when `onClick` is provided. */
export function Chip({ children, active, onClick, className }: ChipProps) {
  const cls = clsx("lf-chip", active && "lf-chip--active", className);
  if (onClick) {
    return (
      <button type="button" className={cls} onClick={onClick} style={{ cursor: "pointer" }} aria-pressed={active}>
        {children}
      </button>
    );
  }
  return <span className={cls}>{children}</span>;
}
