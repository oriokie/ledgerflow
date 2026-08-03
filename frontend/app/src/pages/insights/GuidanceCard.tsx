import { CalendarClock, Lightbulb, PiggyBank, RefreshCw, TrendingUp, type LucideIcon } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { Recommendation } from "../../api/types";
import { Button } from "../../ui";
import { recommendationBasis, recommendationCta, recommendationTone } from "./insightsCopy";

const ICON: Record<string, LucideIcon> = {
  budget_rebalance: PiggyBank,
  budget_create: PiggyBank,
  bill_upcoming: CalendarClock,
  subscription_review: RefreshCw,
  savings_opportunity: TrendingUp,
};

/** One recommendation, framed as guidance: a plain title, a conversational
 * explanation, a single clear next step, and a quiet note on what it's based
 * on. Good-news items carry no action — guidance shouldn't nag. */
export function GuidanceCard({ rec }: { rec: Recommendation }) {
  const navigate = useNavigate();
  const tone = recommendationTone(rec.severity);
  const cta = recommendationCta(rec);
  const Icon = ICON[rec.kind] ?? Lightbulb;

  return (
    <div className={`lf-guidance lf-tone-${tone}`}>
      <span className="lf-guidance-icon">
        <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
      </span>
      <div className="lf-guidance-main">
        <div className="lf-guidance-title">{rec.title}</div>
        <p className="lf-guidance-body">{rec.body}</p>
        <div className="lf-guidance-foot">
          {cta && (
            <Button variant="secondary" size="sm" onClick={() => navigate(cta.to)}>
              {cta.label}
            </Button>
          )}
          <span className="lf-guidance-why">{recommendationBasis(rec)}</span>
        </div>
      </div>
    </div>
  );
}
