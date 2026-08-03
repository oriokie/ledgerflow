import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { AuthBrand } from "../components/auth/AuthLayout";
import { Illustration, type IllustrationName } from "../ui/illustration";

/**
 * The full-page states: not found, server error, maintenance, offline.
 *
 * One component rather than four, because these pages differ only in what they
 * say. Four separate ones would drift — and the drift always goes the same way,
 * with the rarely-seen page ending up as the one that looks unfinished.
 *
 * Each says three things in this order: what happened, whether it is the user's
 * problem, and what to do next. The illustration is the smallest part of that
 * and is `aria-hidden` — it sets the tone, the words do the work.
 */
export function StatusPage({
  illustration,
  code,
  title,
  body,
  actions,
}: {
  illustration: IllustrationName;
  /** Shown small, above the title. Absent for states without an HTTP status. */
  code?: string;
  title: string;
  body: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="lf-status-page">
      <header className="lf-status-header">
        <Link to="/" aria-label="LedgerFlow home">
          <AuthBrand />
        </Link>
      </header>

      <main className="lf-status-body" id="main">
        <Illustration name={illustration} size="panel" />
        {code && <p className="lf-status-code">{code}</p>}
        <h1>{title}</h1>
        <div className="lf-status-text">{body}</div>
        {actions && <div className="lf-status-actions">{actions}</div>}
      </main>
    </div>
  );
}

export function NotFoundPage() {
  return (
    <StatusPage
      illustration="not-found"
      code="404"
      title="That page isn't here"
      body={
        <p>
          The link may be out of date, or the page may have moved. Nothing has happened to your
          data.
        </p>
      }
      actions={
        <>
          <Link className="lf-btn lf-btn--primary" to="/">
            Go to your overview
          </Link>
          <Link className="lf-btn lf-btn--secondary" to="/activity">
            Open your activity
          </Link>
        </>
      }
    />
  );
}

export function ServerErrorPage({ onRetry }: { onRetry?: () => void }) {
  return (
    <StatusPage
      illustration="error"
      code="500"
      title="Something went wrong at our end"
      body={
        <p>
          This one is ours, not yours. Your data is unaffected — nothing is written unless it
          succeeds. Trying again often works, because most of these are momentary.
        </p>
      }
      actions={
        <>
          {onRetry ? (
            <button type="button" className="lf-btn lf-btn--primary" onClick={onRetry}>
              Try again
            </button>
          ) : (
            <Link className="lf-btn lf-btn--primary" to="/">
              Go to your overview
            </Link>
          )}
        </>
      }
    />
  );
}

export function MaintenancePage() {
  return (
    <StatusPage
      illustration="maintenance"
      title="Down for scheduled maintenance"
      body={
        <p>
          We're making a planned change and will be back shortly. Nothing is being altered in your
          books while this is happening.
        </p>
      }
    />
  );
}

export function OfflinePage() {
  return (
    <StatusPage
      illustration="offline"
      title="You're offline"
      body={
        <p>
          LedgerFlow can't reach the server. Anything you recorded while offline is queued on this
          device and will send once the connection returns.
        </p>
      }
      actions={
        <button
          type="button"
          className="lf-btn lf-btn--primary"
          onClick={() => window.location.reload()}
        >
          Try again
        </button>
      }
    />
  );
}
