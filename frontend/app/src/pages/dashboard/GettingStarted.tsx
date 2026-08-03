import { ArrowRight, Check, X } from "lucide-react";
import { Link } from "react-router-dom";
import { buildSteps, type OnboardingState } from "./onboarding";

/**
 * First-run guidance, as a checklist that persists rather than a gate that
 * vanishes.
 *
 * The previous version showed three steps and disappeared the moment a user had
 * one account and one transaction — which is exactly the point they knew least
 * about budgets, goals and sharing. Those features were never suggested again,
 * so the product stopped teaching itself right when it should have started.
 *
 * Now: five steps, a visible progress indicator, and only the current step
 * exposes an action so there is always exactly one obvious next move. It's
 * dismissible, because a checklist you can't get rid of stops being guidance
 * and becomes nagging.
 */
export function GettingStarted({
  state,
  onDismiss,
  compact = false,
}: {
  state: OnboardingState;
  onDismiss?: () => void;
  /**
   * Show only the step the user is actually on.
   *
   * Once there is an account and a transaction, the real dashboard exists —
   * and the full five-step card was taking the entire fold on a phone, so the
   * first thing a returning user saw was setup guidance rather than their
   * money. Completed steps have nothing left to teach; collapsing to the
   * current one keeps the single next move and returns the fold to the
   * balance.
   */
  compact?: boolean;
}) {
  const steps = buildSteps(state);
  const doneCount = steps.filter((s) => s.done).length;
  const currentIndex = steps.findIndex((s) => !s.done);
  const complete = currentIndex === -1;
  const pct = Math.round((doneCount / steps.length) * 100);
  const visibleSteps = compact && !complete ? steps.filter((_, i) => i === currentIndex) : steps;

  return (
    <section className="lf-onboard" aria-labelledby="onboard-title">
      <header className="lf-onboard-head">
        <div className="lf-onboard-head-main">
          <h2 className="lf-onboard-title" id="onboard-title">
            {complete ? "You're all set" : "Let's get you set up"}
          </h2>
          <p className="lf-onboard-sub">
            {complete
              ? "Everything's in place. This checklist won't come back."
              : "A few quick steps and your dashboard comes to life."}
          </p>
        </div>
        {onDismiss && (
          <button
            type="button"
            className="lf-btn lf-btn--ghost lf-iconbtn"
            onClick={onDismiss}
            aria-label="Dismiss the setup checklist"
          >
            <X size={16} strokeWidth={1.8} aria-hidden="true" />
          </button>
        )}
      </header>

      {/* Progress is stated in words as well as drawn, so it doesn't depend on
          seeing the bar or distinguishing its color. */}
      <div className="lf-onboard-progress">
        <div
          className="lf-onboard-progress-track"
          role="progressbar"
          aria-valuenow={doneCount}
          aria-valuemin={0}
          aria-valuemax={steps.length}
          aria-label="Setup progress"
        >
          <div className="lf-onboard-progress-fill" style={{ width: `${pct}%` }} />
        </div>
        <span className="lf-onboard-progress-label">
          {doneCount} of {steps.length} done
        </span>
      </div>

      <ol className="lf-onboard-steps">
        {visibleSteps.map((step) => {
          const i = steps.indexOf(step);
          const isCurrent = i === currentIndex;
          return (
            <li key={step.id} className="lf-onboard-step" data-done={step.done} data-current={isCurrent}>
              <span className="lf-onboard-marker" aria-hidden="true">
                {step.done ? <Check size={15} strokeWidth={3} /> : i + 1}
              </span>
              <div className="lf-onboard-step-main">
                <div className="lf-onboard-step-title">
                  {step.title}
                  {step.done && <span className="lf-visually-hidden"> — done</span>}
                </div>
                <p className="lf-onboard-step-body">{step.body}</p>
                {isCurrent && step.cta && (
                  <div className="lf-onboard-cta-row">
                    <Link className="lf-btn lf-btn--primary lf-btn--sm lf-onboard-cta" to={step.cta.to}>
                      {step.cta.label}
                      <ArrowRight size={15} strokeWidth={2} aria-hidden="true" />
                    </Link>
                    {step.secondary && (
                      <Link className="lf-onboard-secondary" to={step.secondary.to}>
                        {step.secondary.label}
                      </Link>
                    )}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
