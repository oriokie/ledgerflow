import type { ReactNode } from "react";
import { Heading, Text } from "../../ui";
import { Illustration, type IllustrationName } from "../../ui/illustration";
import { AuthProductShot } from "./AuthProductShot";

export type AuthScene =
  | "signin"
  | "register"
  | "recover"
  | "welcome"
  | "invite"
  | "signed-out"
  | "oauth";

const PANEL: Record<
  AuthScene,
  {
    eyebrow: string;
    title: string;
    body: string;
    floats: [string, string];
    illustration?: IllustrationName;
  }
> = {
  signin: {
    eyebrow: "The books, open",
    title: "See what’s settled. See what’s next.",
    body: "One calm place for balances, plans, and the reasoning behind every figure — known on the left, projected on the right.",
    floats: ["Known vs projected", "Always exportable"],
  },
  register: {
    eyebrow: "Seven days, no card",
    title: "Open the books. Keep them.",
    body: "Start with a clear picture of what you have, what you owe, and what comes next.",
    floats: ["Trial, not a trap", "Export anytime"],
  },
  recover: {
    eyebrow: "A quiet reset",
    title: "We'll get you back in.",
    body: "A short-lived link, then a new password. Nothing in your books changes.",
    floats: ["Encrypted in transit", "You stay in control"],
    illustration: "recover",
  },
  welcome: {
    eyebrow: "Your workspace",
    title: "Name the set of books.",
    body: "A workspace is one ledger — personal, a household, or a client you advise.",
    floats: ["Switch anytime", "Roles stay explicit"],
    illustration: "welcome",
  },
  invite: {
    eyebrow: "A shared ledger",
    title: "You've been asked to join.",
    body: "See the workspace first. Accept when the role and the people look right.",
    floats: ["Clear roles", "You choose when"],
    illustration: "verify",
  },
  "signed-out": {
    eyebrow: "Nothing moved",
    title: "Your books stay private.",
    body: "The session is closed. The ledger is exactly as you left it.",
    floats: ["Session closed", "Nothing moved"],
  },
  oauth: {
    eyebrow: "Almost there",
    title: "Finishing the handshake.",
    body: "Completing sign-in with your provider. This only takes a moment.",
    floats: ["Secure redirect", "No password stored"],
    illustration: "secure",
  },
};

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
  /** Changes the narrative artwork and panel copy without changing the form layout. */
  scene?: AuthScene;
  /** Motif for flows that already opt into a named illustration (recover, verify, welcome). */
  illustration?: IllustrationName;
}

interface AuthPageHeaderProps {
  eyebrow?: string;
  title: ReactNode;
  children?: ReactNode;
}

/** Shared editorial heading for every auth form: kicker, display title, lead. */
export function AuthPageHeader({ eyebrow, title, children }: AuthPageHeaderProps) {
  return (
    <div className="lf-auth-heading">
      {eyebrow ? <p className="lf-auth-kicker">{eyebrow}</p> : null}
      <Heading level={1} className="lf-auth-title">
        {title}
      </Heading>
      {children ? (
        <Text size="sm" tone="secondary" className="lf-auth-lead">
          {children}
        </Text>
      ) : null}
    </div>
  );
}

/**
 * Split auth shell: the form first in the DOM (and on the left), a product
 * panel on the right. Sign-in / register / signed-out show the Overview
 * capture; recover / invite / welcome keep a named illustration.
 *
 * The panel is decorative (`aria-hidden`). Below the laptop breakpoint it
 * disappears and the form stands alone with the brand.
 */
export function AuthLayout({
  children,
  footer,
  maxWidth,
  scene = "signin",
  illustration,
}: AuthLayoutProps) {
  const copy = PANEL[scene];
  const resolvedIllustration = illustration ?? copy.illustration;
  const productShot = !resolvedIllustration;

  return (
    <div className="lf-auth-shell" data-scene={scene}>
      <main className="lf-auth-main">
        <div className="lf-auth-card" style={maxWidth ? { maxWidth } : undefined}>
          <div className="lf-auth-brand-slot">
            <AuthBrand />
          </div>
          <div className="lf-auth-form-card">{children}</div>
          {footer && (
            <p className="lf-auth-footer lf-text-secondary lf-text-sm">
              {footer}
            </p>
          )}
        </div>
      </main>

      <aside className="lf-auth-panel" aria-hidden="true">
        <div className="lf-auth-panel-inner">
          <div className={`lf-auth-stage${productShot ? " lf-auth-stage--product" : ""}`}>
            <div className="lf-auth-illus" data-style={productShot ? "product" : "doodle"}>
              {resolvedIllustration ? (
                <Illustration name={resolvedIllustration} size="panel" style="doodle" />
              ) : (
                <AuthProductShot dimmed={scene === "signed-out"} />
              )}
            </div>
            <span className="lf-auth-float lf-auth-float--top">{copy.floats[0]}</span>
            <span className="lf-auth-float lf-auth-float--bottom">{copy.floats[1]}</span>
          </div>

          <div className="lf-auth-panel-copy">
            <p className="lf-auth-panel-eyebrow">{copy.eyebrow}</p>
            <p className="lf-auth-panel-title">{copy.title}</p>
            <p className="lf-auth-panel-body">{copy.body}</p>
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
