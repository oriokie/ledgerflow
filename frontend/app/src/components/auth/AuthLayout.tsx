import type { ReactNode } from "react";
import { AuthHeroArt, type AuthScene } from "./AuthHeroArt";
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
  /** Changes the narrative artwork without changing the form layout. */
  scene?: AuthScene;
  /** Motif for flows that already opt into a named illustration (recover, verify, welcome). */
  illustration?: IllustrationName;
}

/**
 * The auth shell: the form on the left, a soft tinted showcase panel on the
 * right with people-first doodle artwork.
 *
 * The panel disappears below 900px, leaving a focused single-column form with
 * the brand row up top. Every auth screen (login, register, reset, invite,
 * workspace picker, logged-out) renders through this, so the treatment is
 * identical everywhere.
 */
export function AuthLayout({
  children,
  footer,
  maxWidth,
  scene = "signin",
  illustration,
}: AuthLayoutProps) {
  const resolvedIllustration = illustration ?? (scene === "signin" ? "secure" : undefined);
  const panelCopy =
    scene === "signed-out"
      ? {
          eyebrow: "Session complete",
          title: "Your books stay private.",
          body: "Everything is exactly where you left it, ready when you return.",
        }
      : {
          eyebrow: "Clarity, every day",
          title: "Your money makes more sense here.",
          body: "One calm place for balances, plans, goals, and the reasoning behind every number.",
        };

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
        <div className="lf-auth-panel-brand">
          <AuthBrand />
        </div>
        <div className="lf-auth-panel-inner">
          <div className="lf-auth-stage">
            <div className="lf-auth-illus">
              {resolvedIllustration ? (
                <Illustration name={resolvedIllustration} size="panel" style="doodle" />
              ) : (
                <AuthHeroArt scene={scene} />
              )}
            </div>
            <span className="lf-auth-float lf-auth-float--top">Private by design</span>
            <span className="lf-auth-float lf-auth-float--bottom">Always exportable</span>
          </div>

          <div className="lf-auth-panel-copy">
            <p className="lf-auth-panel-eyebrow">{panelCopy.eyebrow}</p>
            <p className="lf-auth-panel-title">{panelCopy.title}</p>
            <p className="lf-auth-panel-body">{panelCopy.body}</p>
          </div>
        </div>
      </aside>
    </div>
  );
}

/** A horizontal "or" separator between sign-in methods. */
export function AuthDivider({ label = "or" }: { label?: string }) {
  return <div className="lf-auth-divider" role="separator">{label}</div>;
}
