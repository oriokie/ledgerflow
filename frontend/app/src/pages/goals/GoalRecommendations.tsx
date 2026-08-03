import { Lightbulb } from "lucide-react";
import type { GoalRecommendation } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { Button, Card, Text } from "../../ui";
import { GOAL_KIND_ICONS, GOAL_KIND_LABELS } from "./kinds";

/**
 * Suggested goals, derived from the workspace's own figures.
 *
 * Renders nothing at all when there are no recommendations. That is deliberate:
 * the engine returns an empty list rather than filler when the user's data can't
 * support an honest suggestion, and a panel saying "no suggestions right now"
 * would reintroduce exactly the noise the engine avoids.
 *
 * Each card leads with the *reason* rather than the ask. "Your spending averages
 * £2,100 a month, so 3 months of cover would be £6,300" is a suggestion the user
 * can check against their own knowledge; "Build an emergency fund" is a slogan.
 */
export function GoalRecommendations({
  recommendations,
  onAccept,
}: {
  recommendations: GoalRecommendation[];
  onAccept?: (rec: GoalRecommendation) => void;
}) {
  if (recommendations.length === 0) return null;

  return (
    <section className="lf-goal-recs" aria-labelledby="goal-recs-title">
      <h2 className="lf-goal-recs-title" id="goal-recs-title">
        <Lightbulb size={15} strokeWidth={1.8} aria-hidden="true" />
        Suggested for you
      </h2>

      <div className="lf-goal-recs-list">
        {recommendations.map((rec) => {
          const Icon = GOAL_KIND_ICONS[rec.kind] ?? GOAL_KIND_ICONS.custom;
          return (
            <Card key={rec.kind} className="lf-goal-rec">
              <div className="lf-goal-rec-head">
                <span className="lf-goal-rec-icon" aria-hidden="true">
                  <Icon size={16} strokeWidth={1.8} />
                </span>
                <div>
                  <span className="lf-goal-rec-flag">Idea</span>
                  {/* <h3>, so the suggestions land in the page outline under
                      their own <h2> instead of being anonymous paragraphs. */}
                  <h3 className="lf-goal-rec-name">{rec.title}</h3>
                  <Text as="span" tone="tertiary" size="xs">
                    {GOAL_KIND_LABELS[rec.kind]}
                  </Text>
                </div>
              </div>

              {/* The rationale is the point — it's what makes the number checkable. */}
              <p className="lf-goal-rec-why">{rec.rationale}</p>

              <dl className="lf-goal-rec-figures">
                <div>
                  <dt>Suggested target</dt>
                  <dd>{formatAmount(rec.suggested_target_minor, rec.currency)}</dd>
                </div>
                {rec.suggested_monthly_minor !== null && (
                  <div>
                    <dt>Monthly</dt>
                    <dd>{formatAmount(rec.suggested_monthly_minor, rec.currency)}</dd>
                  </div>
                )}
              </dl>

              {onAccept && (
                <Button variant="secondary" size="sm" onClick={() => onAccept(rec)}>
                  Set this up
                </Button>
              )}
            </Card>
          );
        })}
      </div>
    </section>
  );
}
