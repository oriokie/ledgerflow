import clsx from "clsx";
import type { CSSProperties, ReactNode } from "react";

interface HeadingProps {
  children: ReactNode;
  /** Visual + semantic level. h1 = page title, h2 = section, h3 = card. */
  level?: 1 | 2 | 3;
  className?: string;
  style?: CSSProperties;
}

/** Semantic heading with the display font + tokened size. Prefer this over
 * bare <h1> so heading scale stays consistent everywhere.
 *
 * Sizing lives in CSS (`.lf-heading--{level}`) rather than inline styles, so
 * contextual rules — a page title inside `.lf-page-header` stepping up to the
 * display size — can still win. Inline styles would have blocked them. */
export function Heading({ children, level = 1, className, style }: HeadingProps) {
  const Tag = (`h${level}`) as "h1" | "h2" | "h3";
  return (
    <Tag className={clsx("lf-heading", `lf-heading--${level}`, className)} style={style}>
      {children}
    </Tag>
  );
}

type TextTone = "primary" | "secondary" | "tertiary";
type TextSize = "xs" | "sm" | "base" | "md";

interface TextProps {
  children: ReactNode;
  tone?: TextTone;
  size?: TextSize;
  weight?: "regular" | "medium" | "semibold";
  as?: "p" | "span" | "div";
  className?: string;
  style?: CSSProperties;
}

const WEIGHT: Record<string, number> = { regular: 400, medium: 500, semibold: 600 };

/** Body text with tone + size tokens. Replaces inline `color`/`font-size`. */
export function Text({
  children,
  tone = "primary",
  size = "base",
  weight = "regular",
  as: Tag = "p",
  className,
  style,
}: TextProps) {
  return (
    <Tag
      className={clsx(`lf-text-${tone}`, size !== "base" && `lf-text-${size}`, className)}
      style={{ margin: 0, fontWeight: WEIGHT[weight], ...style }}
    >
      {children}
    </Tag>
  );
}

/** The small uppercase kicker above titles (e.g. "12 accounts"). */
export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={clsx("lf-eyebrow", className)}>{children}</p>;
}

interface PageHeaderProps {
  title: ReactNode;
  eyebrow?: ReactNode;
  /** One line explaining what this page is for. */
  description?: ReactNode;
  /** Right-aligned actions (buttons). */
  actions?: ReactNode;
}

/** The standard page header: eyebrow + title on the left, actions on the right.
 * Formalizes the `.lf-page-header` markup repeated on every page. The title
 * renders one full scale step above section headings — see `.lf-page-header h1`
 * in components.css — so page-level hierarchy is never ambiguous. */
export function PageHeader({ title, eyebrow, description, actions }: PageHeaderProps) {
  return (
    <div className="lf-page-header">
      <div>
        {eyebrow && <Eyebrow>{eyebrow}</Eyebrow>}
        <Heading level={1}>{title}</Heading>
        {description && <p className="lf-page-header-desc">{description}</p>}
      </div>
      {actions && <div className="lf-page-header-actions">{actions}</div>}
    </div>
  );
}
