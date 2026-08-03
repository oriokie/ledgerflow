import clsx from "clsx";
import type { CSSProperties, ReactNode } from "react";

type BannerTone = "danger" | "success" | "warning" | "info";

interface BannerProps {
  children: ReactNode;
  tone?: BannerTone;
  /** Optional dismiss handler — renders a close affordance. */
  onDismiss?: () => void;
  className?: string;
}

const BANNER_STYLE: Record<BannerTone, CSSProperties> = {
  danger: {},
  success: {
    borderColor: "var(--lf-status-success)",
    background: "var(--lf-status-success-bg)",
    color: "var(--lf-status-success-text)",
  },
  warning: {
    borderColor: "var(--lf-status-warning)",
    background: "var(--lf-status-warning-bg)",
    color: "var(--lf-status-warning-text)",
  },
  info: {
    borderColor: "var(--lf-border-default)",
    background: "var(--lf-bg-sunken)",
    color: "var(--lf-text-primary)",
  },
};

/**
 * An inline alert bar. Default tone is danger (matching the base `.lf-banner`
 * styling); other tones recolor to the semantic status palette. Use `role`
 * "alert" for errors and "status" for confirmations.
 */
export function Banner({ children, tone = "danger", onDismiss, className }: BannerProps) {
  return (
    <div
      className={clsx("lf-banner", className)}
      role={tone === "danger" ? "alert" : "status"}
      style={tone === "danger" ? undefined : BANNER_STYLE[tone]}
    >
      {children}
      {onDismiss && (
        <button
          type="button"
          className="lf-btn lf-btn--ghost lf-btn--sm"
          onClick={onDismiss}
          style={{ marginLeft: "auto" }}
        >
          Dismiss
        </button>
      )}
    </div>
  );
}

interface SpinnerProps {
  size?: "sm" | "md" | "lg";
  className?: string;
  /** Accessible label announced to screen readers. */
  label?: string;
}

/** A spinning loading indicator. Inherits `currentColor`, so it matches
 * whatever text color surrounds it. */
export function Spinner({ size = "md", className, label = "Loading" }: SpinnerProps) {
  return (
    <span
      className={clsx("lf-spinner", size === "sm" && "lf-spinner--sm", size === "lg" && "lf-spinner--lg", className)}
      role="status"
      aria-label={label}
    />
  );
}

/** A single shimmer line placeholder. Width/height are style-controlled. */
export function Skeleton({ width, height, className, style }: { width?: string | number; height?: string | number; className?: string; style?: CSSProperties }) {
  return (
    <div
      className={clsx("lf-skeleton", "lf-skeleton-line", className)}
      style={{ width, height, ...style }}
      aria-hidden="true"
    />
  );
}

/** A card-shaped loading placeholder: a few shimmer lines inside a card. */
export function SkeletonCard({ lines = 2 }: { lines?: number }) {
  return (
    <div className="lf-card" aria-hidden="true">
      <Skeleton width="40%" />
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} width={`${70 - i * 12}%`} height={i === 0 ? 28 : undefined} />
      ))}
    </div>
  );
}

/** Centered spinner for full-section loading states. */
export function LoadingBlock({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="lf-center" style={{ padding: "var(--lf-space-12)", color: "var(--lf-text-tertiary)" }}>
      <div className="lf-inline lf-gap-2">
        <Spinner />
        <span className="lf-text-sm">{label}</span>
      </div>
    </div>
  );
}
