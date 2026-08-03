import { Info } from "lucide-react";
import { useState } from "react";
import type { DebtStress } from "../../api/types";
import { Text } from "../../ui";

const BAND_LABELS: Record<DebtStress["band"], string> = {
  excellent: "Excellent",
  good: "Good",
  moderate: "Moderate",
  high: "High pressure",
  critical: "Critical",
};

/**
 * The Debt Stress Score.
 *
 * Higher is better, matching the financial health score — inverting one
 * relative to the other would be a persistent source of misreading.
 *
 * The derivation is always one click away, and the weakest component leads,
 * because that's where an improvement moves the total most. A composite score
 * nobody can interrogate is one they'll over-trust or ignore, and both are
 * worse than showing no score.
 */
export function DebtStressCard({ stress }: { stress: DebtStress }) {
  const [showWorking, setShowWorking] = useState(false);
  const circumference = 2 * Math.PI * 42;
  const filled = (stress.score / 100) * circumference;

  return (
    <section className="lf-stress" aria-labelledby="stress-title">
      <div className="lf-stress-main">
        <div className="lf-stress-dial" data-band={stress.band} data-provisional={stress.is_provisional}>
          <svg
            viewBox="0 0 100 100"
            role="img"
            aria-label={
              stress.is_provisional
                ? `Provisional debt stress score, about ${stress.score} out of 100, based on ` +
                  `${Math.round(stress.coverage * 100)}% of the usual inputs`
                : `Debt stress score ${stress.score} out of 100`
            }
          >
            <circle cx="50" cy="50" r="42" className="lf-stress-track" />
            <circle
              cx="50"
              cy="50"
              r="42"
              className="lf-stress-fill"
              strokeDasharray={`${filled} ${circumference}`}
              transform="rotate(-90 50 50)"
            />
          </svg>
          {/* The tilde is the cheapest honest signal available: it survives a
              screenshot, a glance, and being quoted out of context. */}
          <span className="lf-stress-value" aria-hidden="true">
            {stress.is_provisional ? "~" : ""}
            {stress.score}
          </span>
        </div>

        <div>
          <h2 className="lf-stress-title" id="stress-title">
            {BAND_LABELS[stress.band]}
            {stress.is_provisional && <span className="lf-stress-provisional-tag">Provisional</span>}
          </h2>
          {/* Saying the total is partial is more useful than presenting an
              incomplete score as complete. */}
          {stress.is_provisional && (
            <p className="lf-stress-provisional">
              <Info size={13} strokeWidth={2} aria-hidden="true" />
              Based on {Math.round(stress.coverage * 100)}% of the usual inputs — add your income
              for a fuller picture.
            </p>
          )}
          <button
            type="button"
            className="lf-insight-why-toggle"
            onClick={() => setShowWorking((v) => !v)}
            aria-expanded={showWorking}
          >
            How is this worked out?
          </button>
        </div>
      </div>

      {showWorking && (
        <div className="lf-stress-working">
          <ul className="lf-stress-components">
            {stress.components.map((component) => (
              <li key={component.key}>
                <div className="lf-stress-component-head">
                  <span className="lf-stress-component-label">{component.label}</span>
                  <span className="lf-stress-component-score">{component.score}</span>
                </div>
                <div
                  className="lf-stress-bar"
                  role="progressbar"
                  aria-valuenow={component.score}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={component.label}
                >
                  <div className="lf-stress-bar-fill" style={{ width: `${component.score}%` }} />
                </div>
                <Text as="span" tone="tertiary" size="xs">
                  {component.detail}
                </Text>
              </li>
            ))}
          </ul>

          {stress.missed_payment_penalty > 0 && (
            <p className="lf-stress-penalty">
              −{stress.missed_payment_penalty} for missed payments, applied after weighting.
            </p>
          )}

          <Text as="span" tone="tertiary" size="xs">
            {stress.method}
          </Text>
        </div>
      )}
    </section>
  );
}
