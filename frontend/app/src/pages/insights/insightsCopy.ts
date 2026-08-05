import type { Anomaly, HealthScore, HealthScoreComponent, Recommendation } from "../../api/types";

export type Tone = "attention" | "soon" | "good" | "neutral";

/* ----------------------------------------------------------------- health --- */

const BAND_HEADLINE: Record<string, string> = {
  excellent: "Your finances are in great shape.",
  good: "You're in good shape overall.",
  fair: "You're doing okay, with a little room to improve.",
  "needs attention": "A few things could use your attention.",
  "not enough data": "There isn't enough recorded yet to score your finances honestly.",
};

export function bandTone(band: string): Tone {
  const b = band.toLowerCase();
  if (b === "excellent" || b === "good") return "good";
  if (b === "fair") return "soon";
  if (b === "needs attention") return "attention";
  return "neutral";
}

export function bandLabel(band: string): string {
  return band.charAt(0).toUpperCase() + band.slice(1);
}

/** A component with a real measurement behind it. */
export type MeasuredComponent = HealthScoreComponent & { score: number };

export interface HealthSummary {
  /** Null when the score couldn't honestly be stated. */
  score: number | null;
  band: string;
  bandLabel: string;
  headline: string;
  tone: Tone;
  strength: MeasuredComponent | null;
  watch: MeasuredComponent | null;
  /** Components with no basis yet — shown as gaps to fill, not as failures. */
  missing: HealthScoreComponent[];
}

/** Reduce the 5-part score to a plain-language read: one clear strength and,
 * if anything's lagging, one thing to watch.
 *
 * Only *measured* components are eligible to be either. A component with no
 * data behind it is neither a strength nor a weakness — it's a gap, and it is
 * reported separately so "we haven't been told" never reads as "you're doing
 * well here". */
export function healthSummary(health: HealthScore | undefined): HealthSummary | null {
  if (!health) return null;
  const measured = health.components.filter((c): c is MeasuredComponent => c.score !== null);
  const missing = health.components.filter((c) => c.score === null);
  const strength = measured.length
    ? measured.reduce((best, c) => (c.score > best.score ? c : best))
    : null;
  const lowest = measured.length
    ? measured.reduce((worst, c) => (c.score < worst.score ? c : worst))
    : null;
  // Only flag a watch-out if it's genuinely lagging.
  const watch = lowest && lowest.score < 60 ? lowest : null;
  return {
    score: health.score === null ? null : Math.round(health.score),
    band: health.band,
    bandLabel: bandLabel(health.band),
    headline: BAND_HEADLINE[health.band.toLowerCase()] ?? "Here's how your money is doing.",
    tone: bandTone(health.band),
    strength,
    watch,
    missing,
  };
}

/* --------------------------------------------------------------- greeting --- */

/** A warm one-line opener that reflects the overall picture and whether there's
 * anything to act on — never a wall of numbers. */
export function greeting(
  health: HealthScore | undefined,
  guidanceCount: number,
): { title: string; subtitle: string } {
  const headline = health ? BAND_HEADLINE[health.band.toLowerCase()] ?? "Here's your money check-in." : "Here's your money check-in.";
  let tail: string;
  if (guidanceCount === 0) {
    tail = "Nothing needs action right now — nice work.";
  } else if (guidanceCount === 1) {
    tail = "There's one suggestion below worth a look.";
  } else {
    tail = `There are ${guidanceCount} suggestions below that could help.`;
  }
  return { title: "Your money check-in", subtitle: `${headline} ${tail}` };
}

/* -------------------------------------------------------- recommendations --- */

export function recommendationTone(severity: string): Tone {
  const s = severity.toLowerCase();
  if (s === "attention") return "attention";
  if (s === "soon") return "soon";
  if (s === "good") return "good";
  return "neutral";
}

/** Map a recommendation to a concrete next step + where to do it. Positive
 * "good news" recommendations intentionally have no call to action. */
export function recommendationCta(rec: Recommendation): { label: string; to: string } | null {
  const actionType = rec.action?.action;
  const key = actionType || rec.kind;
  switch (key) {
    case "budget_rebalance":
    case "budget_create":
      return { label: "Open budgets", to: "/budgets" };
    case "bill_upcoming":
      return { label: "Review bills", to: "/bills" };
    case "subscription_review":
      return { label: "Review subscriptions", to: "/recurring" };
    default:
      return null;
  }
}

/** A plain, honest note about what the suggestion is based on — the trust cue. */
export function recommendationBasis(rec: Recommendation): string {
  switch (rec.kind) {
    case "budget_rebalance":
    case "budget_create":
      return "Based on your budgets this month.";
    case "bill_upcoming":
      return "Based on your upcoming bills.";
    case "savings_opportunity":
      return "Based on your income and spending.";
    case "subscription_review":
      return "Based on your recurring charges.";
    default:
      return "Based on your recent activity.";
  }
}

/* ------------------------------------------------------------- anomalies --- */

const ANOMALY_HEADLINE: Record<string, string> = {
  amount_spike: "A charge that's higher than usual",
  duplicate: "This might be a duplicate charge",
  new_payee_large: "A large charge to someone new",
  recurring_missed: "A regular charge didn't show up",
};

export function anomalyView(a: Anomaly): { headline: string; tone: Tone } {
  const headline = ANOMALY_HEADLINE[a.kind] ?? a.kind.replace(/_/g, " ");
  const tone: Tone = a.severity >= 0.75 ? "attention" : "soon";
  return { headline, tone };
}

/* ----------------------------------------------------------- suggestions --- */

/** Turn a raw confidence score into words people trust more than a percentage. */
export function confidenceLabel(confidence: number): string {
  if (confidence < 0.5) return "It's a guess";
  if (confidence < 0.8) return "Fairly sure";
  return "Very sure";
}
