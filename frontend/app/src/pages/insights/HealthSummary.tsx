import { Check, TriangleAlert } from "lucide-react";
import { useState } from "react";
import type { HealthScore } from "../../api/types";
import { Button, Card, Figure, Meter, Text } from "../../ui";
import { healthSummary } from "./insightsCopy";

/** Health as a plain read: a band, one clear strength, and — only if something
 * lags — one thing to watch. The full 5-part breakdown stays one tap away, so
 * the score is always explainable rather than a black box. */
export function HealthSummary({ health }: { health: HealthScore }) {
  const s = healthSummary(health);
  const [open, setOpen] = useState(false);
  if (!s) return null;

  return (
    <Card title="Your financial health">
      <div className="lf-health-head">
        <span className={`lf-health-band lf-tone-${s.tone}`}>{s.bandLabel}</span>
        {/* No score is rendered as no score. Substituting a 0 or a dash-shaped
            number here would turn "we can't tell you yet" into a verdict.
            When the score rests on an incomplete set of components, that's
            said right next to the number — through Figure's `certainty` —
            rather than in a caveat the reader has to scroll to find. */}
        {s.score !== null && s.missing.length > 0 && (
          <Figure
            label="Score"
            value={
              <>
                {s.score}
                <span className="lf-health-score-suffix">/100</span>
              </>
            }
            size="secondary"
            certainty="speculative"
            confidence={`Not yet counted: ${s.missing.map((c) => c.name.toLowerCase()).join(", ")}.`}
          />
        )}
        {s.score !== null && s.missing.length === 0 && (
          <Figure
            label="Score"
            value={
              <>
                {s.score}
                <span className="lf-health-score-suffix">/100</span>
              </>
            }
            size="secondary"
          />
        )}
      </div>

      <p className="lf-guidance-body" style={{ marginBottom: "var(--lf-space-3)" }}>
        {s.headline}
      </p>

      <div className="lf-health-lines">
        {s.strength && (
          <div className="lf-health-line">
            <Check size={16} strokeWidth={2} className="lf-health-line-icon" style={{ color: "var(--lf-status-success)" }} aria-hidden="true" />
            <span>
              <strong>{s.strength.name}:</strong> {s.strength.detail}
            </span>
          </div>
        )}
        {s.watch && (
          <div className="lf-health-line">
            <TriangleAlert size={16} strokeWidth={2} className="lf-health-line-icon" style={{ color: "var(--lf-status-warning)" }} aria-hidden="true" />
            <span>
              <strong>Worth improving — {s.watch.name.toLowerCase()}:</strong> {s.watch.detail}
            </span>
          </div>
        )}
      </div>

      {/* What the score is still missing, stated plainly. This is the honest
          counterpart to no longer scoring absent data as full marks: the user
          learns what to record next rather than why their score dropped.
          Only needed here when there's no score above to carry the caveat
          itself — once a score exists, its Figure already says this. */}
      {s.score === null && s.missing.length > 0 && (
        <Text tone="tertiary" size="sm" style={{ marginTop: "var(--lf-space-2)", display: "block" }}>
          Once you've recorded a little more, this becomes a score you can rely on. Still needed:{" "}
          {s.missing.map((c) => c.name.toLowerCase()).join(", ")}.
        </Text>
      )}

      <div style={{ marginTop: "var(--lf-space-3)" }}>
        <Button variant="ghost" size="sm" onClick={() => setOpen((v) => !v)}>
          {open ? "Hide the breakdown" : "See the full breakdown"}
        </Button>
      </div>

      {open && (
        <div className="lf-health-detail">
          {health.components.map((c) => (
            <div key={c.name}>
              {c.score === null ? (
                <Text weight="medium" size="sm">
                  {c.name} — not measured yet
                </Text>
              ) : (
                <Meter value={Math.min(100, c.score)} label={c.name} caption={Math.round(c.score)} />
              )}
              <Text tone="tertiary" size="sm" style={{ marginTop: "var(--lf-space-1)" }}>
                {c.detail}
              </Text>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
