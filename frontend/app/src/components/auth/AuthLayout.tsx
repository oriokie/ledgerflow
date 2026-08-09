import type { ReactNode } from "react";
import { QuoteRotator } from "./QuoteRotator";
import { Figure } from "../../ui";
import { Illustration, type IllustrationName } from "../../ui/illustration";

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
  /** Which motif the showcase panel renders. Defaults to "secure" so every
   * existing call site is unchanged until it opts into something more
   * specific — e.g. "recover" for password reset, "verify" for invite flows. */
  illustration?: IllustrationName;
}

/**
 * The auth shell: the form on the left, a soft tinted showcase panel on the
 * right.
 *
 * Built to a supplied reference layout — form first in the reading order,
 * pill-shaped fields, a full-width dark primary, icon-only round social
 * buttons, and beside it an inset rounded panel holding flat vector artwork, a
 * floating figure card and position dots under a headline.
 *
 * Two deliberate departures from the reference. The artwork is LedgerFlow's
 * own illustration system rather than a copy of someone else's drawing, and
 * the floating card shows a real settled-vs-projected pair drawn by the same
 * component the app uses — the product's actual signature, not a stand-in.
 *
 * The panel disappears below 900px, leaving a focused single-column form with
 * the brand row up top. Every auth screen (login, register, reset, invite,
 * workspace picker, logged-out) renders through this, so the treatment is
 * identical everywhere.
 */
export function AuthLayout({ children, footer, maxWidth, illustration = "secure" }: AuthLayoutProps) {
  return (
    <div className="lf-auth-shell">
      <main className="lf-auth-main">
        <div className="lf-auth-card" style={maxWidth ? { maxWidth } : undefined}>
          <div className="lf-auth-mobile-brand">
            <AuthBrand />
          </div>
          <div className="lf-auth-form-card">{children}</div>
          {footer && (
            <p
              className="lf-text-secondary lf-text-sm"
              style={{ marginTop: "var(--lf-space-5)", textAlign: "center" }}
            >
              {footer}
            </p>
          )}
        </div>
      </main>

      {/* The showcase. Entirely decorative, so `aria-hidden` — a screen reader
          reaching the login form should meet the form, not a tour of it. */}
      <aside className="lf-auth-panel" aria-hidden="true">
        <div className="lf-auth-panel-inner">
          <div className="lf-auth-stage">
            <Illustration name={illustration} size="panel" className="lf-auth-illus" />

            {/* The floating card in the reference is a task with a progress
                ring. Here it is the product's actual signature: a settled
                figure and a projected one, drawn by the same component the app
                uses, so the thing being shown off is the real thing. */}
            <div className="lf-auth-specimen">
              <Figure
                label="Settled"
                amountMinor={4228381}
                currency="KES"
                neutral
                certainty="settled"
                size="inline"
              />
              <Figure
                label="Projected"
                amountMinor={540000}
                currency="KES"
                neutral
                certainty="projected"
                size="inline"
              />
            </div>
          </div>

          <QuoteRotator />
        </div>
      </aside>
    </div>
  );
}

/** A horizontal "or" separator between sign-in methods. */
export function AuthDivider({ label = "or" }: { label?: string }) {
  return <div className="lf-auth-divider" role="separator">{label}</div>;
}
