import clsx from "clsx";
import type { CSSProperties, ElementType, ReactNode } from "react";

type Gap = 1 | 2 | 3 | 4 | 5 | 6 | 8;

interface StackProps {
  children: ReactNode;
  gap?: Gap;
  align?: "start" | "center" | "end" | "stretch";
  className?: string;
  as?: ElementType;
  style?: CSSProperties;
}

const ALIGN: Record<string, string> = {
  start: "flex-start",
  center: "center",
  end: "flex-end",
  stretch: "stretch",
};

/** Vertical flow with token-based spacing. Replaces ad-hoc `flex-direction:
 * column` + margins scattered across pages. */
export function Stack({ children, gap = 4, align, className, as: Tag = "div", style }: StackProps) {
  return (
    <Tag
      className={clsx("lf-stack", `lf-gap-${gap}`, className)}
      style={{ ...(align ? { alignItems: ALIGN[align] } : {}), ...style }}
    >
      {children}
    </Tag>
  );
}

interface InlineProps {
  children: ReactNode;
  gap?: Gap;
  wrap?: boolean;
  justify?: "start" | "center" | "end" | "between";
  align?: "start" | "center" | "end";
  className?: string;
  as?: ElementType;
  style?: CSSProperties;
}

/** Horizontal row with alignment + wrapping. Replaces the countless
 * `display:flex; gap:...; align-items:center` inline styles. */
export function Inline({
  children,
  gap = 2,
  wrap = true,
  justify,
  align = "center",
  className,
  as: Tag = "div",
  style,
}: InlineProps) {
  return (
    <Tag
      className={clsx(
        "lf-inline",
        `lf-gap-${gap}`,
        !wrap && "lf-inline--nowrap",
        justify === "between" && "lf-inline--between",
        justify === "end" && "lf-inline--end",
        justify === "center" && "lf-inline--center",
        align === "start" && "lf-inline--start-top",
        className,
      )}
      style={style}
    >
      {children}
    </Tag>
  );
}

interface GridProps {
  children: ReactNode;
  cols?: 2 | 3 | 4 | "auto";
  gap?: Gap;
  className?: string;
  style?: CSSProperties;
}

/** Responsive grid. Collapses to a single column under 720px (handled in CSS). */
export function Grid({ children, cols = "auto", gap = 4, className, style }: GridProps) {
  return (
    <div className={clsx("lf-grid", `lf-grid--${cols}`, `lf-gap-${gap}`, className)} style={style}>
      {children}
    </div>
  );
}

/** Horizontal rule using the subtle border token. */
export function Divider({ className, style }: { className?: string; style?: CSSProperties }) {
  return <hr className={clsx("lf-divider", className)} style={style} />;
}

/** A flexible spacer that pushes siblings apart inside an Inline/flex row. */
export function Spacer() {
  return <div style={{ flex: 1 }} aria-hidden="true" />;
}
