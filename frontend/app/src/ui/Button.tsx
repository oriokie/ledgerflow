import clsx from "clsx";
import type { ButtonHTMLAttributes, ReactNode, Ref } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  /** Shows a spinner and disables the button. */
  loading?: boolean;
  /** Full-width block button (e.g. form submit, modal footer). */
  block?: boolean;
  /** Leading icon element (e.g. a lucide icon). */
  icon?: ReactNode;
  /** React 19 passes refs as a normal prop — used for focus management
   * (e.g. moving focus to a confirm button the moment it appears). */
  ref?: Ref<HTMLButtonElement>;
  children?: ReactNode;
}

/**
 * The canonical button. Wraps `.lf-btn` + variant/size modifiers so pages never
 * hand-write `className="lf-btn lf-btn--primary"` again, and get loading state,
 * sizes, and icon slots for free.
 */
export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  block = false,
  icon,
  children,
  className,
  disabled,
  type = "button",
  ref,
  ...rest
}: ButtonProps) {
  return (
    <button
      ref={ref}
      type={type}
      className={clsx(
        "lf-btn",
        `lf-btn--${variant}`,
        size === "sm" && "lf-btn--sm",
        size === "lg" && "lf-btn--lg",
        block && "lf-btn--block",
        loading && "is-loading",
        className,
      )}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {icon && <span className="lf-btn-icon" aria-hidden="true">{icon}</span>}
      {children}
    </button>
  );
}

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Required for accessibility — icon-only buttons need a label. */
  label: string;
  icon: ReactNode;
  variant?: Variant;
  size?: Size;
}

/** Square icon-only button. `label` is mandatory (becomes aria-label + title)
 * so we never ship an unlabeled icon button. */
export function IconButton({
  label,
  icon,
  variant = "ghost",
  size = "md",
  className,
  type = "button",
  ...rest
}: IconButtonProps) {
  return (
    <button
      type={type}
      className={clsx(
        "lf-btn",
        `lf-btn--${variant}`,
        "lf-iconbtn",
        size === "sm" && "lf-btn--sm",
        size === "lg" && "lf-btn--lg",
        className,
      )}
      aria-label={label}
      title={label}
      {...rest}
    >
      {icon}
    </button>
  );
}
