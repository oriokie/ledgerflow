import type { ReactNode } from "react";
import { QuoteRotator } from "./QuoteRotator";
import { Figure } from "../../ui";
import { Illustration } from "../../ui/illustration";

/** The LedgerFlow mark used across the auth surface. */
export function AuthBrand({ inverted = false }: { inverted?: boolean }) {
  return (
    <div className={`lf-auth-brand${inverted ? " lf-auth-brand--inverted" : ""}`}>
      <span className="lf-auth-brand-mark" aria-hidden="true">
        <svg width="18" height="18" viewBox="0 0 20 20" fill="none">
          <rect x="2" y="3" width="16" height="14" rx="3" stroke="currentColor" strokeWidth="1.8" />
          <path d="M6 8h8M6 12h5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      </span>
      LedgerFlow
    </div>
  );
}

interface AuthLayoutProps {
  children: ReactNode;
  /** Text/links shown centered beneath the card (e.g. "New here? Create an account"). */
  footer?: ReactNode;
  /** Widen the card for content-heavy screens like the workspace picker. */
  maxWidth?: number;
}

/**
 * The auth shell, redesigned as a premium split screen:
 *  - Left: a dark brand panel with ambient gradient light and a rotating famous
 *    quote on financial management — the moment of calm before the numbers.
 *  - Right: the form on a clean surface.
 * The panel disappears below 900px, leaving a focused single-column form with
 * the brand row up top. Every auth screen (login, register, reset, invite,
 * workspace picker, logged-out) renders through this, so the treatment is
 * identical everywhere.
 */
export function AuthLayout({ children, footer, maxWidth }: AuthLayoutProps) {
  return (
    <div className="lf-auth-shell">
      <aside className="lf-auth-panel" aria-hidden="true">
        <div className="lf-auth-panel-glow" />
        <div className="lf-auth-panel-grid" />
        <div className="lf-auth-panel-inner">
          <AuthBrand inverted />
          {/* The panel is already `aria-hidden`; the illustration sets tone for
              a screen whose entire job is to feel safe to type a password into.
              It sits above the quote so the eye lands on it first and the words
              read as the caption. */}
          <Illustration name="secure" size="panel" className="lf-auth-illus" />
          <QuoteRotator />
          {/* The product's signature where a generic tagline used to be: a
              settled figure and a projected one, drawn by the same component
              the app uses. Clarity shown, not claimed. Decorative — the whole
              panel is aria-hidden. */}
          <div className="lf-auth-specimen">
            <Figure label="Settled" amountMinor={4228381} currency="KES" neutral certainty="settled" size="inline" />
            <Figure label="Projected" amountMinor={540000} currency="KES" neutral certainty="projected" size="inline" />
            <p className="lf-auth-panel-tagline">A settled balance and a projection never look the same.</p>
          </div>
        </div>
      </aside>

      <main className="lf-auth-main">
        <div className="lf-auth-card" style={maxWidth ? { maxWidth } : undefined}>
          <div className="lf-auth-mobile-brand">
            <AuthBrand />
          </div>
          <div className="lf-card lf-auth-form-card">{children}</div>
          {footer && (
            <p
              className="lf-text-secondary lf-text-sm"
              style={{ marginTop: "var(--lf-space-4)", textAlign: "center" }}
            >
              {footer}
            </p>
          )}
        </div>
      </main>
    </div>
  );
}

/** A horizontal "or" separator between sign-in methods. */
export function AuthDivider({ label = "or" }: { label?: string }) {
  return <div className="lf-auth-divider" role="separator">{label}</div>;
}
